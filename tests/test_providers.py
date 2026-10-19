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


def test_deepseek_drops_images(tmp_path):
    image = tmp_path / "s.png"
    image.write_bytes(b"x")
    history = [{"role": "user", "content": "veja", "images": [str(image)]}]
    out = OpenAICompatProvider("deepseek", {"base_url": "https://api.deepseek.com"})._convert("deepseek-chat", history)
    assert out == [{"role": "user", "content": "veja"}]


def test_anthropic_groups_tool_results_in_one_user_turn():
    system, out = AnthropicProvider("a", {})._convert("claude-opus-5-5", HISTORY)
    assert system == "sys"
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]
    results = out[2]["content"]
    assert [b["tool_use_id"] for b in results] == ["c1", "c2"]
    assert out[1]["content"][1] == {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a"}}


def test_anthropic_replays_native_blocks():
    native = {"provider": "anthropic", "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                                                    {"type": "text", "text": "oi"}]}
    _, out = AnthropicProvider("a", {})._convert("m", [{"role": "user", "content": "x"},
                                                       {"role": "assistant", "content": "oi", "_native": native}])
    assert out[1]["content"] == native["content"]


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

