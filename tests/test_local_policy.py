"""Política somente local: não envia conversa para nuvem nem para gateway indefinido."""

import pytest

from agent.core.local_policy import data_destination, refusal, tool_block
from agent.core.providers import OpenAICompatProvider, ProviderError
from agent.core.tools import Tool, ToolResult


class _Settings:
    def __init__(self, policy="local_only"):
        self.policy = policy

    def get(self, key, default=None):
        if key == "execution_policy":
            return self.policy
        return default


def test_known_local_engines_are_local_and_gateways_are_not():
    assert data_destination("ollama", {"type": "ollama"}) == "local"
    assert data_destination("lmstudio", {"type": "openai", "base_url": "http://127.0.0.1:1234/v1"}) == "local"
    assert data_destination("river", {"type": "openai", "base_url": "http://127.0.0.1:20128/v1"}) == "unknown"
    assert data_destination("openai", {"type": "openai", "base_url": "https://api.openai.com/v1"}) == "cloud"
    assert data_destination("remote", {
        "type": "openai", "base_url": "https://gpu.example/v1", "inference_resource": "local-gpu",
    }) == "cloud"
    assert data_destination("grok", {"type": "grok_cli"}) == "cloud"


def test_open_policy_does_not_refuse_cloud():
    assert refusal(_Settings("open"), "openai", {"type": "openai", "base_url": "https://api.openai.com/v1"}) is None


def test_local_only_refuses_before_any_http_call(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("rede")

    monkeypatch.setattr("httpx.Client", boom)
    provider = OpenAICompatProvider(
        "openai",
        {"type": "openai", "base_url": "https://api.openai.com/v1", "api_key": "segredo"},
        _Settings(),
    )
    with pytest.raises(ProviderError, match="somente local"):
        provider.chat("gpt", [{"role": "user", "content": "texto privado"}])


def test_local_only_allows_loopback_ollama_destination():
    assert refusal(_Settings(), "ollama", {"type": "ollama", "base_url": "http://127.0.0.1:11434"}) is None


def test_shell_web_and_mcp_are_blocked_writes_are_not():
    settings = _Settings()
    shell = Tool("run_shell", "x", {}, lambda a, c: ToolResult(text="ok"), risk="exec")
    web = Tool("web_search", "x", {}, lambda a, c: ToolResult(text="ok"), risk="read")
    mcp = Tool("evil", "x", {}, lambda a, c: ToolResult(text="ok"), risk="read", source="mcp:demo")
    write = Tool("write_file", "x", {}, lambda a, c: ToolResult(text="ok"), risk="write")
    assert tool_block(settings, shell) and tool_block(settings, web) and tool_block(settings, mcp)
    assert tool_block(settings, write) is None
    assert tool_block(_Settings("open"), shell) is None



