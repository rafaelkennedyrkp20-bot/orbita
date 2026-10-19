import base64
import io
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from agent.core import providers
from agent.core.providers import (AnthropicProvider, OpenAICompatProvider, OllamaProvider,
                                  ProviderError, _http_error, _stream_request, ToolsUnsupported)

HISTORY = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "oi"},
    {"role": "assistant", "content": "vou ler", "tool_calls": [
        {"id": "c1", "name": "read_file", "arguments": {"path": "a"}},
        {"id": "c2", "name": "screenshot", "arguments": {}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "conteúdo"},
    {"role": "tool", "tool_call_id": "c2", "name": "screenshot", "content": "tela", "images": []},
    {"role": "assistant", "content": "pronto"},
]


def test_openai_conversion():
    p = OpenAICompatProvider("x", {"base_url": "http://x"})
    out = p._convert("gpt", HISTORY)
    assert out[2]["tool_calls"][0]["function"]["arguments"] == '{"path": "a"}'
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "tool", "assistant"]


def test_openai_tool_images_follow_tool_messages(tmp_path):
    image = tmp_path / "s.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    history = HISTORY[:4] + [{**HISTORY[4], "images": [str(image)]}] + HISTORY[5:]
    out = OpenAICompatProvider("x", {"base_url": "http://x"})._convert("gpt", history)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "tool", "user", "assistant"]
    assert out[5]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_deepseek_text_only_drops_images_with_notice(tmp_path):
    image = tmp_path / "s.png"
    image.write_bytes(b"x")
    history = [{"role": "user", "content": "veja", "images": [str(image)]}]
    out = OpenAICompatProvider("deepseek", {"base_url": "https://api.deepseek.com"})._convert("deepseek-chat", history)
    assert out[0]["content"].startswith("veja\n[imagem anexada não enviada")


def test_deepseek_v4_sends_images(tmp_path):
    """Caso real (river): DeepSeek-V4.1-Flash lê imagem, mas o Órbita a descartava em silêncio."""
    image = tmp_path / "s.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    p = OpenAICompatProvider("river", {"base_url": "https://api.river.ai/v1"})
    for model in ("deepseek-ai/DeepSeek-V4.1-Flash", "deepseek-ai/DeepSeek-V4.1-Flash-1017"):
        out = p._convert(model, [{"role": "user", "content": "veja", "images": [str(image)]}])
        assert out[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    for model in ("deepseek-chat", "deepseek-reasoner", "deepseek-ai/DeepSeek-R1", "deepseek-v3.2", "deepseek-coder"):
        assert not p.supports_vision(model)
    assert p.supports_vision("deepseek-ai/deepseek-vl2")


def test_several_attached_images_go_labeled_in_order(tmp_path):
    """Caso real: 9 páginas numeradas chegaram sem identificação e o modelo traduziu na ordem errada."""
    paths = []
    for name in ("01.png", "02.png"):
        (tmp_path / name).write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(tmp_path / name))
    history = [{"role": "user", "content": "traduza", "images": paths}]
    parts = OpenAICompatProvider("x", {"base_url": "http://x"})._convert("gpt", history)[0]["content"]
    assert [p["type"] for p in parts] == ["text", "text", "image_url", "text", "image_url"]
    assert parts[1]["text"] == "Imagem 1 de 2: 01.png" and parts[3]["text"] == "Imagem 2 de 2: 02.png"
    _, out = AnthropicProvider("a", {})._convert("m", history)
    blocks = out[0]["content"]
    assert [b.get("text") for b in blocks if b["type"] == "text"] == ["Imagem 1 de 2: 01.png", "Imagem 2 de 2: 02.png",
                                                                     "traduza"]
    item = OllamaProvider("o", {"vision": True})._convert("m", history)[0]
    assert "[Imagens anexadas, nesta ordem: Imagem 1 de 2: 01.png; Imagem 2 de 2: 02.png]" in item["content"]


def test_tall_page_goes_in_overlapping_slices(tmp_path):
    """Caso real: página de manhwa 720×14.290 inteira chega reduzida a ~900 tokens e o modelo inventa o texto;
    em partes de 720×2.160 os dois DeepSeek do river leram os balões."""
    from PIL import Image

    tall, small = tmp_path / "02.webp", tmp_path / "tela.png"
    Image.new("RGB", (720, 14290), "white").save(tall)
    Image.new("RGB", (1920, 1080), "white").save(small)
    inputs = providers._image_inputs([str(tall)])
    assert len(inputs) == 7 and {mime for _, mime, _ in inputs} == {"image/jpeg"}
    assert inputs[0][0] == "02.webp, parte 1 de 7 (de cima para baixo)"
    heights = [Image.open(io.BytesIO(base64.b64decode(data))).size for _, _, data in inputs]
    assert heights[0] == (720, 2160) and sum(h for _, h in heights) - 6 * 120 == 14290
    assert providers._image_inputs([str(small)]) == [("", "image/png", providers._image_b64(str(small))[1])]
    labels = [label for label, _, _ in providers._image_inputs([str(small), str(tall)])]
    assert labels[:2] == ["Imagem 1 de 2: tela.png", "Imagem 2 de 2: 02.webp, parte 1 de 7 (de cima para baixo)"]


def test_anthropic_groups_tool_results_in_one_user_turn():
    system, out = AnthropicProvider("a", {})._convert("claude-opus-5-5", HISTORY)
    assert system == "sys"
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]
    results = out[2]["content"]
    assert [b["tool_use_id"] for b in results] == ["c1", "c2"]
    assert out[1]["content"][1] == {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a"}}


def test_anthropic_replays_native_blocks():
    request = [{"role": "user", "content": "x"}]
    prefix = providers._Prefix("", None).add("user", [{"type": "text", "text": "x"}]).digest()
    native = {"provider": "anthropic", "prefix": prefix,
              "content": [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": "oi"}]}
    _, out = AnthropicProvider("a", {})._convert("m", request + [{"role": "assistant", "content": "oi", "_native": native}])
    assert out[1]["content"] == native["content"]
    # Prefixo desconhecido (sessão antiga) ou editado: o pensamento fica fora, o texto vai.
    for stale in ({**native, "prefix": "outro"}, {k: v for k, v in native.items() if k != "prefix"}):
        _, out = AnthropicProvider("a", {})._convert("m", request + [{"role": "assistant", "content": "oi", "_native": stale}])
        assert out[1]["content"] == [{"type": "text", "text": "oi"}]


def test_ollama_conversion_and_vision_hint():
    p = OllamaProvider("ollama", {})
    out = p._convert("qwen2.5:14b", HISTORY)
    assert out[2]["tool_calls"][0]["function"]["arguments"] == {"path": "a"}
    assert out[3]["tool_name"] == "read_file"
    assert p.supports_vision("qwen2.5vl:7b") and not p.supports_vision("qwen2.5:14b")


def test_tools_unsupported_detection():
    assert isinstance(_http_error(400, '{"error": "registry.ollama.ai/x does not support tools"}'), ToolsUnsupported)
    assert not isinstance(_http_error(400, '{"error": "bad request"}'), ToolsUnsupported)


def test_openai_preserves_reasoning_content_on_tool_calls():
    p = OpenAICompatProvider("deepseek", {"base_url": "https://api.deepseek.com/v1"})
    messages = [
        {"role": "user", "content": "analise"},
        {"role": "assistant", "content": "", "reasoning": "passo 1: ler arquivo",
         "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "x.py"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "print(1)"},
    ]
    out = p._convert("deepseek-reasoner", messages)
    assert out[1]["reasoning_content"] == "passo 1: ler arquivo"
    assert out[1]["tool_calls"][0]["function"]["name"] == "read_file"


def test_connect_timeout_retries_and_returns_friendly_error(monkeypatch):
    attempts = []

    def timeout(request):
        attempts.append(request)
        raise httpx.ConnectTimeout("tempo esgotado", request=request)

    monkeypatch.setattr(providers.time, "sleep", lambda _seconds: None)
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ProviderError, match="Não foi possível conectar"):
            _stream_request(client, "https://example.invalid/chat", {}, {}, attempts=2)
    assert len(attempts) == 2


def test_retry_after_http_date_retries_instead_of_raising(monkeypatch):
    attempts, waits = [], []
    retry_at = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=10), usegmt=True)

    def respond(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": retry_at}, json={"error": "limite"})
        return httpx.Response(200, text="data: [DONE]\n\n")

    monkeypatch.setattr(providers.time, "sleep", waits.append)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        response = _stream_request(client, "https://example.invalid/chat", {}, {}, attempts=2)
        response.close()
    assert len(attempts) == 2
    assert len(waits) == 1 and 0 < waits[0] <= 20


def test_http_error_list_still_explains_authentication():
    error = _http_error(401, '[{"message": "chave inválida"}]')
    assert isinstance(error, ProviderError)
    assert "HTTP 401" in str(error)
    assert "Verifique a chave de API" in str(error)



class _Delta:
    def __init__(self, kind, **fields):
        self.type = kind
        self.__dict__.update(fields)


class _Event:
    def __init__(self, delta):
        self.type = "content_block_delta"
        self.delta = delta


class _FakeAnthropicStream:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return iter(self.events)

    def __exit__(self, *exc):
        return False


def _anthropic_with(events):
    from types import SimpleNamespace

    from agent.core.providers import AnthropicProvider

    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **params: _FakeAnthropicStream(events)))
    return AnthropicProvider("claude", {"type": "anthropic"}), client


def test_cancelled_claude_stream_keeps_partial_text():
    """#22: o texto já mostrado sumia do resultado (e do histórico) ao parar o streaming."""
    import threading

    cancel = threading.Event()
    shown = []

    def on_text(piece):
        shown.append(piece)
        cancel.set()

    provider, client = _anthropic_with([
        _Event(_Delta("thinking_delta", thinking="pensando")),
        _Event(_Delta("text_delta", text="parcial")),
        _Event(_Delta("text_delta", text=" nunca mostrado")),
    ])
    result = provider._stream(client, {"model": "claude-opus-5-5", "messages": []}, False, on_text, None, cancel)
    assert result.stop_reason == "cancelled"
    assert result.text == "".join(shown) == "parcial"
    assert result.reasoning == "pensando" and result.tool_calls == [] and result.native is None


def test_cancel_before_first_delta_and_during_partial_tool():
    import threading

    cancel = threading.Event()
    cancel.set()
    provider, client = _anthropic_with([_Event(_Delta("text_delta", text="x"))])
    result = provider._stream(client, {"model": "m", "messages": []}, False, None, None, cancel)
    assert result.text == "" and result.stop_reason == "cancelled"

    cancel = threading.Event()
    events = [_Event(_Delta("text_delta", text="vou gravar")),
              _Event(_Delta("input_json_delta", partial_json='{"path": "a.t')),
              _Event(_Delta("input_json_delta", partial_json='xt"}'))]
    provider, client = _anthropic_with(events)
    seen = []

    def on_text(piece):
        seen.append(piece)

    original = events[1].delta
    events[1] = _Event(original)
    result = provider._stream(client, {"model": "m", "messages": []}, False, on_text, None,
                              _CancelAfter(cancel, 2))
    assert result.text == "vou gravar" and result.tool_calls == [] and result.native is None


class _CancelAfter:
    """Evento que fica marcado depois de N consultas (no meio da ferramenta parcial)."""

    def __init__(self, event, after):
        self.event, self.after, self.checks = event, after, 0

    def is_set(self):
        self.checks += 1
        return self.checks > self.after
