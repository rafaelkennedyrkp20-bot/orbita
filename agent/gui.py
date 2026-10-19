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
import re
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
from agent.core import checkpoints, grok_cli, mentions, routing, toolbox, updater
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
            "cheap_model", "image_model", "ollama_num_ctx", "ollama_keep_alive", "checkpoints", "update_check",
            "team_model", "stt_model", "stt_engine", "team_max_parallel", "execution_policy",
            "file_scope"}
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


_KEY_PREFIX = re.compile(r"^(sk|sk-or|sk-ant|rv|gsk|xai|pplx|csk|r8|hf|ghp|AIza)[-_]?[A-Za-z0-9]", re.I)


def looks_like_secret(text: str, known_keys: tuple[str, ...] = ()) -> bool:
    """Chave de API colada no lugar do nome do modelo (acontece muito na tela de API manual)."""
    text = (text or "").strip()
    if not text:
        return False
    if any(key and text == key.strip() for key in known_keys):
        return True
    if "/" in text or ":" in text or " " in text:
        return False   # nomes de modelo: "meta-llama/...", "qwen3:14b"
    longest = max((len(part) for part in re.split(r"[-_.]", text)), default=0)
    mixed = re.search(r"[A-Z]", text) and re.search(r"[a-z]", text) and re.search(r"\d", text)
    return bool(mixed and (longest >= 24 or (_KEY_PREFIX.match(text) and len(text) >= 24)))


_OUTPUT_KINDS = {".html": "web", ".htm": "web", ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
                 ".webp": "image", ".svg": "image", ".mp4": "video", ".webm": "video", ".pdf": "file", ".stl": "file", ".glb": "file", ".gltf": "file", ".blend": "file"}
_EXT = "|".join(sorted({e.strip().lstrip(".") for e in _OUTPUT_KINDS}, key=len, reverse=True))
_QUOTED_PATH = re.compile(rf"`([^`\n]+?\.(?:{_EXT}))`", re.I)                  # entre crases aceita espaços
_BARE_PATH = re.compile(rf"(?<![\w/:.])((?:[A-Za-z]:[\\/]|~?/|\.{{1,2}}[\\/])?[\w\-.\\/À-ÿ]+?\.(?:{_EXT}))(?![\w/])", re.I)


def turn_outputs(text: str, workspace: Path, limit: int = 4) -> list[dict]:
    """Arquivos que existem e foram citados na resposta (página, imagem, vídeo…), para o botão Testar/Abrir."""
    found: list[Path] = []
    for match in [*_QUOTED_PATH.finditer(text or ""), *_BARE_PATH.finditer(text or "")]:
        raw = match.group(1).strip()
        if "://" in (text or "")[max(0, match.start() - 12):match.start() + 3] or raw.startswith("//"):
            continue   # URL, não arquivo
        path = Path(raw).expanduser()
        path = path if path.is_absolute() else Path(workspace) / path
        try:
            path = path.resolve()
            if path.is_file() and path not in found:
                found.append(path)
        except OSError:
            continue
    order = {"web": 0, "video": 1, "image": 2, "file": 3}
    items = [{"path": str(p), "kind": _OUTPUT_KINDS.get(p.suffix.lower(), "file")} for p in found]
    return sorted(items, key=lambda item: order[item["kind"]])[:limit]


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
            if request.get("tool") == "toolbox_install":   # permissão mostra nome, tamanho e origem
                request = {**request, "detail": toolbox.get_toolbox().approval_detail(
                    str((request.get("args") or {}).get("id", "")))}
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
                elif command == "compact":
                    self.events("status", {"text": "Compactando o histórico…"})
                    self.push({"type": "compact_done", **self.brain.compact_current_session()})
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
        self._engine_scan = threading.Event()
        # Progresso da caixa de ferramentas (instalação pela interface ou pelo agente) vai para a página.
        toolbox.get_toolbox().add_listener(lambda data: self.push({"type": "toolbox", **data}))

    def push(self, payload: dict) -> None:
        try:
            self._relay.emit(json.dumps(payload, ensure_ascii=False, default=str))
        except RuntimeError:
            pass

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
        elif profile.in_team and settings.get("team_model", "principal") == "auto":
            routed = self.brain.route_model(routing.specialty_for(profile))
            data["model_label"] = f"auto · {_short_model(routed)}" if routed else (settings.get("cheap_model") or "modelo principal")
        elif profile.in_team:
            provider, model = self.brain.current_model
            data["model_label"] = f"mesmo do principal · {_short_model(f'{provider}:{model}')}"
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
            "data_destination": self._data_destination(provider),
            "workspace": str(workspace),
            "workspace_name": workspace.name,
            "recent_workspaces": brain.recent_workspaces(),
            "projects_parent": str(brain.default_projects_parent()),
            "workspace_set": bool((brain.profile.workspace or "").strip() or (settings.get("default_workspace") or "").strip()),
            "providers": providers,
            "mcp": brain.mcp.status(),
            "skills": [{"name": s.name, "description": s.description, "origin": s.origin}
                       for s in sorted(brain.skills.skills.values(), key=lambda s: s.name)],
            "toolbox": toolbox.get_toolbox().list(),
            "conversations": brain.conversations.list(),
            "conversation_id": brain.conversation_id,
            "conversation_title": brain.conversation_title,
            "pinned_prompt": brain.pinned_prompt,
            "conversation_tokens": session.total_tokens if session else 0,
            "usage": brain.usage.today(),
            "grok": self.grok_status(),
            "local_models": brain.local_models(),
            "all_groups": ALL_GROUPS,
            "quick_prompts": QUICK_PROMPTS,
            "pygments_css": render.pygments_css(),
            "version": __version__,
            "install": self.install_info(),
            "voice_gpu": self.voice_gpu() if getattr(self, "_voice_gpu", None) else None,
        }

    @pyqtSlot(result=str)
    def voiceGpuStatus(self) -> str:
        return json.dumps(self.voice_gpu())

    def install_info(self) -> dict:
        if not hasattr(self, "_install"):
            mode = updater.install_mode()
            sha = updater.local_sha(mode=mode) or ""
            self._install = {"mode": mode, "sha": sha[:7], "repo": updater.REPO}
        return self._install

    def _data_destination(self, provider: str) -> str:
        from agent.core.local_policy import data_destination

        try:
            cfg = self.brain.settings.provider(provider)
        except KeyError:
            return "unknown"
        return data_destination(provider, cfg)

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
        """Conversa por voz: fala, o agente responde e lê a resposta (paleta de comandos)."""
        self.win.worker.commands.put(("voice", None))

    # ── Ditado (microfone → texto no campo) ──────────────────

    def stt_engine(self, with_key: bool = True) -> dict:
        """Onde transcrever: nuvem (Groq/OpenAI, se houver chave) ou este PC (Whisper leve)."""
        from agent.voice import dictation
        settings = self.brain.settings
        choice = settings.get("stt_engine") or "auto"
        if settings.get("execution_policy") == "local_only":
            choice = "local"
        if choice in ("auto", "cloud"):
            for name, model in dictation.CLOUD_MODELS.items():
                try:
                    cfg = settings.provider(name)
                    key = settings.api_key(cfg)
                except KeyError:
                    continue
                if key:
                    engine = {"kind": "cloud", "label": f"{cfg.get('label', name)} · nuvem",
                              "base_url": cfg.get("base_url", ""), "model": model}
                    return {**engine, "key": key} if with_key else engine
        size = settings.get("stt_model") or dictation.DEFAULT_LOCAL_MODEL
        return {"kind": "local", "size": size, "label": f"neste PC · Whisper {size}",
                "wanted_cloud": choice == "cloud"}

    def dictation(self):
        if getattr(self, "_dictation", None) is None:
            from agent.voice.dictation import Dictation
            self._dictation = Dictation(self.push, self.stt_engine)
        return self._dictation

    @pyqtSlot(result=str)
    def sttStatus(self) -> str:
        return json.dumps(self.stt_engine(with_key=False), ensure_ascii=False)

    @pyqtSlot(result=str)
    def dictationStart(self) -> str:
        error = self.dictation().start()
        return json.dumps({"error": error} if error else {}, ensure_ascii=False)

    def voice_gpu(self) -> dict:
        """Placa NVIDIA presente? Bibliotecas CUDA do Whisper instaladas? (calculado uma vez)"""
        if not hasattr(self, "_voice_gpu"):
            import importlib.util
            try:
                import ctranslate2
                cuda = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                cuda = False
            libs = bool(importlib.util.find_spec("nvidia")) and any(
                importlib.util.find_spec(f"nvidia.{name}") for name in ("cublas",))
            self._voice_gpu = {"cuda": cuda, "libs": libs, "installing": False}
        return self._voice_gpu

    @pyqtSlot()
    def installVoiceGpu(self) -> None:
        """Instala cuBLAS/cuDNN (pip, ~1 GB) para o Whisper rodar na placa NVIDIA."""
        info = self.voice_gpu()
        if info["installing"]:
            return
        info["installing"] = True

        def work():
            command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                       "nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"]
            self.push({"type": "voice_gpu", "state": "running"})
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=3600,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                ok = result.returncode == 0
                if ok:
                    from agent.voice import dictation
                    dictation.WHISPER._cpu_only, dictation.WHISPER._dlls = False, False
                    info["libs"] = True
                self.push({"type": "voice_gpu", "state": "done" if ok else "error",
                           "message": "" if ok else (result.stderr or result.stdout)[-600:]})
            except Exception as error:
                self.push({"type": "voice_gpu", "state": "error", "message": str(error)})
            finally:
                info["installing"] = False
        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot()
    def dictationStop(self) -> None:
        self.dictation().stop()

    @pyqtSlot()
    def dictationCancel(self) -> None:
        self.dictation().cancel()

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

    @pyqtSlot(str, result=str)
    def setPinnedPrompt(self, prompt: str) -> str:
        return json.dumps({"pinned_prompt": self.brain.set_pinned_prompt(prompt)}, ensure_ascii=False)

    @pyqtSlot(result=str)
    def compactConversation(self) -> str:
        """Botão Compactar: roda no worker (chama o modelo para resumir); o resultado chega como evento."""
        if self.win.busy:
            return json.dumps({"error": "Espere o agente terminar antes de compactar."}, ensure_ascii=False)
        self.win.worker.commands.put(("compact", None))
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
        payload = {"id": data["id"], "title": data.get("title", ""), "pinned_prompt": data.get("pinned_prompt", ""),
                   "blocks": data["blocks"], "model_label": f"{data.get('provider', '')}:{data.get('model', '')}"}
        return json.dumps(payload, ensure_ascii=False, default=str)

    @pyqtSlot(str, result=str)
    def deleteConversation(self, conversation_id: str) -> str:
        ok = self.brain.conversations.delete(conversation_id)
        if ok and conversation_id == self.brain.conversation_id:
            self.brain.new_conversation()
        return json.dumps(ok)

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

    def _known_keys(self, provider: Optional[str] = None) -> tuple[str, ...]:
        settings = self.brain.settings
        names = [provider] if provider else list(settings.providers())
        keys = []
        for name in names:
            try:
                keys.append(settings.api_key(settings.provider(name)))
            except Exception:
                continue
        return tuple(k for k in keys if k)

    def scrub_secret_models(self) -> bool:
        """Conserta quem já salvou uma chave de API como nome de modelo. A chave continua só no .env."""
        settings, fixed = self.brain.settings, False
        stored = dict(settings.get("providers") or {})
        for name, cfg in stored.items():
            models = (cfg or {}).get("models") or []
            clean = [m for m in models if not looks_like_secret(m, self._known_keys(name))]
            if clean != models:
                stored[name] = {**cfg, "models": clean}
                fixed = True
        if fixed:
            settings.set("providers", stored, save=False)
        provider, model = settings.get("provider") or "", settings.get("model") or ""
        if provider and looks_like_secret(model, self._known_keys(provider)):
            options = (stored.get(provider) or {}).get("models") or []
            settings.set("model", options[0] if options else "", save=False)
            fixed = True
        if fixed:
            settings.save()
            logger.warning("Chave de API encontrada no lugar do nome do modelo: removida das configurações.")
        return fixed

    @pyqtSlot(str, str, result=str)
    def selectModel(self, provider: str, model: str) -> str:
        if looks_like_secret(model, self._known_keys(provider)):
            return json.dumps({"error": "Isso é uma chave de API, não o nome do modelo. A chave vai em "
                                        "Configurações › Chaves de API; aqui escolha um modelo da lista."},
                              ensure_ascii=False)
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
        known = tuple(k for k in (data.get("key") or "",) if k.strip())
        if looks_like_secret(model, known):
            return json.dumps({"error": "O campo Modelo está com a chave de API. Coloque a chave só no campo Chave e, "
                                        "no Modelo, o nome (use Verificar modelos para ver a lista)."},
                              ensure_ascii=False)
        models = [m for m in models if not looks_like_secret(m, known)]
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
        if looks_like_secret(data.get("model") or "", self._known_keys()):
            return json.dumps({"error": "O campo Modelo está com uma chave de API. Coloque o nome do modelo."},
                              ensure_ascii=False)
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
            if model and not looks_like_secret(model, (data.get("key") or "",) + self._known_keys(provider)):
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
            if models and provider != "ollama":
                clean = [m for m in models if not looks_like_secret(m, self._known_keys(provider))]
                self.brain.settings.remember_models(provider, clean, only_if_empty=True)
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

    @pyqtSlot()
    def discoverLocalEngines(self) -> None:
        from agent.core.local_engines import detect_local_engines

        self._engine_scan.set()
        cancel = self._engine_scan = threading.Event()
        providers = self.brain.settings.providers()

        def work():
            rows = detect_local_engines(providers, cancel=cancel)
            if not cancel.is_set():
                self.push({"type": "local_engines", "engines": rows})
        threading.Thread(target=work, name="engine-discovery", daemon=True).start()

    @pyqtSlot()
    def cancelEngineDiscovery(self) -> None:
        self._engine_scan.set()

    def _pull_base(self) -> str:
        return self.brain.settings.provider("ollama").get("base_url", "http://127.0.0.1:11434").rstrip("/")

    def _emit_pull(self, event: dict) -> None:
        if event.get("done") and event.get("state") == "done":
            self.brain._local_models = None
        self.push({"type": "pull", **event})

    @pyqtSlot(str)
    def pullModel(self, name: str) -> None:
        from agent.core.model_manager import get_manager

        try:
            get_manager().start_pull(self._pull_base(), name, self._emit_pull)
        except ValueError as error:
            self.push({"type": "pull", "model": name, "done": True, "error": str(error), "state": "error"})

    @pyqtSlot(str)
    def cancelModelPull(self, name: str) -> None:
        from agent.core.model_manager import get_manager

        get_manager().cancel(name)

    @pyqtSlot(result=str)
    def listMemories(self) -> str:
        project = ""
        try:
            project = str(self.brain.effective_workspace())
        except Exception:
            project = ""
        records = self.brain.memory.list_facts(project)
        public = [{"id": item.get("id"), "fact": item.get("fact"), "scope": item.get("scope"),
                   "origin": item.get("origin"), "project": item.get("project") or ""} for item in records]
        return json.dumps(public, ensure_ascii=False)

    @pyqtSlot(str, str)
    def saveMemory(self, fact_id: str, text: str) -> None:
        if fact_id:
            self.brain.memory.update_fact(fact_id, text)
        elif text.strip():
            self.brain.memory.remember_fact(text.strip(), scope="global", origin="user")
        self.push({"type": "memories"})

    @pyqtSlot(str)
    def deleteMemory(self, fact_id: str) -> None:
        self.brain.memory.delete_fact(fact_id)
        self.push({"type": "memories"})

    @pyqtSlot(result=str)
    def modelJobs(self) -> str:
        from agent.core.model_manager import get_manager

        return json.dumps(get_manager().jobs(), ensure_ascii=False)

    @pyqtSlot(str, str)
    def ollamaAction(self, name: str, action: str) -> None:
        from agent.core.model_manager import ollama_action

        base = self._pull_base()

        def work():
            try:
                message = ollama_action(base, name, action)
                self.brain._local_models = None
                self.push({"type": "ollama_action", "model": name, "action": action, "message": message})
            except Exception as error:
                self.push({"type": "ollama_action", "model": name, "action": action, "error": str(error)})
        threading.Thread(target=work, name="ollama-action", daemon=True).start()

    @pyqtSlot()
    def recommendLocalModels(self) -> None:
        from agent.actions.gpu_monitor import get_hardware_info
        from agent.core.local_catalog import model_recommendations

        def work():
            hardware = get_hardware_info(PROJECT_ROOT)
            rows = model_recommendations(hardware)
            public = [{
                "id": row.get("id"), "name": row.get("name"), "fit": row.get("fit"),
                "execution_mode": row.get("execution_mode"), "rationale": row.get("rationale"),
                "download_gb": row.get("download_gb"), "estimated_memory_gb": row.get("estimated_memory_gb"),
                "license": row.get("license"), "capabilities": row.get("capabilities") or [],
                "pt_br_validation": row.get("pt_br_validation"),
            } for row in rows]
            self.push({"type": "local_catalog", "hardware": {
                "ram_total_gb": hardware.get("ram_total_gb"),
                "ram_available_gb": hardware.get("ram_available_gb"),
                "disk_free_gb": hardware.get("disk_free_gb"),
                "gpus": [{"name": gpu.get("name"), "free_gb": gpu.get("free_gb"),
                          "total_gb": gpu.get("total_gb")} for gpu in hardware.get("gpus") or []],
            }, "models": public})
        threading.Thread(target=work, name="local-catalog", daemon=True).start()

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

    # ── Caixa de ferramentas (programas opcionais) ───────────

    @pyqtSlot(result=str)
    def toolboxList(self) -> str:
        return json.dumps(toolbox.get_toolbox().list(), ensure_ascii=False)

    @pyqtSlot(str)
    def toolboxInstall(self, tool_id: str) -> None:
        """Clique do usuário em Instalar: o clique é a permissão. Baixa só a URL do catálogo."""
        box = toolbox.get_toolbox()

        def work():
            try:
                box.install(tool_id)
                self.push({"type": "toolbox", "id": tool_id, "state": "tested", "test": box.run_test(tool_id)})
            except Exception as error:   # o ouvinte já avisou a página do erro de instalação
                logger.warning("Caixa de ferramentas: %s falhou: %s", tool_id, error)
                if box.find_executable(tool_id):
                    self.push({"type": "toolbox", "id": tool_id, "state": "error",
                               "error": f"Instalado, mas o teste falhou: {error}"})
        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot(str)
    def toolboxRemove(self, tool_id: str) -> None:
        """Apagar o Blender são milhares de arquivos: fora da thread da interface."""
        def work():
            try:
                toolbox.get_toolbox().remove(tool_id)   # o ouvinte avisa a página ("removed")
            except Exception as error:
                self.push({"type": "toolbox", "id": tool_id, "state": "error", "error": str(error)})
        threading.Thread(target=work, daemon=True).start()

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
        if not os.path.exists(path):
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:   # Linux: abre a pasta que contém o arquivo no gerenciador padrão
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(path))))

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

    # ── Atualizações (GitHub) ────────────────────────────────

    def check_updates(self, manual: bool = False) -> None:
        def work():
            try:
                info = updater.check_cached(force=manual)
            except Exception as error:
                logger.info("Verificação de atualização falhou: %s", error)
                if manual:
                    self.push({"type": "update", "error": f"Não consegui falar com o GitHub: {error}"})
                return
            if manual or (info.get("available") and info.get("significant")):
                self.push({"type": "update", "info": info, "manual": manual})
        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot()
    def checkUpdate(self) -> None:
        self.check_updates(manual=True)

    @pyqtSlot(str, bool, result=str)
    def applyUpdate(self, sha: str, keep_local: bool = False) -> str:
        if self.win.busy:
            return json.dumps({"error": "Espere o agente terminar a tarefa atual antes de atualizar."}, ensure_ascii=False)
        try:
            updater.start_detached(sha, keep_local=keep_local)
        except Exception as error:
            return json.dumps({"error": f"Não consegui iniciar o atualizador: {error}"}, ensure_ascii=False)
        QTimer.singleShot(400, self.win.close)   # o atualizador espera a janela fechar e reabre sozinho
        return "{}"

    def report_last_update(self) -> None:
        """Depois de reabrir: conta como foi a atualização e apaga o aviso."""
        result_file = updater.updates_dir() / "result.json"
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
            result_file.unlink()
        except (OSError, ValueError):
            return
        self.push({"type": "updated", "result": result})


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
        QTimer.singleShot(2500, self.api.report_last_update)
        if self.api.scrub_secret_models():
            QTimer.singleShot(6000, lambda: self.api.push({   # depois que a página conectou
                "type": "toast", "kind": "warn", "title": "Modelo corrigido", "ms": 15000,
                "text": "Havia uma chave de API no lugar do nome do modelo. Ela foi tirada dali (continua no .env). "
                        "Escolha o modelo em Configurações › Modelos."}))
        if brain.settings.get("update_check", True):
            QTimer.singleShot(8000, self.api.check_updates)

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
            self.api.push({"type": "reasoning", "text": self._reasoning[-20000:]})

    def _end_reasoning(self) -> None:
        """O modelo parou de pensar (vai escrever ou usar ferramenta): fecha o bloco atual de raciocínio."""
        if self._reasoning:
            if self._reasoning_dirty:
                self._flush_stream()
            self.api.push({"type": "reasoning_end"})
            self._reasoning = ""

    def on_agent_event(self, kind: str, data: dict) -> None:
        agent = data.get("agent", "principal")
        push = self.api.push
        if kind == "turn_start":
            self._seg_id, self._seg_text, self._reasoning, self._streamed_any = None, "", "", False
            push({"type": "turn_start", "model": _short_model(data.get("model", ""))})
        elif kind == "text":
            if agent == "principal":
                self._end_reasoning()
            if self._seg_id is None:
                self._seg_id = uuid.uuid4().hex[:8]
                self._seg_text = ""
            self._seg_text += data["text"]
            self._seg_dirty = self._streamed_any = True
        elif kind == "reasoning":
            if agent != "principal":
                return   # raciocínio dos subagentes não entra no chat principal
            self._reasoning += data["text"]
            self._reasoning_dirty = True
        elif kind == "tool_start":
            if agent == "principal":
                self._end_reasoning()
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
            self._end_reasoning()
            text = data.get("text") or ""
            if self._seg_id is not None:
                self._close_segment()
            elif not self._streamed_any and text and not text.startswith("⚠️"):
                push({"type": "seg", "id": uuid.uuid4().hex[:8], "html": render.markdown_html(text), "streaming": False})
            try:
                outputs = turn_outputs(text, self.brain.effective_workspace())
            except Exception:   # o cartão "Testar" nunca atrapalha o fim do turno
                outputs = []
            push({"type": "turn_end", "conversation_id": self.brain.conversation_id,
                  "title": self.brain.conversation_title, "plan": bool(data.get("plan")), "outputs": outputs})
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
        self.api.cancelEngineDiscovery()
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
