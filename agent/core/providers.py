"""
providers.py — Camada única para conversar com qualquer IA.

Formato interno de mensagem (independente de provedor):
    {"role": "system"|"user"|"assistant"|"tool",
     "content": str,
     "images": [caminho, ...],                       # user/tool (visão)
     "tool_calls": [{"id", "name", "arguments": dict}],  # assistant
     "tool_call_id": str, "name": str,               # tool
     "_native": {...}}                               # assistant: blocos originais do provedor

Provedores:
    OllamaProvider        → API nativa do Ollama (/api/chat), local
    OpenAICompatProvider  → OpenAI, DeepSeek, Gemini, OpenRouter, Groq, xAI, Mistral,
                            LM Studio, vLLM... qualquer endpoint /chat/completions
    AnthropicProvider     → Claude, pelo SDK oficial `anthropic` (carregado sob demanda)
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import math
import mimetypes
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from functools import lru_cache, wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from agent.core import inference_queue

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

TextCallback = Optional[Callable[[str], None]]

_http_client_instance: Any = None
_http_client_lock = threading.Lock()


def _httpx():
    import httpx as _mod

    globals()["httpx"] = _mod
    return _mod


def __getattr__(name: str):
    if name == "httpx":
        return _httpx()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _shared_http_client() -> "httpx.Client":
    """Reutiliza um único httpx.Client thread-safe (evita recriar contexto SSL/TLS a cada chamada)."""
    global _http_client_instance
    if _http_client_instance is None:
        with _http_client_lock:
            if _http_client_instance is None:
                hx = _httpx()
                timeout = hx.Timeout(connect=15, read=600, write=60, pool=10)
                _http_client_instance = hx.Client(timeout=timeout)
    return _http_client_instance


class ProviderError(RuntimeError):
    """Erro de comunicação com o provedor (mensagem já amigável)."""


class ToolsUnsupported(ProviderError):
    """O modelo não aceita ferramentas nativas — o loop usa o modo por prompt."""


@dataclass
class ChatResult:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    reasoning: str = ""
    stop_reason: str = ""
    native: Optional[dict] = None
    usage: dict = field(default_factory=dict)


def _coordinated_inference(chat):
    """Reserva apenas a chamada ao modelo, nunca ferramentas ou subagentes."""
    @wraps(chat)
    def run(self, *args, **kwargs):
        on_event = kwargs.pop("on_inference_event", None)
        cfg = dict(self.cfg)
        if isinstance(self, OllamaProvider):
            cfg["type"] = "ollama"
        from agent.core.local_policy import refusal

        blocked = refusal(getattr(self, "settings", None), self.name, cfg)
        if blocked:
            raise ProviderError(blocked)
        resource = inference_queue.inference_resource(cfg, self.name)
        with inference_queue.INFERENCE_QUEUE.slot(resource, cancel=kwargs.get("cancel"),
                                                  on_event=on_event) as acquired:
            if not acquired:
                return ChatResult(stop_reason="cancelled")
            return chat(self, *args, **kwargs)
    return run


def new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:20]


def preserves_thinking(model: str) -> bool:
    """Kimi exige reasoning_content integral nas mensagens anteriores destes modelos."""
    return bool(re.search(r"(^|/)kimi-(k3|(k3\.1-pro|k2\.7-code)(-highspeed)?)$", model or "", re.I))


def _image_b64(path: str) -> tuple[str, str]:
    data = Path(path).read_bytes()
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return mime, base64.b64encode(data).decode("ascii")


SLICE_MIN_PX = 1600   # parte de imagem alta: 3× a largura, no mínimo isto
SLICE_OVERLAP = 6     # cada parte repete 1/6 da largura do fim da anterior (balão no corte aparece inteiro)


@lru_cache(maxsize=32)
def _image_pieces(path: str, _mtime: float, _size: int) -> tuple[tuple[str, str], ...]:
    """(mime, base64) de uma imagem; página alta (manhwa de 720×15.000) vai em partes de cima para baixo.
    Inteira, a API reduz a página a ~900 tokens e o modelo inventa o texto; em partes de 720×2.160 ele lê.
    O Claude também recusa imagem com mais de 8.000 px. Mtime e tamanho entram na chave do cache."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            step = max(width * 3, SLICE_MIN_PX)
            if height > step * 1.5:
                pieces, top = [], 0
                while True:
                    bottom = min(height, top + step)
                    buffer = io.BytesIO()
                    image.crop((0, top, width, bottom)).convert("RGB").save(buffer, "JPEG", quality=90)
                    pieces.append(("image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii")))
                    if bottom >= height:
                        return tuple(pieces)
                    top = bottom - width // SLICE_OVERLAP
    except Exception as error:   # formato que o Pillow não abre: vai o arquivo como está
        logger.debug("Imagem enviada sem fatiar (%s): %s", path, error)
    return (_image_b64(path),)


def _image_inputs(paths: list[str] | None) -> list[tuple[str, str, str]]:
    """(rótulo, mime, base64) das imagens que existem, na ordem. Com mais de uma imagem ou parte, cada uma leva
    "Imagem N de T: nome, parte P de Q", para o modelo seguir a ordem e citar a página certa."""
    found = [p for p in paths or [] if Path(p).is_file()]
    out = []
    for i, path in enumerate(found, 1):
        stat = Path(path).stat()
        pieces = _image_pieces(path, stat.st_mtime, stat.st_size)
        for j, (mime, data) in enumerate(pieces, 1):
            label = f"Imagem {i} de {len(found)}: {Path(path).name}" if len(found) > 1 else Path(path).name
            if len(pieces) > 1:
                label += f", parte {j} de {len(pieces)} (de cima para baixo)"
            elif len(found) == 1:
                label = ""   # uma imagem inteira dispensa rótulo
            out.append((label, mime, data))
    return out


def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"value": value}
    except (TypeError, json.JSONDecodeError):
        return {"__invalid_json__": str(raw)}


class Provider:
    """Interface comum. `chat` faz streaming e devolve o resultado consolidado."""

    supports_native_tools = True

    def __init__(self, name: str, cfg: dict, settings=None):
        self.name = name
        self.cfg = cfg
        self.settings = settings

    @property
    def api_key(self) -> str:
        from agent.core.settings import Settings

        return Settings.api_key(self.cfg)

    def supports_vision(self, model: str) -> bool:
        if "vision" in self.cfg:
            return bool(self.cfg["vision"])
        return True

    def chat(self, model: str, messages: list[dict], tools: list[dict] | None = None, *,
             temperature: float | None = None, max_tokens: int | None = None,
             on_text: TextCallback = None, on_reasoning: TextCallback = None,
             cancel: threading.Event | None = None, **extra) -> ChatResult:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        return list(self.cfg.get("models", []))


# ─────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────

_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


def _stream_request(client: "httpx.Client", url: str, payload: dict, headers: dict,
                    attempts: int = 3, timeout: Any = None) -> "httpx.Response":
    """Abre um POST em streaming com novas tentativas para falhas transitórias."""
    hx = _httpx()
    delay = 1.5
    for attempt in range(attempts):
        try:
            kwargs: dict[str, Any] = {"json": payload, "headers": headers}
            if timeout is not None:
                kwargs["timeout"] = timeout
            request = client.build_request("POST", url, **kwargs)
            response = client.send(request, stream=True)
        except (hx.ConnectError, hx.TimeoutException, hx.RemoteProtocolError) as error:
            if attempt == attempts - 1:
                raise ProviderError(f"Não foi possível conectar a {url}: {error}") from error
            time.sleep(delay)
            delay *= 2
            continue
        if response.status_code < 400:
            return response
        body = response.read().decode("utf-8", errors="replace")
        response.close()
        if response.status_code in _RETRY_STATUS and attempt < attempts - 1:
            wait = delay
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    wait = float(retry_after)
                except ValueError:
                    try:
                        wait = parsedate_to_datetime(retry_after).timestamp() - time.time()
                    except (TypeError, ValueError, OverflowError):
                        pass
            time.sleep(min(max(wait if math.isfinite(wait) else delay, 0), 20))
            delay *= 2
            continue
        raise _http_error(response.status_code, body)
    raise ProviderError("Falha desconhecida de rede.")


def _http_error(status: int, body: str) -> ProviderError:
    try:
        detail = json.loads(body)
        if isinstance(detail, dict):
            detail = detail.get("error", detail)
        if isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail, ensure_ascii=False)
        elif isinstance(detail, list):
            detail = json.dumps(detail, ensure_ascii=False)[:500]
    except json.JSONDecodeError:
        detail = body[:500]
    text = f"HTTP {status}: {detail}"
    lowered = str(detail).lower()
    if status == 400 and ("does not support tools" in lowered or "tool" in lowered and "not supported" in lowered
                          or "function calling" in lowered and "not" in lowered):
        return ToolsUnsupported(text)
    if status in (401, 403):
        return ProviderError(f"{text}\nVerifique a chave de API em Configurações.")
    return ProviderError(text)


# ─────────────────────────────────────────────────────────────
# Ollama (local)
# ─────────────────────────────────────────────────────────────

class OllamaProvider(Provider):

    VISION_HINTS = ("llava", "vision", "-vl", "vl:", "gemma3", "minicpm-v", "moondream", "qwen2.5vl", "llama4")

    @property
    def base_url(self) -> str:
        return self.cfg.get("base_url", "http://127.0.0.1:11434").rstrip("/")

    def supports_vision(self, model: str) -> bool:
        if "vision" in self.cfg:
            return bool(self.cfg["vision"])
        return any(hint in model.lower() for hint in self.VISION_HINTS)

    def _convert(self, model: str, messages: list[dict]) -> list[dict]:
        vision = self.supports_vision(model)
        out = []
        for msg in messages:
            role = msg["role"]
            item: dict[str, Any] = {"role": role, "content": msg.get("content") or ""}
            if role == "assistant" and msg.get("tool_calls"):
                item["tool_calls"] = [
                    {"function": {"name": c["name"], "arguments": c.get("arguments", {})}}
                    for c in msg["tool_calls"]
                ]
            if role == "tool":
                item["tool_name"] = msg.get("name", "")
            if msg.get("images"):
                if vision:
                    inputs = _image_inputs(msg["images"])
                    item["images"] = [data for _, _, data in inputs]
                    if len(inputs) > 1:
                        item["content"] += "\n[Imagens anexadas, nesta ordem: " + "; ".join(
                            label for label, _, _ in inputs) + "]"
                else:
                    item["content"] += "\n[imagem anexada não enviada: este modelo não tem visão]"
            out.append(item)
        return out

    @_coordinated_inference
    def chat(self, model, messages, tools=None, *, temperature=None, max_tokens=None,
             on_text=None, on_reasoning=None, cancel=None, **extra) -> ChatResult:
        settings = self.settings
        options: dict[str, Any] = {"num_ctx": int(settings.get("ollama_num_ctx", 16384)) if settings else 16384}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens:
            options["num_predict"] = max_tokens
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._convert(model, messages),
            "stream": True,
            "options": options,
            "keep_alive": settings.get("ollama_keep_alive", "10m") if settings else "10m",
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        result = ChatResult()
        text_parts, reasoning_parts = [], []
        hx = _httpx()
        timeout = hx.Timeout(connect=10, read=600, write=60, pool=10)
        client = _shared_http_client()
        response = _stream_request(client, f"{self.base_url}/api/chat", payload, {}, timeout=timeout)
        try:
            for line in response.iter_lines():
                if cancel is not None and cancel.is_set():
                    result.stop_reason = "cancelled"
                    break
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise ProviderError(chunk["error"])
                message = chunk.get("message") or {}
                if message.get("thinking"):
                    reasoning_parts.append(message["thinking"])
                    if on_reasoning:
                        on_reasoning(message["thinking"])
                if message.get("content"):
                    text_parts.append(message["content"])
                    if on_text:
                        on_text(message["content"])
                for call in message.get("tool_calls") or []:
                    fn = call.get("function", {})
                    result.tool_calls.append({
                        "id": call.get("id") or new_call_id(),
                        "name": fn.get("name", ""),
                        "arguments": _parse_args(fn.get("arguments")),
                    })
                if chunk.get("done"):
                    result.stop_reason = chunk.get("done_reason", "stop")
                    result.usage = {
                        "input_tokens": chunk.get("prompt_eval_count", 0),
                        "output_tokens": chunk.get("eval_count", 0),
                    }
        finally:
            response.close()
        result.text = "".join(text_parts)
        result.reasoning = "".join(reasoning_parts)
        return result

    def installed_models(self) -> list[str]:
        """Modelos realmente instalados; lista vazia se o Ollama não responder."""
        try:
            import urllib.request

            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return sorted(m["name"] for m in data.get("models", []))
        except Exception as error:
            logger.debug("Ollama indisponível ao listar modelos: %s", error)
            return []

    def list_models(self) -> list[str]:
        return self.installed_models() or super().list_models()


# ─────────────────────────────────────────────────────────────
# OpenAI-compatível (OpenAI, DeepSeek, Gemini, OpenRouter, Groq, xAI, LM Studio...)
# ─────────────────────────────────────────────────────────────

class OpenAICompatProvider(Provider):

    @property
    def base_url(self) -> str:
        return self.cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")

    # DeepSeek só-texto: API oficial (chat/reasoner) e gerações até a V3/R1. A V4 lê imagem.
    DEEPSEEK_TEXT_ONLY = re.compile(r"deepseek-(chat|reasoner|coder|r1|v2|v3)")

    def supports_vision(self, model: str) -> bool:
        if "vision" in self.cfg:
            return bool(self.cfg["vision"])
        lowered = model.lower()
        return "vl" in lowered or not self.DEEPSEEK_TEXT_ONLY.search(lowered)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter" in self.base_url:
            headers["HTTP-Referer"] = "https://github.com/rafaelkennedyrkp20-bot/orbita"
            headers["X-Title"] = "Orbita"
        return headers

    def _convert(self, model: str, messages: list[dict]) -> list[dict]:
        vision = self.supports_vision(model)
        out: list[dict] = []
        pending_images: list[str] = []

        def image_parts(paths: list[str]) -> list[dict]:
            parts: list[dict] = []
            for label, mime, data in _image_inputs(paths):
                if label:
                    parts.append({"type": "text", "text": label})
                parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
            return parts

        def flush_images():
            if pending_images and vision:
                out.append({"role": "user", "content": [{"type": "text", "text": "Imagens retornadas pelas ferramentas acima:"}]
                            + image_parts(pending_images)})
            pending_images.clear()

        for msg in messages:
            role = msg["role"]
            if role != "tool":
                flush_images()
            if role == "assistant":
                item: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or None}
                if msg.get("reasoning") and (msg.get("tool_calls") or preserves_thinking(model)):
                    item["reasoning_content"] = msg["reasoning"]
                if msg.get("tool_calls"):
                    item["tool_calls"] = [{
                        "id": c["id"], "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments", {}), ensure_ascii=False)},
                    } for c in msg["tool_calls"]]
                out.append(item)
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": msg.get("tool_call_id", ""), "content": msg.get("content") or ""})
                pending_images.extend(msg.get("images") or [])
            elif role == "user" and msg.get("images") and vision:
                out.append({"role": "user", "content": [{"type": "text", "text": msg.get("content") or ""}]
                            + image_parts(msg["images"])})
            elif role == "user" and msg.get("images"):
                out.append({"role": "user", "content": (msg.get("content") or "")
                            + "\n[imagem anexada não enviada: este modelo não tem visão]"})
            else:
                out.append({"role": role, "content": msg.get("content") or ""})
        flush_images()
        return out

    @_coordinated_inference
    def chat(self, model, messages, tools=None, *, temperature=None, max_tokens=None,
             on_text=None, on_reasoning=None, cancel=None, **extra) -> ChatResult:
        payload: dict[str, Any] = {"model": model, "messages": self._convert(model, messages), "stream": True}
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
        if temperature is not None and not self.cfg.get("omit_temperature"):
            payload["temperature"] = temperature
        if max_tokens:
            payload[self.cfg.get("max_tokens_param", "max_tokens")] = max_tokens
        # K3/K3.1 usam esforço no nível superior; não aceitam o parâmetro thinking.
        if re.search(r"(^|/)kimi-k3($|\.1-pro(-highspeed)?$)", model or "", re.I) and extra.get("effort"):
            effort = extra["effort"]
            if effort not in ("low", "high", "max"):
                raise ProviderError("Kimi K3/K3.1 aceita esforço low, high ou max. Ajuste o perfil.")
            payload["reasoning_effort"] = effort
        if "openai.com" in self.base_url or "deepseek" in self.base_url:
            payload["stream_options"] = {"include_usage": True}

        hx = _httpx()
        timeout = hx.Timeout(connect=15, read=600, write=60, pool=10)
        client = _shared_http_client()
        try:
            response = _stream_request(client, f"{self.base_url}/chat/completions", payload, self._headers(), timeout=timeout)
        except ToolsUnsupported:
            raise
        except ProviderError as error:
            # Alguns modelos rejeitam parâmetros opcionais: tenta de novo sem eles.
            message = str(error).lower()
            dropped = [k for k in ("temperature", "max_tokens", "max_completion_tokens", "stream_options")
                       if k in payload and k in message]
            if not dropped:
                raise
            for key in dropped:
                payload.pop(key, None)
            response = _stream_request(client, f"{self.base_url}/chat/completions", payload, self._headers(), timeout=timeout)
        return self._consume(response, on_text, on_reasoning, cancel)

    @staticmethod
    def _consume(response: "httpx.Response", on_text, on_reasoning, cancel) -> ChatResult:
        result = ChatResult()
        text_parts, reasoning_parts = [], []
        calls: dict[int, dict] = {}
        try:
            for line in response.iter_lines():
                if cancel is not None and cancel.is_set():
                    result.stop_reason = "cancelled"
                    break
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise ProviderError(str(chunk["error"]))
                if chunk.get("usage"):
                    usage = chunk["usage"]
                    result.usage = {"input_tokens": usage.get("prompt_tokens", 0),
                                    "output_tokens": usage.get("completion_tokens", 0)}
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        reasoning_parts.append(reasoning)
                        if on_reasoning:
                            on_reasoning(reasoning)
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                        if on_text:
                            on_text(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", len(calls)), {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        result.stop_reason = choice["finish_reason"]
        finally:
            response.close()
        result.text = "".join(text_parts)
        result.reasoning = "".join(reasoning_parts)
        result.tool_calls = [
            {"id": slot["id"] or new_call_id(), "name": slot["name"], "arguments": _parse_args(slot["arguments"])}
            for _, slot in sorted(calls.items()) if slot["name"]
        ]
        return result

    def list_models(self) -> list[str]:
        if self.cfg.get("api_key_env") and not self.api_key:
            return super().list_models()
        try:
            response = _shared_http_client().get(f"{self.base_url}/models", headers=self._headers(), timeout=8)
            response.raise_for_status()
            ids = sorted({item["id"] for item in response.json().get("data", []) if item.get("id")})
            return ids or super().list_models()
        except Exception as error:
            logger.debug("Não foi possível listar modelos de %s: %s", self.name, error)
            return super().list_models()


# ─────────────────────────────────────────────────────────────
# Anthropic (Claude) — SDK oficial
# ─────────────────────────────────────────────────────────────

THINKING_BLOCKS = ("thinking", "redacted_thinking")


class _Prefix:
    """Impressão digital do que vai antes de um ponto da requisição ao Claude: sistema, ferramentas e blocos.

    Nos Claude atuais (Opus 5.5, Fable 5.1) um bloco de pensamento só vale com o prefixo exato que o gerou; editar
    o meio do histórico (encurtar resultado antigo, cortar passos) dá HTTP 400 nas contas novas.
    """

    def __init__(self, system: str, tools: list[dict] | None):
        self._hash = hashlib.sha256(json.dumps([system, tools or []], sort_keys=True, ensure_ascii=False).encode())

    def add(self, role: str, blocks: list[dict]) -> "_Prefix":
        for block in blocks:
            self._hash.update(json.dumps([role, block], sort_keys=True, ensure_ascii=False).encode())
        return self

    def add_messages(self, messages: list[dict]) -> "_Prefix":
        for message in messages:
            self.add(message["role"], message["content"])
        return self

    def digest(self) -> str:
        return self._hash.copy().hexdigest()[:32]


class AnthropicProvider(Provider):

    # Modelos que aceitam o fallback automático do servidor em caso de recusa.
    FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")

    def __init__(self, name, cfg, settings=None):
        super().__init__(name, cfg, settings)
        self._client = None

    def _sdk(self):
        try:
            import anthropic
        except ImportError as error:
            raise ProviderError("Instale o SDK: pip install anthropic") from error
        if self._client is None:
            kwargs: dict[str, Any] = {"max_retries": 2}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.cfg.get("base_url"):
                kwargs["base_url"] = self.cfg["base_url"]
            self._client = anthropic.Anthropic(**kwargs)
        return anthropic, self._client

    @staticmethod
    def _image_blocks(paths: list[str] | None) -> list[dict]:
        blocks: list[dict] = []
        for label, mime, data in _image_inputs(paths):
            if label:
                blocks.append({"type": "text", "text": label})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
        return blocks

    def _convert(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> tuple[str, list[dict]]:
        system = "\n\n".join(msg.get("content") or "" for msg in messages if msg["role"] == "system")
        out: list[dict] = []
        prefix = _Prefix(system, tools)

        def push(role: str, blocks: list[dict]):
            # A API exige alternância user/assistant: junta blocos consecutivos do mesmo papel.
            prefix.add(role, blocks)
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": blocks})

        for msg in messages:
            role = msg["role"]
            if role == "user":
                blocks = self._image_blocks(msg.get("images"))
                blocks.append({"type": "text", "text": msg.get("content") or "(vazio)"})
                push("user", blocks)
            elif role == "assistant":
                native = msg.get("_native") or {}
                if native.get("provider") == "anthropic" and native.get("content"):
                    # Devolve os blocos originais sem alterar. O pensamento só vai se o que vem antes dele for
                    # idêntico ao que gerou a resposta; senão sai só desta cópia (texto e chamadas ficam).
                    blocks = list(native["content"])
                    if native.get("prefix") != prefix.digest():
                        blocks = [b for b in blocks if not (isinstance(b, dict) and b.get("type") in THINKING_BLOCKS)]
                    if blocks:
                        push("assistant", blocks)
                        continue
                blocks = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": msg["content"]})
                for call in msg.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": call["id"], "name": call["name"],
                                   "input": call.get("arguments", {})})
                push("assistant", blocks or [{"type": "text", "text": "(sem texto)"}])
            elif role == "tool":
                content: list[dict] = [{"type": "text", "text": msg.get("content") or "(sem saída)"}]
                content += self._image_blocks(msg.get("images"))
                block = {"type": "tool_result", "tool_use_id": msg.get("tool_call_id", ""), "content": content}
                if msg.get("is_error"):
                    block["is_error"] = True
                push("user", [block])
        return system, out

    @_coordinated_inference
    def chat(self, model, messages, tools=None, *, temperature=None, max_tokens=None,
             on_text=None, on_reasoning=None, cancel=None, effort: str | None = None, **extra) -> ChatResult:
        anthropic, client = self._sdk()
        api_tools = [{
            "name": t["name"], "description": t.get("description", ""),
            "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
            "eager_input_streaming": True,
        } for t in tools or []]
        system, converted = self._convert(model, messages, api_tools)
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or 64000,
            "messages": converted,
            "cache_control": {"type": "ephemeral"},
        }
        if system:
            params["system"] = system
        if api_tools:
            params["tools"] = api_tools
        if effort:
            params["output_config"] = {"effort": effort}

        use_fallback = model in self.FALLBACK_MODELS
        try:
            return self._stream(client, params, use_fallback, on_text, on_reasoning, cancel)
        except anthropic.BadRequestError as error:
            if use_fallback and "fallback" in str(error).lower():
                return self._stream(client, params, False, on_text, on_reasoning, cancel)
            raise ProviderError(f"Claude recusou a requisição: {error}") from error
        except anthropic.AuthenticationError as error:
            raise ProviderError("Chave da Anthropic inválida. Configure ANTHROPIC_API_KEY.") from error
        except anthropic.APIStatusError as error:
            raise ProviderError(f"Erro da API Anthropic ({error.status_code}): {error}") from error
        except anthropic.APIConnectionError as error:
            raise ProviderError(f"Sem conexão com a API Anthropic: {error}") from error

    def _stream(self, client, params, use_fallback, on_text, on_reasoning, cancel) -> ChatResult:
        if use_fallback:
            manager = client.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        else:
            manager = client.messages.stream(**params)
        result = ChatResult()
        texts, thoughts = [], []   # o que já foi mostrado: fica no resultado se a pessoa parar
        with manager as stream:
            for event in stream:
                if cancel is not None and cancel.is_set():
                    result.stop_reason = "cancelled"
                    break
                if event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        texts.append(delta.text)
                        if on_text:
                            on_text(delta.text)
                    elif delta.type == "thinking_delta" and delta.thinking:
                        thoughts.append(delta.thinking)
                        if on_reasoning:
                            on_reasoning(delta.thinking)
            if result.stop_reason == "cancelled":
                # Só o texto e o raciocínio parciais; uma ferramenta pela metade nunca vira chamada.
                result.text, result.reasoning = "".join(texts), "".join(thoughts)
                return result
            final = stream.get_final_message()

        blocks = [block.model_dump(exclude_none=True) for block in final.content]
        # Prefixo que gerou esta resposta: o pensamento dela só volta enquanto ele não mudar (ver _convert).
        prefix = _Prefix(params.get("system", ""), params.get("tools")).add_messages(params["messages"]).digest()
        result.native = {"provider": "anthropic", "model": params["model"], "content": blocks, "prefix": prefix}
        result.stop_reason = final.stop_reason or ""
        result.usage = {"input_tokens": final.usage.input_tokens, "output_tokens": final.usage.output_tokens,
                        # O cache fica fora de input_tokens: lido custa ~10%, gravado ~125% do preço de entrada.
                        "cache_read_input_tokens": getattr(final.usage, "cache_read_input_tokens", 0) or 0,
                        "cache_creation_input_tokens": getattr(final.usage, "cache_creation_input_tokens", 0) or 0}
        texts = []
        for block in final.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "thinking":
                result.reasoning += getattr(block, "thinking", "") or ""
            elif block.type == "tool_use":
                result.tool_calls.append({"id": block.id, "name": block.name,
                                          "arguments": block.input if isinstance(block.input, dict) else {}})
        result.text = "".join(texts)
        if result.stop_reason == "refusal":
            details = getattr(final, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            result.text += f"\n\n[O modelo recusou a solicitação{f' ({category})' if category else ''}.]"
            result.tool_calls = []
        elif result.stop_reason == "max_tokens" and result.tool_calls:
            # Entrada de ferramenta truncada: não executar.
            result.tool_calls = []
            result.text += "\n\n[Resposta cortada pelo limite de tokens antes de concluir a chamada de ferramenta.]"
        return result

    def list_models(self) -> list[str]:
        if not self.api_key:
            return super().list_models()
        try:
            _, client = self._sdk()
            ids = [model.id for model in client.models.list(limit=100)]
            return ids or super().list_models()
        except Exception as error:
            logger.debug("Não foi possível listar modelos Claude: %s", error)
            return super().list_models()


PROVIDER_TYPES = {
    "ollama": OllamaProvider,
    "openai": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
}

_cache: dict[tuple, Provider] = {}
_cache_lock = threading.Lock()


def _model_ids(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        items = payload.get("data") if isinstance(payload.get("data"), list) else payload.get("models")
    elif isinstance(payload, list):
        items = payload
    else:
        items = None
    found: list[str] = []
    for item in items or []:
        if isinstance(item, str) and item.strip():
            found.append(item.strip())
        elif isinstance(item, dict):
            value = item.get("id") or item.get("name") or ""
            if str(value).strip():
                found.append(str(value).strip())
    return sorted(set(found))


def probe_compat_models(base_url: str, api_key: str = "") -> dict[str, Any]:
    """Consulta /models de uma API compatível com a OpenAI e devolve o endereço que funcionou."""
    url = (base_url or "").strip().rstrip("/")
    empty = {"ok": False, "models": [], "base_url": url, "error": ""}
    if not url.startswith(("http://", "https://")):
        empty["error"] = "O endereço precisa começar com http:// ou https://."
        return empty
    headers = {"Accept": "application/json"}
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    endpoints = [f"{url}/models"] if url.endswith("/v1") else [f"{url}/v1/models", f"{url}/models"]
    last = "A API não respondeu. Confira o endereço e se ela está no ar."
    hx = _httpx()
    for endpoint in endpoints:
        try:
            response = hx.get(endpoint, headers=headers, timeout=12, follow_redirects=True)
        except hx.HTTPError:
            last = "Não consegui conectar nesse endereço. Confira o link e a internet."
            continue
        if response.status_code in (401, 403):
            empty["error"] = ("A API recusou essa chave. Confira se copiou a chave inteira e se ela está ativa no painel "
                              "do serviço." if (api_key or "").strip() else
                              "Este servidor pede uma chave. Gateways como OmniRoute e LiteLLM pedem uma chave criada no "
                              "painel deles (no OmniRoute: API Keys), mesmo rodando no seu PC. Cole-a no campo Chave.")
            return empty
        if response.status_code >= 400:
            last = f"A API respondeu {response.status_code}. Confira se o endereço termina em /v1."
            continue
        try:
            payload = response.json()
        except ValueError:
            last = "A resposta não é uma lista de modelos. O endereço precisa ser uma API compatível com a OpenAI."
            continue
        ids = _model_ids(payload)
        if ids:
            return {"ok": True, "models": ids[:1000], "base_url": endpoint[: -len("/models")], "error": ""}
        last = "Conectou, mas não veio uma lista de modelos. Você ainda pode digitar o nome do modelo."
    empty["error"] = last
    return empty


def get_provider(name: str, settings) -> Provider:
    """Instancia (com cache) o provedor configurado em `settings`."""
    cfg = settings.provider(name)
    key = (name, json.dumps(cfg, sort_keys=True), settings.api_key(cfg))
    with _cache_lock:
        if key not in _cache:
            if cfg.get("type") == "deepseek_web":
                from agent.core.deepseek_web import DeepSeekWebProvider
                PROVIDER_TYPES["deepseek_web"] = DeepSeekWebProvider
            if cfg.get("type") == "grok_cli":
                from agent.core.grok_cli import GrokBuildProvider  # import tardio: evita ciclo
                PROVIDER_TYPES["grok_cli"] = GrokBuildProvider
            kind = PROVIDER_TYPES.get(cfg.get("type", "openai"))
            if kind is None:
                raise ProviderError(f"Tipo de provedor inválido: {cfg.get('type')}")
            _cache[key] = kind(name, cfg, settings)
        return _cache[key]
