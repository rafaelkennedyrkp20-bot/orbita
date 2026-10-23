"""Ponte local 3D: Unreal Remote Control oficial e Blender instalado pela pessoa.

Consulta de estado não abre rede nem executa programas. O diagnóstico HTTP valida
o protocolo; não afirma que uma cena foi criada ou renderizada. Chamadas mutantes
nunca são repetidas automaticamente (um timeout não prova que nada aconteceu).
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from agent.core.config import DATA_DIR, RESOURCE_ROOT
from agent.core.toolbox import get_toolbox

MAX_RESPONSE = 1_000_000
MAX_OUTPUT = 24000
DEFAULTS = {"unreal": {"enabled": False, "url": "http://127.0.0.1:30010"}, "blender": {"path": ""},
            "unity": {"enabled": False, "url": "http://127.0.0.1:30012", "project_path": ""}}
UNITY_BRIDGE = RESOURCE_ROOT / "agent" / "integrations" / "unity" / "OrbitaBridge.cs"
UNITY_PROTOCOL = "OrbitaUnity/1"
UNITY_PORT = 30012


def validate_unreal_url(value: str) -> str:
    """Endereço HTTP literal local; localhost é normalizado sem resolver DNS."""
    if not isinstance(value, str) or any(c in value for c in "\r\n\t"):
        raise ValueError("Informe um endereço HTTP local válido.")
    parts = urlsplit(value.strip())
    if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parts.username is not None or parts.password is not None
            or parts.path not in {"", "/"} or parts.query or parts.fragment):
        raise ValueError("Unreal: use http://127.0.0.1:30010 (somente loopback, sem caminho ou credenciais).")
    port = parts.port
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Informe a porta HTTP do Remote Control (padrão 30010).")
    host = "[::1]" if parts.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}"


def _text(value, name: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise ValueError(f"{name} deve ser um texto não vazio de até {limit} caracteres.")
    return value.strip()


class Studio3D:
    def __init__(self, path: Path | None = None, box=None):
        self.path = Path(path) if path is not None else DATA_DIR / "studio3d.json"
        self.box = box
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._config = copy.deepcopy(DEFAULTS)
        self._probe = {}
        self._config_error = ""
        if self.path.exists():
            try:
                self._config = self._validate(json.loads(self.path.read_text(encoding="utf-8")), check_path=False)
            except (ValueError, OSError, TypeError) as error:
                self._config_error = f"Configuração 3D inválida: {error}"

    @staticmethod
    def _validate(data: dict, *, check_path: bool = True) -> dict:
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise ValueError("Configuração 3D deve conter somente unreal, unity e blender.")
        out = copy.deepcopy(DEFAULTS)
        for key in out:
            section = data.get(key, {})
            if not isinstance(section, dict) or set(section) - set(out[key]):
                raise ValueError(f"Campos inválidos na configuração de {key}.")
            out[key].update(section)
        for engine in ("unreal", "unity"):
            if not isinstance(out[engine]["enabled"], bool):
                raise ValueError(f"{engine}.enabled deve ser booleano.")
            out[engine]["url"] = validate_unreal_url(out[engine]["url"])
        if out["unity"]["url"] != f"http://127.0.0.1:{UNITY_PORT}":
            raise ValueError(f"A ponte Unity nativa usa somente http://127.0.0.1:{UNITY_PORT}.")
        project = out["unity"]["project_path"]
        if not isinstance(project, str) or (project and not Path(project).expanduser().is_absolute()):
            raise ValueError("O projeto Unity deve ter um caminho absoluto.")
        if project:
            out["unity"]["project_path"] = str(Path(project).expanduser().resolve())
        configured = out["blender"]["path"]
        if not isinstance(configured, str):
            raise ValueError("O caminho do Blender deve ser texto.")
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute() or (check_path and (not path.is_file() or
                                                         (os.name != "nt" and not os.access(path, os.X_OK)))):
                raise ValueError("Selecione um executável existente do Blender com caminho absoluto.")
            if os.name == "nt" and path.suffix.lower() != ".exe":
                raise ValueError("No Windows, selecione o blender.exe.")
            out["blender"]["path"] = str(path.resolve())
        return out

    def configure(self, changes: dict, *, _owner=None) -> dict:
        from agent.core.mcp_hub import SERVER_LEASES

        if not isinstance(changes, dict):
            raise ValueError("Configuração deve ser um objeto JSON.")
        owner = _owner if _owner is not None else object()
        try:
            for engine in ("unreal", "unity"):
                if engine in changes and not SERVER_LEASES.acquire(f"studio3d-{engine}", owner, timeout=0):
                    raise ValueError(f"A conexão {engine} está reservada por um agente. Aguarde o fim do turno antes de reconfigurar.")
            return self._configure(changes)
        finally:
            if _owner is None:
                SERVER_LEASES.release_all(owner)

    def _configure(self, changes: dict) -> dict:
        with self._lock:
            if not isinstance(changes, dict):
                raise ValueError("Configuração deve ser um objeto JSON.")
            merged = copy.deepcopy(self._config)
            for key, value in changes.items():
                if key not in merged or not isinstance(value, dict):
                    raise ValueError(f"Configuração 3D inválida: {key}.")
                merged[key].update(value)
            validated = self._validate(merged, check_path="path" in changes.get("blender", {}))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            try:
                temporary.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self._config = validated
            self._config_error = ""
            self._probe = {}
        return self.status()

    def _apps(self) -> list[dict]:
        return [app for app in (self.box or get_toolbox()).list() if app["id"] in {"blender", "godot", "openscad"}]

    def _blender_executable(self) -> Path | None:
        with self._lock:
            explicit = self._config["blender"]["path"]
        if explicit:
            return Path(explicit) if Path(explicit).is_file() else None
        for item in self._apps():
            if item["id"] == "blender":
                value = item.get("exe") or item.get("system_exe")
                return Path(value) if value and Path(value).is_file() else None
        return None

    def status(self) -> dict:
        with self._lock:
            config = copy.deepcopy(self._config)
            probe = copy.deepcopy(self._probe)
            error = self._config_error
        apps = self._apps()
        executable = self._blender_executable()
        blender_path = str(executable) if executable else config["blender"]["path"]
        return {"unreal": {**config["unreal"],
                           "state": "not_checked" if config["unreal"]["enabled"] else "disabled",
                           "message": "Verifique a API no editor aberto." if config["unreal"]["enabled"] else "Conexão desligada.",
                           "checked_at": "", **probe.get("unreal", {})},
                "unity": {**config["unity"],
                          "state": "not_checked" if config["unity"]["enabled"] else "disabled",
                          "message": "Verifique a ponte no projeto Unity aberto." if config["unity"]["enabled"] else "Conexão desligada.",
                          "checked_at": "", **probe.get("unity", {})},
                "blender": {"path": blender_path, "configured_path": config["blender"]["path"],
                            "state": "available" if executable else "missing",
                            "message": "Executável encontrado; render ainda não validado." if executable else
                                       "Instale pela caixa de ferramentas ou selecione o executável."},
                "apps": apps, "config_error": error}

    def _request(self, method: str, route: str, body=None, *, cancel=None, timeout: float = 10, engine="unreal") -> dict:
        import httpx

        if cancel is not None and cancel.is_set():
            raise InterruptedError("Operação 3D cancelada.")
        with self._lock:
            config = dict(self._config[engine])
        if not config["enabled"]:
            raise ValueError(f"A conexão {engine} está desligada. Ative em Conexões › Estúdio 3D.")
        url = validate_unreal_url(config["url"]) + route
        encoded = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
        if encoded and len(encoded) > MAX_RESPONSE:
            raise ValueError("O pedido 3D passa de 1 MB.")
        started = time.monotonic()
        headers = {"Content-Type": "application/json"}
        if engine == "unity":
            root = self._unity_project(config["project_path"])
            token_path = self._unity_target(root, "Library/Orbita/bridge-token.txt")
            if not token_path.is_file():
                raise ValueError("A ponte Unity não está instalada neste projeto. Use unity_install_bridge.")
            token = token_path.read_text(encoding="utf-8").strip()
            if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
                raise ValueError("Token local da ponte Unity inválido; confira a instalação no projeto.")
            headers["X-Orbita-Token"] = token
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                with client.stream(method, url, content=encoded, headers=headers) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise RuntimeError(f"{engine} respondeu HTTP {response.status_code}; a chamada não será repetida automaticamente.")
                    content = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if cancel is not None and cancel.is_set():
                            raise InterruptedError("Operação cancelada; uma ação já enviada ao Unreal pode ter sido executada.")
                        if time.monotonic() - started > timeout:
                            raise TimeoutError("Prazo da resposta Unreal excedido; não repita uma ação sem conferir a cena.")
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE:
                            raise ValueError("Resposta Unreal passa de 1 MB.")
            result = json.loads(content) if content else {}
            if not isinstance(result, dict):
                raise ValueError("Resposta Unreal deve ser um objeto JSON com HttpRoutes ou resultado da operação.")
            return result
        except httpx.HTTPError as error:
            how = "Remote Control API, WebControl.StartServer e a porta" if engine == "unreal" else "o projeto aberto, a ponte e a porta 30012"
            raise RuntimeError(f"Não foi possível consultar {engine}. Confira {how}. "
                               f"Uma ação já enviada pode ter sido executada. ({type(error).__name__})") from error

    def probe(self, cancel=None) -> dict:
        self._probe_unreal(cancel)
        self._probe_unity(cancel)
        return self.status()

    def _probe_unreal(self, cancel=None) -> None:
        with self._lock:
            snapshot = copy.deepcopy(self._config["unreal"])
        checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not snapshot["enabled"]:
            return
        try:
            info = self._request("GET", "/remote/info", cancel=cancel, timeout=3)
            routes = info.get("HttpRoutes")
            if not isinstance(routes, list) or not any(isinstance(route, dict) and route.get("Path") == "/remote/object/call"
                                                      and str(route.get("Verb", "")).lower() == "put" for route in routes):
                raise ValueError("A resposta não contém HttpRoutes com PUT /remote/object/call; não é uma API Unreal compatível.")
            result = {"state": "available", "message": "API Remote Control disponível; cena e render ainda não validados.",
                      "checked_at": checked}
        except (OSError, ValueError, RuntimeError) as error:
            result = {"state": "error", "message": str(error), "checked_at": checked}
        with self._lock:
            if snapshot == self._config["unreal"]:
                self._probe["unreal"] = result

    def _probe_unity(self, cancel=None) -> None:
        with self._lock:
            snapshot = copy.deepcopy(self._config["unity"])
        if not snapshot["enabled"]:
            return
        checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            info = self._request("GET", "/orbita/info", engine="unity", cancel=cancel, timeout=3)
            if info.get("protocol") != UNITY_PROTOCOL:
                raise ValueError("A resposta não corresponde à ponte OrbitaUnity/1.")
            result = {"state": "available", "message": "Ponte Unity disponível; cena e render ainda não validados.", "checked_at": checked}
        except (OSError, ValueError, RuntimeError) as error:
            result = {"state": "error", "message": str(error), "checked_at": checked}
        with self._lock:
            if snapshot == self._config["unity"]:
                self._probe["unity"] = result

    @staticmethod
    def _unity_project(project_path: str) -> Path:
        if not isinstance(project_path, str) or not project_path or not Path(project_path).expanduser().is_absolute():
            raise ValueError("Informe o caminho absoluto de um projeto Unity existente.")
        root = Path(project_path).expanduser().resolve()
        if not (root / "Assets").is_dir() or not (root / "ProjectSettings" / "ProjectVersion.txt").is_file():
            raise ValueError("Projeto Unity inválido: faltam Assets e ProjectSettings/ProjectVersion.txt.")
        return root

    @staticmethod
    def _unity_target(root: Path, relative: str) -> Path:
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("A instalação da ponte Unity não pode seguir links para fora do projeto.")
        return target

    def unity_install_bridge(self, project_path: str) -> dict:
        from agent.core.mcp_hub import SERVER_LEASES

        owner = object()
        if not SERVER_LEASES.acquire("studio3d-unity", owner, timeout=0):
            raise ValueError("Unity reservado por outro agente; a ponte não foi alterada.")
        try:
            return self._install_unity_bridge(project_path, owner)
        finally:
            SERVER_LEASES.release_all(owner)

    def _install_unity_bridge(self, project_path: str, owner) -> dict:
        root = self._unity_project(project_path)
        target = self._unity_target(root, "Assets/Editor/OrbitaBridge.cs")
        token_path = self._unity_target(root, "Library/Orbita/bridge-token.txt")
        source = UNITY_BRIDGE.read_text(encoding="utf-8")
        if target.exists() and target.read_text(encoding="utf-8-sig") != source:
            raise ValueError("OrbitaBridge.cs já existe com conteúdo diferente; preserve ou renomeie antes de instalar.")
        target.parent.mkdir(parents=True, exist_ok=True)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        if not token_path.exists():
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(secrets.token_hex(32))
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Token local existente inválido; não foi substituído.")
        if not target.exists():
            with target.open("x", encoding="utf-8", newline="\n") as output:
                output.write(source)
        self.configure({"unity": {"enabled": True, "project_path": str(root)}}, _owner=owner)
        return {"project_path": str(root), "bridge_path": str(target), "state": "installed",
                "message": "Ponte instalada. Abra o projeto no Unity e aguarde a compilação; depois consulte studio3d_status refresh=true. "
                           "O serviço usa 127.0.0.1:30012; nenhum editor foi aberto ou pacote baixado."}

    def unity_scene(self, cancel=None) -> dict:
        with self._operation_lock:
            return self._request("GET", "/orbita/scene", engine="unity", cancel=cancel)

    def unity_create_primitive(self, primitive: str, name: str, position=None, cancel=None) -> dict:
        if primitive not in {"cube", "sphere", "plane", "capsule", "cylinder", "quad"}:
            raise ValueError("Primitiva Unity inválida.")
        name = _text(name, "name", 120)
        position = {"x": 0, "y": 0, "z": 0} if position is None else position
        if not isinstance(position, dict) or set(position) != {"x", "y", "z"} or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not -1_000_000 <= v <= 1_000_000 for v in position.values()):
            raise ValueError("position deve conter x, y, z numéricos finitos entre -1000000 e 1000000.")
        with self._operation_lock:
            return self._request("POST", "/orbita/primitive", {"primitive": primitive, "name": name, "position": position},
                                 engine="unity", cancel=cancel)

    def unreal_describe(self, object_path: str, cancel=None) -> dict:
        path = _text(object_path, "object_path")
        with self._operation_lock:
            return self._request("PUT", "/remote/object/describe", {"objectPath": path}, cancel=cancel)

    def unreal_call(self, object_path: str, function_name: str, parameters=None, cancel=None) -> dict:
        path = _text(object_path, "object_path")
        function = _text(function_name, "function_name", 256)
        parameters = {} if parameters is None else parameters
        if not isinstance(parameters, dict):
            raise ValueError("parameters deve ser um objeto JSON.")
        with self._operation_lock:
            return self._request("PUT", "/remote/object/call", {"objectPath": path, "functionName": function,
                                 "parameters": parameters, "generateTransaction": True}, cancel=cancel)

    def blender_run_script(self, script_path: str, workspace: Path, timeout: float = 120, cancel=None) -> dict:
        workspace = Path(workspace).resolve()
        if not workspace.is_dir():
            raise ValueError("A pasta do projeto não existe.")
        script = Path(_text(script_path, "script_path")).expanduser()
        script = (script if script.is_absolute() else workspace / script).resolve()
        if not script.is_relative_to(workspace) or not script.is_file() or script.suffix.lower() != ".py":
            raise ValueError("Escolha um script .py existente dentro da pasta do projeto.")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
            raise ValueError("timeout deve estar entre 1 e 600 segundos.")
        executable = self._blender_executable()
        if not executable:
            raise ValueError("Blender não encontrado. Instale na caixa de ferramentas ou configure o executável.")
        command = [str(executable), "--background", "--factory-startup", "--disable-autoexec",
                   "--python-exit-code", "1", "--python", str(script)]
        return self._run_process(command, workspace, timeout, cancel)

    @staticmethod
    def _run_process(command: list[str], cwd: Path, timeout: float, cancel) -> dict:
        from agent.actions.builtin_tools import _kill_tree

        if cancel is not None and cancel.is_set():
            raise InterruptedError("Execução de criação cancelada antes de iniciar.")
        chunks = deque(maxlen=32)
        output_lock = threading.Lock()
        started = time.monotonic()
        proc = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                start_new_session=os.name != "nt")

        def drain():
            try:
                while True:
                    chunk = proc.stdout.read(4096)
                    if not chunk:
                        break
                    with output_lock:
                        chunks.append(chunk)
            finally:
                proc.stdout.close()

        reader = threading.Thread(target=drain, daemon=True, name="orbita-blender-output")
        reader.start()
        timed_out = cancelled = False
        try:
            while proc.poll() is None:
                cancelled = cancel is not None and cancel.is_set()
                timed_out = time.monotonic() - started >= timeout
                if cancelled or timed_out:
                    _kill_tree(proc)  # somente a árvore criada por esta chamada
                    break
                time.sleep(0.05)
            proc.wait(timeout=5)
        finally:
            if proc.poll() is None:
                _kill_tree(proc)
                proc.wait(timeout=5)
            reader.join(timeout=2)
        with output_lock:
            output = b"".join(chunks).decode("utf-8", "replace")[-MAX_OUTPUT:]
        return {"returncode": proc.returncode, "output": output, "timed_out": timed_out, "cancelled": cancelled,
                "elapsed_seconds": round(time.monotonic() - started, 3)}


_default = None
_default_lock = threading.Lock()


def get_studio3d() -> Studio3D:
    global _default
    with _default_lock:
        if _default is None:
            _default = Studio3D()
        return _default
