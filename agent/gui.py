"""
gui.py — Janela do Órbita.

A interface é uma página web local (agent/ui/web) desenhada pelo motor Chromium do Qt.
O Python fala com ela pela ponte `Api` (QWebChannel): a página chama métodos (slots) e
recebe eventos em tempo real (texto em streaming, ferramentas, subagentes, notificações).

Segurança: a página só carrega arquivos locais, links externos abrem no navegador do sistema,
o HTML vindo de modelos é sanitizado (render.py) e há Content-Security-Policy restrita.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import httpx
from PyQt6.QtCore import QObject, Qt, QThread, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMenu, QSystemTrayIcon

from agent import __version__
from agent.core import checkpoints, grok_cli, mentions, routing
from agent.core.brain import Brain
from agent.core.config import (
    DATA_DIR, GUI_VOICE_MAX_RECORD_SECONDS, GUI_VOICE_NO_SPEECH_TIMEOUT, GUI_VOICE_SILENCE_SECONDS, LOGS_DIR,
    PROJECT_ROOT,
)
from agent.core.profiles import ALL_GROUPS, Profile
from agent.core.providers import probe_compat_models
from agent.core.settings import DEFAULT_PROVIDERS
from agent.ui import brand, render

logger = logging.getLogger(__name__)

WEB_INDEX = brand.WEB_DIR / "index.html"
SETTABLE = {"theme", "user_name", "default_workspace", "native_notifications", "show_reasoning", "permission_mode",
            "economy_mode", "turn_token_budget", "daily_token_budget", "voice_replies", "auto_routing",
            "cheap_model", "image_model", "ollama_num_ctx", "ollama_keep_alive", "checkpoints"}
# Modo plano: vai junto da mensagem; as ferramentas que alteram algo ficam bloqueadas no turno.
PLAN_NOTE = ("\n\n[Modo plano] Ainda NÃO execute: não crie, edite nem apague arquivos e não rode comandos que "
             "alterem algo — essas ferramentas estão bloqueadas neste turno. Leia e pesquise o que precisar e "
             "responda com um plano curto: objetivo, arquivos envolvidos, passos numerados, riscos e como "
             "verificar. Termine perguntando se pode executar.")
_MENTIONS_MARK = "\n\n---\nArquivos citados pelo usuário"
QUICK_PROMPTS = [
    {"label": "Resumir esta conversa", "text": "Resuma o que fizemos até agora e o que ficou pendente."},
    {"label": "Revisar com a equipe", "text": "Peça ao revisor da equipe para revisar o que foi feito e corrija os problemas encontrados."},
    {"label": "Status do PC", "text": "Mostre o status do sistema (CPU, RAM, disco e GPU)."},
]


def _short_model(ref: str) -> str:
    """'ollama:hf.co/autor/Modelo-27B-GGUF:Q4' → 'ollama:Modelo-27B-GGUF:Q4' (só para exibir)."""
    provider, _, model = (ref or "").partition(":")
    return f"{provider}:{model.rsplit('/', 1)[-1]}" if model else ref


def _args_summary(args: dict, limit: int = 120) -> str:
    for key in ("path", "command", "query", "url", "name", "pattern", "keys", "text", "prompt", "fact"):
        if isinstance(args.get(key), str):
            value = " ".join(args[key].split())
            return value if len(value) <= limit else value[:limit] + "…"
    if args.get("tasks"):
        return f"{len(args['tasks'])} tarefa(s)"
    raw = json.dumps(args, ensure_ascii=False)
    return raw if len(raw) <= limit else raw[:limit] + "…"


def _visible_user_text(text: str) -> str:
    """O que o usuário digitou, sem o anexo de @arquivos nem a nota do modo plano."""
    return text.split(_MENTIONS_MARK, 1)[0].replace(PLAN_NOTE, "")


def project_folder(brain: Brain) -> Optional[Path]:
    """Pasta do projeto escolhida pelo usuário (None se ele ainda não escolheu nenhuma)."""
    chosen = (brain.profile.workspace or "").strip() or (brain.settings.get("default_workspace") or "").strip()
    if not chosen:
        return None
    folder = brain.effective_workspace()
    return folder if folder.is_dir() else None


# ─────────────────────────────────────────────────────────────
# Trabalho em segundo plano
# ─────────────────────────────────────────────────────────────

class AgentWorker(QThread):
    """Processa pedidos (texto, voz, prompt inicial) em sequência, fora da interface."""

    raw_event = pyqtSignal(str, object)
    busy = pyqtSignal(bool)

    def __init__(self, brain: Brain, push):
        super().__init__()
        self.brain = brain
        self.push = push
        self.commands: queue.Queue = queue.Queue()
        self.running = True
        self._approval_lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, list]] = {}
        self.checkpoints = checkpoints.Checkpoints()
        self.plan_active = False

    def approve(self, request: dict) -> str:
        """Chamado pelas threads do agente; bloqueia até a resposta do usuário na interface."""
        if self.plan_active and request.get("type") == "tool":
            return "no"   # modo plano: nada que altere arquivos ou rode comandos
        with self._approval_lock:
            approval_id = uuid.uuid4().hex[:10]
            done, answer = threading.Event(), ["no"]
            self._pending[approval_id] = (done, answer)
            self.push({"type": "approval", "id": approval_id, "request": request})
            self.raw_event.emit("attention", {"title": "Permissão necessária", "text": request.get("tool", "")})
            while not done.wait(0.2):
                if not self.running:
                    break
            self._pending.pop(approval_id, None)
            return answer[0]

    def answer(self, approval_id: str, value: str) -> None:
        pending = self._pending.get(approval_id)
        if pending:
            pending[1][0] = value if value in ("yes", "always", "no") else "no"
            pending[0].set()

    def deny_pending(self) -> None:
        """Parar: nenhuma confirmação fica esperando um clique que não vai chegar."""
        for done, answer in list(self._pending.values()):
            answer[0] = "no"
            done.set()

    def events(self, kind: str, data: dict) -> None:
        self.raw_event.emit(kind, data)

    def run(self) -> None:
        while self.running:
            try:
                command, payload = self.commands.get(timeout=0.2)
            except queue.Empty:
                continue
            if command == "quit":
                break
            self.busy.emit(True)
            try:
                if command == "voice":
                    self._voice()
                elif command == "turn":
                    self._turn(*payload)
            except Exception as error:
                logger.exception("Falha no processamento")
                self.events("error", {"message": f"Falha: {error}"})
            finally:
                self.busy.emit(False)

    def _turn(self, text: str, images: list[str], speak: bool, plan: bool = False) -> None:
        provider, model = self.brain.current_model
        self.events("turn_start", {"model": f"{provider}:{model}"})
        folder = project_folder(self.brain) if self.brain.settings.get("checkpoints", True) else None
        label = " ".join(_visible_user_text(text).split())[:120]
        before = self.checkpoints.snapshot(folder, f"antes: {label}") if folder and not plan else None
        with self._plan_mode(plan):
            response = self.brain.run_turn(text, images, events=self.events, approve=self.approve)
        self.events("turn_end", {"text": response, "plan": plan})
        turn = self.checkpoints.finish(folder, before, f"depois: {label}") if before else None
        if turn:
            self.events("checkpoint", {"workspace": turn.workspace, "before": turn.before, "after": turn.after,
                                       "changes": [asdict(c) for c in turn.changes]})
        if speak and self.brain.settings.get("voice_replies", True) and self.running:
            spoken = render.speech_text(response)
            if spoken:
                self.events("status", {"text": "Falando…"})
                self.brain.speaker.speak(spoken, blocking=True)

    @contextmanager
    def _plan_mode(self, on: bool):
        """No modo plano tudo que altera pede permissão, e `approve` nega sem perguntar."""
        if not on:
            yield
            return
        settings = self.brain.settings
        previous = settings.get("permission_mode", "auto")
        session = self.brain.session
        allowed = set(session.always_allowed) if session else set()
        if session:
            session.always_allowed.clear()
        settings.set("permission_mode", "perguntar", save=False)
        self.plan_active = True
        try:
            yield
        finally:
            self.plan_active = False
            settings.set("permission_mode", previous)
            if self.brain.session:
                self.brain.session.always_allowed |= allowed

    def _voice(self) -> None:
        self.push({"type": "listening"})
        self.brain.speaker.play_beep(frequency=880, duration=0.12)
        text = self.brain.listener.listen(max_seconds=GUI_VOICE_MAX_RECORD_SECONDS,
                                          silence_threshold=GUI_VOICE_SILENCE_SECONDS,
                                          no_speech_timeout=GUI_VOICE_NO_SPEECH_TIMEOUT)
        if not text:
            self.push({"type": "toast", "kind": "warn", "title": "Microfone", "text": "Nenhuma fala detectada."})
            return
        self.push({"type": "voice_text", "text": text})
        self._turn(text, [], True)

    def stop(self) -> None:
        self.running = False
        self.brain.stop()
        for done, _ in list(self._pending.values()):
            done.set()
        self.commands.put(("quit", None))


# ─────────────────────────────────────────────────────────────
# Ponte com a página
# ─────────────────────────────────────────────────────────────

class Api(QObject):
    """Métodos chamados pela página (JS) e eventos enviados a ela."""

    message = pyqtSignal(str)   # não usar "event": conflita com QObject.event()
    _relay = pyqtSignal(str)

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.win = window
        self.brain = window.brain
        self._relay.connect(self.message)   # emissões de outras threads chegam enfileiradas
        self._grok_cache: tuple[float, dict] = (0.0, {})

    def push(self, payload: dict) -> None:
        self._relay.emit(json.dumps(payload, ensure_ascii=False, default=str))

    # ── Estado ───────────────────────────────────────────────

    def grok_status(self, fresh: bool = False) -> dict:
        if fresh or time.time() - self._grok_cache[0] > 60:
            self._grok_cache = (time.time(), grok_cli.status())
        return self._grok_cache[1]

    def profile_view(self, profile: Profile) -> dict:
        data = asdict(profile)
        settings = self.brain.settings
        if profile.model_ref:
            data["model_label"] = _short_model(profile.model_ref)
        elif profile.in_team:
            routed = self.brain.route_model(routing.specialty_for(profile))
            data["model_label"] = f"auto · {_short_model(routed)}" if routed else (settings.get("cheap_model") or "modelo principal")
        else:
            data["model_label"] = "modelo principal"
        data["bound"] = bool(profile.provider and profile.model
                             and settings.profile_for_model(profile.provider, profile.model) == profile.id)
        return data

    def state(self) -> dict:
        brain, settings = self.brain, self.brain.settings
        provider, model = brain.current_model
        workspace = brain.effective_workspace()
        providers = []
        for name, cfg in settings.providers().items():
            providers.append({"id": name, "label": cfg.get("label", name), "type": cfg.get("type"),
                              "base_url": cfg.get("base_url", ""),
                              "builtin": name in DEFAULT_PROVIDERS,
                              "api_key_env": cfg.get("api_key_env", ""), "has_credentials": settings.has_credentials(name),
                              "models": cfg.get("models", [])})
        profiles = [self.profile_view(p) for p in brain.profiles.list()]
        session = brain.session
        return {
            "settings": {key: settings.get(key) for key in SETTABLE | {"onboarded"}},
            "profile": self.profile_view(brain.profile),
            "profiles": profiles,
            "team": [p for p in profiles if p["in_team"]],
            "provider": provider, "model": model, "model_label": _short_model(f"{provider}:{model}"),
            "workspace": str(workspace),
            "workspace_name": workspace.name,
            "recent_workspaces": brain.recent_workspaces(),
            "projects_parent": str(brain.default_projects_parent()),
            "workspace_set": bool((brain.profile.workspace or "").strip() or (settings.get("default_workspace") or "").strip()),
            "providers": providers,
            "mcp": brain.mcp.status(),
            "skills": [{"name": s.name, "description": s.description, "origin": s.origin}
                       for s in sorted(brain.skills.skills.values(), key=lambda s: s.name)],
            "conversations": brain.conversations.list(),
            "conversation_id": brain.conversation_id,
            "conversation_title": brain.conversation_title,
            "conversation_tokens": session.total_tokens if session else 0,
            "usage": brain.usage.today(),
            "grok": self.grok_status(),
            "local_models": brain.local_models(),
            "all_groups": ALL_GROUPS,
            "quick_prompts": QUICK_PROMPTS,
            "pygments_css": render.pygments_css(),
            "version": __version__,
        }

    def _state_json(self) -> str:
        return json.dumps(self.state(), ensure_ascii=False, default=str)

    @pyqtSlot(result=str)
    def getState(self) -> str:
        return self._state_json()

    # ── Conversa ─────────────────────────────────────────────

    @pyqtSlot(str)
    def send(self, raw: str) -> None:
        data = json.loads(raw)
        plan = bool(data.get("plan"))
        text = data.get("text", "") + (PLAN_NOTE if plan else "")
        folder = project_folder(self.brain)
        if folder is not None and "@" in text:
            try:
                text = mentions.expand(text, folder)
            except OSError as error:
                logger.warning("Falha ao anexar @arquivos: %s", error)
        self.win.worker.commands.put(("turn", (text, data.get("images") or [], False, plan)))

    @pyqtSlot(str, result=str)
    def searchFiles(self, query: str) -> str:
        folder = project_folder(self.brain)
        return json.dumps(mentions.search(folder, query) if folder else [], ensure_ascii=False)

    # ── Checkpoints (desfazer o que uma resposta mudou) ──────

    @pyqtSlot(str, result=str)
    def checkpointDiff(self, raw: str) -> str:
        data = json.loads(raw)
        try:
            text = self.win.worker.checkpoints.diff(Path(data["workspace"]), data["before"], data["after"])
        except Exception as error:
            return json.dumps({"error": f"Não consegui montar o diff: {error}"}, ensure_ascii=False)
        return json.dumps({"diff": text}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def checkpointUndo(self, raw: str) -> str:
        if self.win.busy:
            return json.dumps({"error": "Espere o agente terminar antes de desfazer."}, ensure_ascii=False)
        data = json.loads(raw)
        try:
            result = self.win.worker.checkpoints.undo(Path(data["workspace"]), data["before"], data["after"])
        except Exception as error:
            return json.dumps({"error": f"Não consegui desfazer: {error}"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    @pyqtSlot()
    def stop(self) -> None:
        self.brain.stop()
        self.win.worker.deny_pending()
        self.push({"type": "status", "text": "Parando…"})

    @pyqtSlot()
    def voice(self) -> None:
        self.win.worker.commands.put(("voice", None))

    @pyqtSlot(str, str)
    def answerApproval(self, approval_id: str, value: str) -> None:
        self.win.worker.answer(approval_id, value)

    @pyqtSlot(result=str)
    def newConversation(self) -> str:
        if self.win.busy:
            self.brain.stop()
        self.brain.new_conversation()
        self.win.start_prompt_if_any()
        return "{}"

    @pyqtSlot(result=str)
    def listConversations(self) -> str:
        return json.dumps(self.brain.conversations.list(), ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def openConversation(self, conversation_id: str) -> str:
        data = self.brain.open_conversation(conversation_id)
        if not data:
            return "null"
        for block in data["blocks"]:
            if block["kind"] == "user":
                block["text"] = _visible_user_text(block.get("text") or "")
            elif block["kind"] == "assistant":
                block["html"] = render.markdown_html(block.pop("md"))
            elif block["kind"] == "tool":
                block["summary"] = _args_summary(block.get("args") or {})
        payload = {"id": data["id"], "title": data.get("title", ""), "blocks": data["blocks"],
                   "model_label": f"{data.get('provider', '')}:{data.get('model', '')}"}
        return json.dumps(payload, ensure_ascii=False, default=str)

    @pyqtSlot(str, result=str)
    def deleteConversation(self, conversation_id: str) -> str:
        return json.dumps(self.brain.conversations.delete(conversation_id))

    @pyqtSlot(str, str, result=str)
    def renameConversation(self, conversation_id: str, title: str) -> str:
        ok = self.brain.conversations.rename(conversation_id, title)
        if ok and conversation_id == self.brain.conversation_id:
            self.brain.conversation_title = title.strip()[:80]
        return json.dumps(ok)

    # ── Perfis, modelos e configurações ──────────────────────

    @pyqtSlot(str, result=str)
    def selectProfile(self, profile_id: str) -> str:
        self.brain.select_profile(profile_id)
        return self._state_json()

    @pyqtSlot(str, str, result=str)
    def selectModel(self, provider: str, model: str) -> str:
        bound = self.brain.select_model(provider, model.strip()) if model.strip() else None
        return json.dumps({"state": self.state(), "bound_profile": bound.name if bound else None},
                          ensure_ascii=False, default=str)

    @pyqtSlot(str, str, result=str)
    def setSetting(self, key: str, raw: str) -> str:
        if key in SETTABLE:
            self.brain.settings.set(key, json.loads(raw))
        return self._state_json()

    @pyqtSlot(str, str, result=str)
    def saveApiKey(self, env: str, value: str) -> str:
        allowed = {cfg.get("api_key_env") for cfg in self.brain.settings.providers().values()}
        if env in allowed and value.strip():
            self.brain.settings.save_api_key(env, value.strip())
        return self._state_json()

    @pyqtSlot(str, result=str)
    def addProvider(self, raw: str) -> str:
        data = json.loads(raw)
        models = data.get("models") or ""
        if isinstance(models, str):
            models = [item.strip() for item in models.split(",") if item.strip()]
        model = (data.get("model") or "").strip()
        if model and model not in models:
            models.insert(0, model)
        try:
            provider_id = self.brain.settings.add_custom_provider(
                label=(data.get("label") or data.get("id") or "").strip(),
                base_url=(data.get("url") or "").strip(),
                api_key=data.get("key") or "",
                models=models,
            )
        except ValueError as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False)
        if data.get("use", True) and model:
            self.brain.select_model(provider_id, model)
        return json.dumps({"state": self.state(), "id": provider_id}, ensure_ascii=False, default=str)

    @pyqtSlot(str, result=str)
    def removeProvider(self, provider_id: str) -> str:
        try:
            self.brain.settings.remove_custom_provider(provider_id)
        except ValueError as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False)
        return json.dumps({"state": self.state()}, ensure_ascii=False, default=str)

    @pyqtSlot(str)
    def probeProvider(self, raw: str) -> None:
        data = json.loads(raw)

        def work():
            result = probe_compat_models(data.get("url") or "", data.get("key") or "")
            self.push({"type": "probe", **result})

        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot(str, result=str)
    def setWorkspace(self, path: str) -> str:
        try:
            self.brain.set_workspace(path)
        except ValueError as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False)
        return json.dumps({"state": self.state()}, ensure_ascii=False, default=str)

    @pyqtSlot(str, result=str)
    def createWorkspace(self, raw: str) -> str:
        data = json.loads(raw)
        try:
            self.brain.create_workspace(data.get("parent") or "", data.get("name") or "")
        except ValueError as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False)
        except OSError as error:
            return json.dumps({"error": f"Não consegui criar a pasta: {error.strerror or error}"}, ensure_ascii=False)
        return json.dumps({"state": self.state()}, ensure_ascii=False, default=str)

    @pyqtSlot(str, result=str)
    def saveProfile(self, raw: str) -> str:
        data = json.loads(raw)
        bind = data.pop("bind", False)
        manager = self.brain.profiles
        if not data.get("id"):
            base = manager.slugify(data.get("name", "perfil"))
            data["id"] = base if base not in manager.profiles else f"{base}_{len(manager.profiles)}"
        try:
            profile = Profile.from_dict(data)
            manager.save(profile)
        except (TypeError, ValueError) as error:
            return json.dumps({"error": str(error)})
        if profile.provider and profile.model:
            current = self.brain.settings.profile_for_model(profile.provider, profile.model)
            if bind:
                self.brain.settings.bind_model_profile(profile.provider, profile.model, profile.id)
            elif current == profile.id:
                self.brain.settings.bind_model_profile(profile.provider, profile.model, None)
        return self._state_json()

    @pyqtSlot(str, result=str)
    def deleteProfile(self, profile_id: str) -> str:
        self.brain.profiles.delete(profile_id)
        if self.brain.settings.get("active_profile") == profile_id:
            self.brain.select_profile("geral")
        return self._state_json()

    @pyqtSlot(str, result=str)
    def completeOnboarding(self, raw: str) -> str:
        data = json.loads(raw)
        settings = self.brain.settings
        settings.set("user_name", data.get("user_name", "").strip(), save=False)
        settings.set("default_workspace", data.get("workspace", "").strip(), save=False)
        if data.get("permission_mode") in ("perguntar", "auto", "livre"):
            settings.set("permission_mode", data["permission_mode"], save=False)
        settings.set("voice_replies", bool(data.get("voice_replies")), save=False)
        settings.set("onboarded", True)
        provider, model = data.get("provider"), (data.get("model") or "").strip()
        if provider in settings.providers():
            env = settings.provider(provider).get("api_key_env")
            if env and data.get("key"):
                settings.save_api_key(env, data["key"].strip())
            if model:
                self.brain.select_model(provider, model)
        if data.get("user_name"):
            self.brain.memory.user_name = data["user_name"].strip()
        return self._state_json()

    @pyqtSlot(str)
    def refreshModels(self, provider: str) -> None:
        def work():
            try:
                models = self.brain.list_models(provider)
            except Exception:
                models = []
            self.push({"type": "models", "provider": provider, "models": models})
        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot(result=str)
    def localModels(self) -> str:
        base = self.brain.settings.provider("ollama").get("base_url", "http://127.0.0.1:11434").rstrip("/")
        try:
            models = httpx.get(f"{base}/api/tags", timeout=4).json().get("models", [])
        except Exception:
            return "[]"
        rows = [{"name": m["name"], "size": f"{m.get('size', 0) / 1e9:.1f} GB",
                 "params": (m.get("details") or {}).get("parameter_size", "")} for m in models]
        return json.dumps(sorted(rows, key=lambda r: r["name"]))

    @pyqtSlot(str)
    def pullModel(self, name: str) -> None:
        base = self.brain.settings.provider("ollama").get("base_url", "http://127.0.0.1:11434").rstrip("/")

        def work():
            last = 0.0
            try:
                with httpx.stream("POST", f"{base}/api/pull", json={"model": name, "stream": True}, timeout=None) as r:
                    for line in r.iter_lines():
                        if not line.strip():
                            continue
                        item = json.loads(line)
                        if item.get("error"):
                            raise RuntimeError(item["error"])
                        if time.time() - last > 0.4:
                            last = time.time()
                            self.push({"type": "pull", "model": name, "status": item.get("status", ""),
                                       "completed": item.get("completed", 0), "total": item.get("total", 0)})
                self.brain._local_models = None
                self.push({"type": "pull", "model": name, "status": "concluído", "completed": 1, "total": 1, "done": True})
            except Exception as error:
                self.push({"type": "pull", "model": name, "done": True, "error": f"Falha ao baixar {name}: {error}"})
        threading.Thread(target=work, daemon=True).start()

    # ── MCP, Grok, arquivos ──────────────────────────────────

    @pyqtSlot(str, bool)
    def mcpToggle(self, name: str, enabled: bool) -> None:
        threading.Thread(target=self.brain.mcp.set_enabled, args=(name, enabled), daemon=True).start()

    @pyqtSlot()
    def mcpReload(self) -> None:
        threading.Thread(target=self.brain.mcp.reload, daemon=True).start()

    @pyqtSlot(result=str)
    def mcpImport(self) -> str:
        return json.dumps(self.brain.mcp.import_external())

    @pyqtSlot(str, result=str)
    def grok(self, action: str) -> str:
        message = ""
        try:
            if action == "login":
                grok_cli.login()
                message = "Abrindo o login no navegador… depois clique em atualizar."
            elif action == "device":
                grok_cli.login(device_code=True)
                message = "Siga o código mostrado na janela que abriu."
            elif action == "logout":
                message = grok_cli.logout()
            elif action == "install":
                grok_cli.install()
                message = "Instalador oficial aberto no PowerShell."
        except Exception as error:
            message = str(error)
        return json.dumps({"message": message, "status": self.grok_status(fresh=True)})

    @pyqtSlot(result=str)
    def pickImages(self) -> str:
        files, _ = QFileDialog.getOpenFileNames(self.win, "Anexar imagens", str(Path.home()),
                                                "Imagens (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        return json.dumps(files)

    @pyqtSlot(str, result=str)
    def pickFolder(self, current: str) -> str:
        return QFileDialog.getExistingDirectory(self.win, "Escolher pasta", current or str(Path.home())) or ""

    @pyqtSlot(str)
    def openPath(self, target: str) -> None:
        named = {"mcp": self.brain.mcp.config_path, "data": DATA_DIR, "logs": LOGS_DIR,
                 "roadmap": PROJECT_ROOT / "ROADMAP.md", "license": PROJECT_ROOT / "LICENSE",
                 "catalog": routing.CATALOG_FILE}
        if target == "catalog":
            routing.load_catalog()
        path = Path(named.get(target, target))
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @pyqtSlot(str)
    def revealPath(self, path: str) -> None:
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    @pyqtSlot(str)
    def openUrl(self, url: str) -> None:
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))
        elif url.startswith("file:"):
            local = QUrl(url).toLocalFile()
            if os.path.exists(local):
                QDesktopServices.openUrl(QUrl.fromLocalFile(local))

    @pyqtSlot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)


# ─────────────────────────────────────────────────────────────
# Página e janela
# ─────────────────────────────────────────────────────────────

class LocalPage(QWebEnginePage):
    """Só a interface local navega dentro da janela; o resto abre no navegador do sistema."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # type: ignore[override]
        if url.isLocalFile() and Path(url.toLocalFile()).resolve() == WEB_INDEX.resolve():
            return True
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
        return False

    def javaScriptConsoleMessage(self, level, message, line, source):  # type: ignore[override]
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logger.warning("JS: %s (%s:%s)", message, source, line)


class MainWindow(QMainWindow):

    def __init__(self, brain: Brain):
        super().__init__()
        self.brain = brain
        self.busy = False
        self.setWindowTitle(brand.APP_NAME)
        self.setWindowIcon(brand.app_icon())
        self.resize(1480, 920)
        self.setMinimumSize(1080, 680)

        self.api = Api(self)
        self.worker = AgentWorker(brain, self.api.push)
        self.worker.raw_event.connect(self.on_agent_event)
        self.worker.busy.connect(self.on_busy)

        self.view = QWebEngineView(self)
        self.view.setPage(LocalPage(self.view))
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        page_settings = self.view.page().settings()
        page_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        page_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.view.page().setBackgroundColor(Qt.GlobalColor.black)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("api", self.api)
        self.view.page().setWebChannel(self.channel)
        self.view.load(QUrl.fromLocalFile(str(WEB_INDEX)))
        self.setCentralWidget(self.view)

        # Estado do streaming do turno atual
        self._seg_id: Optional[str] = None
        self._seg_text = ""
        self._seg_dirty = False
        self._reasoning = ""
        self._reasoning_dirty = False
        self._streamed_any = False
        self._flush = QTimer(self)
        self._flush.timeout.connect(self._flush_stream)
        self._flush.start(70)

        self._tray = self._make_tray()
        brain.mcp.listeners.append(lambda: self.api.push({"type": "mcp", "servers": brain.mcp.status()}))
        self.worker.start()
        QTimer.singleShot(900, self.start_prompt_if_any)

    def _make_tray(self) -> Optional[QSystemTrayIcon]:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(brand.app_icon(), self)
        tray.setToolTip(f"{brand.APP_NAME} — {brand.TAGLINE}")
        menu = QMenu()
        menu.addAction("Mostrar", self.showNormal)
        menu.addAction("Nova conversa", lambda: (self.api.newConversation(), self.api.push({"type": "state", "state": self.api.state()})))
        menu.addSeparator()
        menu.addAction("Sair", self.close)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        return tray

    def notify(self, title: str, text: str) -> None:
        """Notificação do Windows só quando a janela não está em foco."""
        if self._tray and not self.isActiveWindow() and self.brain.settings.get("native_notifications", True):
            self._tray.showMessage(title, text[:240], brand.app_icon(), 6000)

    def start_prompt_if_any(self) -> None:
        startup = self.brain.startup_prompt()
        if startup and not self.busy:
            self.api.push({"type": "voice_text", "text": startup})
            self.api.push({"type": "toast", "kind": "info", "title": "Prompt inicial",
                           "text": f"Enviado pelo perfil {self.brain.profile.name}"})
            self.worker.commands.put(("turn", (startup, [], False)))

    # ── Tradução dos eventos do agente para a página ─────────

    def on_busy(self, busy: bool) -> None:
        self.busy = busy
        self.api.push({"type": "busy", "busy": busy})

    def _close_segment(self) -> None:
        if self._seg_id is not None:
            self.api.push({"type": "seg", "id": self._seg_id, "html": render.markdown_html(self._seg_text), "streaming": False})
        self._seg_id, self._seg_text, self._seg_dirty = None, "", False

    def _flush_stream(self) -> None:
        if self._seg_dirty and self._seg_id is not None:
            self._seg_dirty = False
            self.api.push({"type": "seg", "id": self._seg_id, "html": render.markdown_html(self._seg_text), "streaming": True})
        if self._reasoning_dirty:
            self._reasoning_dirty = False
            self.api.push({"type": "reasoning", "text": self._reasoning[-600:]})

    def on_agent_event(self, kind: str, data: dict) -> None:
        agent = data.get("agent", "principal")
        push = self.api.push
        if kind == "turn_start":
            self._seg_id, self._seg_text, self._reasoning, self._streamed_any = None, "", "", False
            push({"type": "turn_start", "model": _short_model(data.get("model", ""))})
        elif kind == "text":
            if self._seg_id is None:
                self._seg_id = uuid.uuid4().hex[:8]
                self._seg_text = ""
            self._seg_text += data["text"]
            self._seg_dirty = self._streamed_any = True
        elif kind == "reasoning":
            self._reasoning += data["text"]
            self._reasoning_dirty = True
        elif kind == "tool_start":
            self._close_segment()
            push({"type": "tool", "id": data["id"], "name": data["name"], "status": "running", "agent": agent,
                  "summary": _args_summary(data.get("args") or {})})
        elif kind == "tool_end":
            push({"type": "tool", "id": data["id"], "name": data["name"], "agent": agent,
                  "status": "error" if data.get("is_error") else "ok", "result": data.get("result", "")[:3000],
                  "images": data.get("images") or []})
        elif kind == "preview":
            path = data.get("path", "")
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
                push({"type": "preview", "path": path, "kind": "image"})
            else:
                try:
                    content = Path(path).read_text(encoding="utf-8", errors="replace")[:150_000]
                except OSError as error:
                    content = str(error)
                html = render.markdown_html(content if path.lower().endswith(".md")
                                            else f"```{Path(path).suffix.lstrip('.')}\n{content}\n```")
                push({"type": "preview", "path": path, "kind": "text", "html": html})
        elif kind == "subagent_start":
            self._close_segment()
            push({"type": "sub_start", "agent": data["agent"], "model": data.get("model", ""), "task": data.get("task", "")})
        elif kind == "subagent_end":
            push({"type": "sub_end", "agent": data["agent"], "tokens": data.get("tokens", 0), "model": ""})
        elif kind == "turn_end":
            text = data.get("text") or ""
            if self._seg_id is not None:
                self._close_segment()
            elif not self._streamed_any and text and not text.startswith("⚠️"):
                push({"type": "seg", "id": uuid.uuid4().hex[:8], "html": render.markdown_html(text), "streaming": False})
            push({"type": "turn_end", "conversation_id": self.brain.conversation_id,
                  "title": self.brain.conversation_title, "plan": bool(data.get("plan"))})
            self.notify("Tarefa concluída", render.speech_text(text, 200) or "O agente terminou.")
        elif kind == "usage":
            push({"type": "usage", "total": data.get("total", 0), "turn": data.get("turn", 0)})
        elif kind == "error":
            push({"type": "error", "message": data.get("message", "")})
        elif kind == "status":
            push({"type": "status", "text": data.get("text", "")})
            if str(data.get("text", "")).startswith("Modelo sem"):
                push({"type": "toast", "kind": "info", "title": "Modo compatível", "text": data["text"]})
        elif kind == "compacted":
            push({"type": "compacted", "messages": data.get("messages", 0)})
        elif kind == "checkpoint":
            push({"type": "checkpoint", **data})
        elif kind == "model_start" and agent == "principal":
            push({"type": "status", "text": "Pensando…"})
        elif kind == "attention":
            self.notify(data.get("title", ""), data.get("text", ""))
            QApplication.alert(self, 0)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.worker.stop()
        self.worker.wait(3000)
        if self._tray:
            self._tray.hide()
        self.brain.shutdown()
        event.accept()


def launch_gui(brain: Brain) -> None:
    brand.register_windows_app()
    if os.environ.get("AGENTE_DEVTOOLS"):
        os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", "9229")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(brand.APP_NAME)
    app.setApplicationDisplayName(brand.APP_NAME)
    app.setWindowIcon(brand.app_icon())
    brand.ensure_ico()
    window = MainWindow(brain)
    window.showMaximized()  # abre ocupando a tela toda
    sys.exit(app.exec())
