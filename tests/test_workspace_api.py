"""Pasta de projeto e API compatível com a OpenAI adicionada na mão."""


import httpx

from agent.core.providers import probe_compat_models
from agent.core.settings import Settings, project_folder_name, resolve_workspace


def test_resolve_workspace_prefers_profile_then_default_then_home(tmp_path):
    home = tmp_path / "casa"
    project = tmp_path / "projeto"
    profile = tmp_path / "perfil"
    home.mkdir()
    project.mkdir()
    profile.mkdir()
    assert resolve_workspace("", "", home=home) == home
    assert resolve_workspace("", str(project), home=home) == project
    assert resolve_workspace(str(profile), str(project), home=home) == profile
    assert resolve_workspace(str(tmp_path / "sumiu"), str(project), home=home) == home


def test_project_folder_name_rejects_paths_and_reserved_names():
    assert project_folder_name(" site da loja ") == "site da loja"
    for bad in ("../fora", "a/b", "a\\b", "con", "AUX", "nome?", ""):
        try:
            project_folder_name(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_add_and_remove_custom_provider(tmp_path, monkeypatch):
    settings = Settings(tmp_path / "settings.json")
    saved = {}
    monkeypatch.setattr(Settings, "save_api_key", staticmethod(lambda env, value: saved.update({env: value})))
    provider_id = settings.add_custom_provider(
        label="Together AI",
        base_url="https://api.together.xyz/v1/",
        api_key="sk-test",
        models=["meta-llama"],
    )
    assert provider_id == "together_ai"
    cfg = settings.provider(provider_id)
    assert cfg["base_url"] == "https://api.together.xyz/v1"
    assert cfg["models"] == ["meta-llama"]
    assert cfg["api_key_env"] == "ORBITA_TOGETHER_AI_API_KEY"
    assert saved == {"ORBITA_TOGETHER_AI_API_KEY": "sk-test"}
    assert "sk-test" not in (tmp_path / "settings.json").read_text(encoding="utf-8")

    local_id = settings.add_custom_provider(label="Meu servidor", base_url="http://127.0.0.1:8080/v1")
    assert settings.has_credentials(local_id)
    again = settings.add_custom_provider(label="Meu servidor", base_url="http://127.0.0.1:8081/v1")
    assert again == "meu_servidor_2"

    try:
        settings.remove_custom_provider("openai")
    except ValueError:
        pass
    else:
        raise AssertionError("provedor padrão não pode sair")
    settings.remove_custom_provider(provider_id)
    assert provider_id not in settings.providers()


def test_probe_lists_models_and_normalizes_the_base_url(monkeypatch):
    seen = []

    class Response:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload

        def json(self):
            if not isinstance(self._payload, (dict, list)):
                raise ValueError("não é json")
            return self._payload

    def fake_get(url, headers, timeout, follow_redirects):
        seen.append(url)
        assert headers["Authorization"] == "Bearer segredo"
        assert timeout == 12 and follow_redirects is True
        if url.endswith("/v1/models"):
            return Response(200, {"data": [{"id": "modelo-b"}, {"id": "modelo-a"}]})
        return Response(404, {})

    monkeypatch.setattr(httpx, "get", fake_get)
    found = probe_compat_models("https://api.exemplo.com", "segredo")
    assert found["ok"] is True
    assert found["base_url"] == "https://api.exemplo.com/v1"
    assert found["models"] == ["modelo-a", "modelo-b"]
    assert seen == ["https://api.exemplo.com/v1/models"]

    refused = probe_compat_models("ftp://arquivo", "")
    assert refused["ok"] is False
    assert "http" in refused["error"]


def test_used_models_become_visible_to_the_team(tmp_path, monkeypatch):
    """Caso real: API própria (river) com chave e lista de modelos vazia não aparecia para a equipe — o Grok
    gastou ~100 s procurando no PC o nome do DeepSeek para delegar."""
    from agent.core import routing

    settings = Settings(tmp_path / "settings.json")
    monkeypatch.setattr(Settings, "save_api_key", staticmethod(lambda env, value: None))
    monkeypatch.setattr(Settings, "api_key", lambda self, cfg: "rv-teste" if cfg.get("api_key_env") else "")
    settings.add_custom_provider(label="river", base_url="https://api.exemplo/v1", api_key="rv-teste")
    refs = lambda: routing.candidate_refs(settings, ("grok", "grok-4.7"), [], [])  # noqa: E731
    assert not any(r.startswith("river:") for r in refs())

    assert settings.remember_models("river", ["deepseek-ai/DeepSeek-V4.1-Flash"])
    assert "river:deepseek-ai/DeepSeek-V4.1-Flash" in refs()
    # Lista vinda da API só preenche quando estava vazia (não incha provedores com centenas de modelos)
    assert not settings.remember_models("river", ["zai-org/GLM-5.3-Flash"], only_if_empty=True)
    assert settings.remember_models("river", ["zai-org/GLM-5.3-Flash"])
    assert settings.provider("river")["models"] == ["deepseek-ai/DeepSeek-V4.1-Flash", "zai-org/GLM-5.3-Flash"]
    assert not settings.remember_models("nao-existe", ["x"])


def test_local_gateway_without_key_end_to_end(tmp_path):
    """Gateway local sem chave (ex.: OmniRoute em 127.0.0.1:20128): endereço sem /v1, adicionar e listar modelos."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from agent.core.providers import get_provider

    class Gateway(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/v1/models":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"object": "list", "data": [{"id": "kr/claude-sonnet-4.5"}, {"id": "gh/gpt-5"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        address = f"http://127.0.0.1:{server.server_address[1]}"
        found = probe_compat_models(address, "")
        assert found["ok"] and found["base_url"] == address + "/v1"
        assert found["models"] == ["gh/gpt-5", "kr/claude-sonnet-4.5"]

        settings = Settings(tmp_path / "settings.json")
        provider_id = settings.add_custom_provider(label="OmniRoute", base_url=found["base_url"],
                                                   models=["kr/claude-sonnet-4.5"])
        assert settings.has_credentials(provider_id)                       # sem chave conta como pronto
        assert get_provider(provider_id, settings).list_models() == ["gh/gpt-5", "kr/claude-sonnet-4.5"]
    finally:
        server.shutdown()
        server.server_close()
