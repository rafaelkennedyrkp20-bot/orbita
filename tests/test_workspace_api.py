"""Pasta de projeto e API compatível com a OpenAI adicionada na mão."""

from pathlib import Path

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
