"""Texto para imagem em ComfyUI existente, somente com nós padrão.

Protocolo: https://docs.comfy.org/development/comfyui-server/comms_routes
Fila individual: POST /queue com delete=[prompt_id]. Nunca usa /interrupt,
pois essa rota afeta o trabalho em execução de outros clientes. Cancelar a
espera pode deixar um job já iniciado rodando; ComfyCancelled informa isso.
"""

from contextlib import nullcontext
import json
import math
from pathlib import PurePosixPath
import re
import threading
import time
from urllib.parse import urlsplit
import uuid

import httpx


_NODES = ("CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage",
          "KSampler", "VAEDecode", "SaveImage")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ComfyError(RuntimeError):
    """Falha com diagnóstico local e sem refletir payloads do servidor."""

    def __init__(self, message, *, prompt_id=None, may_still_run=False):
        super().__init__(message)
        self.prompt_id = prompt_id
        self.may_still_run = may_still_run


class ComfyCancelled(ComfyError):
    """Espera cancelada; execução remota pode ter começado antes do cancelamento."""


class ComfyClient:
    def __init__(self, base_url="http://127.0.0.1:8188", *, transport=None,
                 total_timeout=300, poll_interval=0.25, max_image_bytes=32 * 1024**2):
        try:
            parsed = urlsplit(base_url)
            valid = (parsed.scheme in {"http", "https"} and
                     parsed.hostname in {"localhost", "127.0.0.1", "::1"} and
                     parsed.username is None and parsed.password is None and
                     not parsed.query and not parsed.fragment and parsed.path in {"", "/"})
            _ = parsed.port
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ComfyError("Informe uma URL HTTP local do ComfyUI, sem credenciais ou parâmetros.")
        if isinstance(total_timeout, bool) or not isinstance(total_timeout, (int, float)) or not math.isfinite(total_timeout) or not 0 < total_timeout <= 1800:
            raise ComfyError("Prazo total deve ficar entre 0 e 1800 segundos.")
        if not isinstance(poll_interval, (int, float)) or not math.isfinite(poll_interval) or not 0 < poll_interval <= 5:
            raise ComfyError("Intervalo de consulta inválido.")
        if isinstance(max_image_bytes, bool) or not isinstance(max_image_bytes, int) or not 0 < max_image_bytes <= 64 * 1024**2:
            raise ComfyError("Limite da imagem inválido (máximo 64 MiB).")
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.total_timeout = total_timeout
        self.poll_interval = poll_interval
        self.max_image_bytes = max_image_bytes

    def _client(self):
        return httpx.Client(base_url=self.base_url, transport=self.transport,
                            trust_env=False, follow_redirects=False,
                            headers={"Accept-Encoding": "identity"})

    @staticmethod
    def _check(deadline, cancel=None):
        if cancel is not None and cancel.is_set():
            raise ComfyCancelled("Geração cancelada.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ComfyError("ComfyUI excedeu o prazo total de espera.")
        return remaining

    def _request(self, client, method, path, deadline, *, payload=None,
                 cancel=None, max_bytes=2 * 1024**2, binary=False):
        remaining = self._check(deadline, cancel)
        try:
            with client.stream(method, path, json=payload,
                               timeout=min(5, remaining)) as response:
                if not 200 <= response.status_code < 300:
                    raise ComfyError(f"ComfyUI respondeu HTTP {response.status_code}.")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ComfyError("Resposta comprimida não suportada pelo limite de leitura.")
                parts, size = [], 0
                for part in response.iter_bytes():
                    self._check(deadline, cancel)
                    size += len(part)
                    if size > max_bytes:
                        raise ComfyError("Resposta do ComfyUI excede o limite de tamanho.")
                    parts.append(part)
                self._check(deadline, cancel)
                data = b"".join(parts)
        except httpx.HTTPError:
            raise ComfyError("Não foi possível comunicar com o ComfyUI local.") from None
        if binary:
            return data
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError):
            raise ComfyError("Resposta JSON inválida do ComfyUI.") from None
        if not isinstance(value, dict):
            raise ComfyError("Resposta incompatível do ComfyUI.")
        return value

    def _health(self, client, deadline, cancel=None):
        stats = self._request(client, "GET", "/system_stats", deadline, cancel=cancel)
        if not isinstance(stats.get("system"), dict) or not isinstance(stats.get("devices"), list):
            raise ComfyError("Resposta incompatível de /system_stats.")
        missing, checkpoints = [], []
        for node in _NODES:
            data = self._request(client, "GET", f"/object_info/{node}", deadline, cancel=cancel)
            if not isinstance(data.get(node), dict):
                missing.append(node)
            elif node == "CheckpointLoaderSimple":
                try:
                    checkpoints = data[node]["input"]["required"]["ckpt_name"][0]
                except (KeyError, IndexError, TypeError):
                    raise ComfyError("Resposta incompatível do carregador de checkpoints.") from None
                if not isinstance(checkpoints, list) or any(not isinstance(name, str) for name in checkpoints):
                    raise ComfyError("Lista de checkpoints incompatível.")
        status = "incompatible" if missing else "ready" if checkpoints else "no_models"
        return {"status": status, "checkpoints": checkpoints, "missing_nodes": missing,
                "devices": stats["devices"], "system": stats["system"]}

    def health(self):
        """Diagnóstico sem instalar, iniciar serviço ou baixar modelos."""
        try:
            with self._client() as client:
                return self._health(client, time.monotonic() + min(15, self.total_timeout))
        except ComfyError as error:
            return {"status": "unreachable", "checkpoints": [], "missing_nodes": [],
                    "detail": str(error)}

    @staticmethod
    def _workflow(prompt, checkpoint, negative_prompt, seed, width, height, steps, prefix):
        # Grafo próprio mínimo; nenhum custom node ou caminho escolhido pelo modelo.
        return {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["4", 1]}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "3": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "positive": ["6", 0],
                  "negative": ["7", 0], "latent_image": ["5", 0], "seed": seed, "steps": steps,
                  "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
        }

    def _remove_owned(self, client, prompt_id):
        """Remove somente ID próprio; falha/estado desconhecido assume job vivo."""
        try:
            deadline = time.monotonic() + 3
            self._request(client, "POST", "/queue", deadline,
                          payload={"delete": [prompt_id]}, binary=True)
            queue = self._request(client, "GET", "/queue", deadline)
            if not all(isinstance(queue.get(key), list) for key in ("queue_running", "queue_pending")):
                return True
            return any(isinstance(row, list) and len(row) > 1 and row[1] == prompt_id
                       for key in ("queue_running", "queue_pending") for row in queue[key])
        except ComfyError:
            return True

    @staticmethod
    def _image_path(image, prefix):
        if not isinstance(image, dict):
            raise ComfyError("Referência de arquivo inválida.")
        filename, folder = image.get("filename"), image.get("subfolder", "")
        if (not isinstance(filename, str) or not isinstance(folder, str) or
                len(filename) > 255 or len(folder) > 512 or
                any(char in filename + folder for char in ("\\", ":", "\x00")) or
                PurePosixPath(filename).name != filename or
                PurePosixPath(folder).is_absolute() or ".." in PurePosixPath(folder).parts or
                not filename.startswith(prefix + "_") or not filename.lower().endswith(".png") or
                image.get("type") != "output"):
            raise ComfyError("Caminho de arquivo retornado pelo ComfyUI é inválido.")
        return {"filename": filename, "subfolder": folder, "type": "output"}

    def generate_image(self, prompt, checkpoint, *, seed=0, width=512, height=512,
                       negative_prompt="", steps=20, cancel=None, on_progress=None, resource_slot=None):
        """Retorna (PNG bytes, metadados). Chamar em worker com permissão de escrita.

        resource_slot é uma fábrica de context manager que entrega bool de aquisição.
        O chamador fornece coordenação da GPU; não há instalação nem fallback cloud.
        O workflow inicial se destina a checkpoints SD 1.x/SDXL compatíveis com os
        nós padrão, não garante suporte a toda arquitetura listada pelo serviço.
        """
        for value, minimum, maximum in ((width, 256, 1536), (height, 256, 1536), (steps, 1, 50), (seed, 0, 2**64 - 1)):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ComfyError("Dimensões, passos ou seed fora dos limites permitidos.")
        if width % 64 or height % 64 or width * height > 1536 * 1024:
            raise ComfyError("Dimensões devem ser múltiplas de 64 e ter até 1,5 megapixel.")
        if (not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000 or
                not isinstance(negative_prompt, str) or len(negative_prompt) > 8000 or
                not isinstance(checkpoint, str) or not checkpoint or len(checkpoint) > 512):
            raise ComfyError("Prompt ou checkpoint inválido.")
        self._check(time.monotonic() + self.total_timeout, cancel)
        with (resource_slot() if resource_slot else nullcontext(True)) as acquired:
            if not acquired:
                raise ComfyCancelled("Espera pela GPU cancelada.")
            with self._client() as client:
                return self._generate(client, prompt, checkpoint, seed, width, height,
                                      negative_prompt, steps, cancel, on_progress)

    def _generate(self, client, prompt, checkpoint, seed, width, height, negative, steps, cancel, progress):
        started = time.monotonic()
        deadline = started + self.total_timeout
        prompt_id, submission_started = None, False
        prefix = "orbita_" + uuid.uuid4().hex
        workflow = self._workflow(prompt, checkpoint, negative, seed, width, height, steps, prefix)

        def emit(state):
            if progress:
                progress({"state": state, "prompt_id": prompt_id,
                          "elapsed_seconds": time.monotonic() - started})
        try:
            health = self._health(client, deadline, cancel)
            if health["missing_nodes"]:
                raise ComfyError("ComfyUI não dispõe dos nós padrão necessários.")
            if checkpoint not in health["checkpoints"]:
                raise ComfyError("O checkpoint escolhido não está instalado no ComfyUI.")
            self._check(deadline, cancel)
            submission_started = True
            queued = self._request(client, "POST", "/prompt", deadline,
                                   payload={"prompt": workflow, "client_id": uuid.uuid4().hex})
            prompt_id = queued.get("prompt_id")
            if not isinstance(prompt_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", prompt_id):
                prompt_id = None
                raise ComfyError("ComfyUI não confirmou um identificador válido para a tarefa.")
            emit("queued")
            while True:
                self._check(deadline, cancel)
                history = self._request(client, "GET", f"/history/{prompt_id}", deadline, cancel=cancel)
                entry = history.get(prompt_id)
                if entry is not None:
                    if not isinstance(entry, dict) or not isinstance(entry.get("status"), dict):
                        raise ComfyError("Histórico incompatível da tarefa do ComfyUI.")
                    status = entry["status"]
                    if status.get("status_str") == "error":
                        raise ComfyError("A geração no ComfyUI falhou; confira o serviço local.")
                    if status.get("completed") is True:
                        outputs = entry.get("outputs", {})
                        output = outputs.get("9") if isinstance(outputs, dict) else None
                        images = output.get("images", []) if isinstance(output, dict) else []
                        if not isinstance(images, list) or not images:
                            raise ComfyError("ComfyUI terminou sem uma imagem no nó de saída.")
                        image = self._image_path(images[0], prefix)
                        path = httpx.URL("/view", params=image)
                        content = self._request(client, "GET", path, deadline, cancel=cancel,
                                                binary=True, max_bytes=self.max_image_bytes)
                        if not content.startswith(_PNG_SIGNATURE):
                            raise ComfyError("Arquivo recebido não tem assinatura PNG válida.")
                        emit("completed")
                        return content, {"backend": "comfyui", "prompt_id": prompt_id, "seed": seed,
                                         "width": width, "height": height, "steps": steps, "checkpoint": checkpoint,
                                         "prompt": prompt, "negative_prompt": negative, "workflow": workflow,
                                         "devices": health["devices"], "source_file": image,
                                         "duration_seconds": round(time.monotonic() - started, 3)}
                emit("waiting")
                delay = min(self.poll_interval, self._check(deadline, cancel))
                if cancel is not None:
                    cancel.wait(delay)
                else:
                    threading.Event().wait(delay)
        except Exception as error:
            # Um callback do chamador também pode falhar; a fila própria precisa
            # de limpeza antes de propagar a exceção original, sem mascará-la.
            may_still_run = self._remove_owned(client, prompt_id) if prompt_id else submission_started
            if isinstance(error, ComfyError):
                error.prompt_id = prompt_id
                error.may_still_run = may_still_run
                if may_still_run:
                    error.args = (str(error) + " A tarefa pode continuar no ComfyUI; não foi interrompido trabalho de terceiros.",)
            raise
