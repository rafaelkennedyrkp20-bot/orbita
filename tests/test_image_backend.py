"""ComfyUI opcional no generate_image, sem rede, sem peso e sem fallback pago."""

import threading

from agent.actions.comfyui import ComfyError
from agent.actions.image_gen import register_image_tool
from agent.core.gallery import Gallery
from agent.core.tools import ToolContext


PNG = b"\x89PNG\r\n\x1a\n"


def _tool(brain, tmp_path, monkeypatch):
    register_image_tool(brain.registry, brain)
    gallery = Gallery(tmp_path / "gallery.json")
    monkeypatch.setattr("agent.core.gallery.get_gallery", lambda: gallery)
    return gallery


def test_comfy_generates_on_loopback_and_does_not_call_the_api(brain, tmp_path, monkeypatch):
    gallery = _tool(brain, tmp_path, monkeypatch)
    brain.settings.set("image_backend", "comfy", save=False)
    brain.settings.set("execution_policy", "local_only", save=False)
    brain.settings.set("comfyui_checkpoint", "sd15.safetensors", save=False)
    brain.settings.set("comfyui_url", "http://127.0.0.1:8188", save=False)
    seen = {}

    class Fake:
        def __init__(self, url):
            assert url == "http://127.0.0.1:8188"

        def health(self):
            return {"status": "ready", "checkpoints": ["sd15.safetensors"], "missing_nodes": [],
                    "devices": [{"name": "GPU teste"}]}

        def generate_image(self, prompt, checkpoint, **kwargs):
            seen["prompt"] = prompt
            seen["slot"] = kwargs.get("resource_slot")
            with kwargs["resource_slot"]() as acquired:
                assert acquired is True
            return PNG, {"seed": kwargs["seed"]}

    monkeypatch.setattr("agent.actions.comfyui.ComfyClient", Fake)
    monkeypatch.setattr("agent.actions.image_gen._openai_image", lambda *a, **k: (_ for _ in ()).throw(AssertionError("API paga")))
    out = tmp_path / "foto.png"
    result = brain.registry.get("generate_image").run({
        "prompt": "uma árvore", "style": "luz suave", "negative_prompt": "texto",
        "size": "512x512", "seed": 4, "save_to": str(out),
    }, ToolContext(workspace=tmp_path))
    assert not result.is_error and out.is_file()
    assert "ComfyUI" in result.text and "não" in result.text.lower()
    assert "[Style Anchor: luz suave]" in seen["prompt"]
    rows = gallery.list(tmp_path)
    assert rows[0]["backend"] == "comfyui" and rows[0]["seed"] == 4 and rows[0]["device"] == "GPU teste"


def test_staged_writes_do_not_touch_comfy_or_the_api(brain, tmp_path, monkeypatch):
    _tool(brain, tmp_path, monkeypatch)
    brain.settings.set("staged_writes", "on", save=False)
    brain.settings.set("image_backend", "comfy", save=False)

    def boom(*args, **kwargs):
        raise AssertionError("houve chamada externa")

    monkeypatch.setattr("agent.actions.comfyui.ComfyClient", boom)
    monkeypatch.setattr("agent.actions.image_gen._openai_image", boom)
    result = brain.registry.get("generate_image").run({"prompt": "árvore"}, ToolContext(workspace=tmp_path))
    assert result.is_error and "revisão" in result.text.lower()


def test_comfy_failure_does_not_fall_back_to_a_paid_api(brain, tmp_path, monkeypatch):
    _tool(brain, tmp_path, monkeypatch)
    brain.settings.set("image_backend", "comfy", save=False)
    brain.settings.set("comfyui_checkpoint", "sd15.safetensors", save=False)

    class Fake:
        def __init__(self, url):
            pass

        def health(self):
            return {"status": "ready", "checkpoints": ["sd15.safetensors"], "missing_nodes": [], "devices": []}

        def generate_image(self, *args, **kwargs):
            raise ComfyError("falhou no serviço local")

    monkeypatch.setattr("agent.actions.comfyui.ComfyClient", Fake)
    monkeypatch.setattr("agent.actions.image_gen._openai_image", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fallback")))
    result = brain.registry.get("generate_image").run({"prompt": "árvore"}, ToolContext(workspace=tmp_path))
    assert result.is_error and "falhou no serviço local" in result.text


def test_missing_checkpoint_is_reported_before_queue(brain, tmp_path, monkeypatch):
    _tool(brain, tmp_path, monkeypatch)
    brain.settings.set("image_backend", "comfy", save=False)
    brain.settings.set("comfyui_checkpoint", "ausente.safetensors", save=False)

    class Fake:
        def __init__(self, url):
            pass

        def health(self):
            return {"status": "ready", "checkpoints": ["sd15.safetensors"], "missing_nodes": [], "devices": []}

        def generate_image(self, *args, **kwargs):
            raise AssertionError("enfileirou sem o checkpoint")

    monkeypatch.setattr("agent.actions.comfyui.ComfyClient", Fake)
    result = brain.registry.get("generate_image").run({"prompt": "árvore"}, ToolContext(workspace=tmp_path))
    assert result.is_error and "não está instalado" in result.text


def test_remote_comfy_url_is_refused_without_a_client_call(brain, tmp_path, monkeypatch):
    _tool(brain, tmp_path, monkeypatch)
    brain.settings.set("image_backend", "comfy", save=False)
    brain.settings.set("comfyui_checkpoint", "sd15.safetensors", save=False)
    brain.settings.set("comfyui_url", "https://user:pw@example.com/comfy?x=1", save=False)
    result = brain.registry.get("generate_image").run({"prompt": "árvore"}, ToolContext(workspace=tmp_path))
    assert result.is_error and "local" in result.text.lower()


def test_empty_checkpoint_does_not_construct_a_client(brain, tmp_path, monkeypatch):
    _tool(brain, tmp_path, monkeypatch)
    brain.settings.set("image_backend", "comfy", save=False)

    def boom(*args, **kwargs):
        raise AssertionError("cliente criado")

    monkeypatch.setattr("agent.actions.comfyui.ComfyClient", boom)
    result = brain.registry.get("generate_image").run({"prompt": "árvore"}, ToolContext(workspace=tmp_path))
    assert result.is_error and "checkpoint" in result.text.lower()


def test_cancel_before_comfy_skips_the_server(brain, tmp_path, monkeypatch):
    _tool(brain, tmp_path, monkeypatch)
    brain.settings.set("image_backend", "comfy", save=False)
    brain.settings.set("comfyui_checkpoint", "sd15.safetensors", save=False)
    monkeypatch.setattr("agent.actions.comfyui.ComfyClient", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rede")))
    cancel = threading.Event()
    cancel.set()
    result = brain.registry.get("generate_image").run(
        {"prompt": "árvore"}, ToolContext(workspace=tmp_path, cancel=cancel))
    assert result.is_error and "cancelada" in result.text.lower()


def test_local_only_still_refuses_the_cloud_image_api(brain, tmp_path, monkeypatch):
    _tool(brain, tmp_path, monkeypatch)
    brain.settings.set("execution_policy", "local_only", save=False)
    brain.settings.set("image_model", "openai:gpt-image-1", save=False)
    monkeypatch.setattr("agent.actions.image_gen._openai_image", lambda *a, **k: (_ for _ in ()).throw(AssertionError("nuvem")))
    result = brain.registry.get("generate_image").run({"prompt": "árvore"}, ToolContext(workspace=tmp_path))
    assert result.is_error and "somente local" in result.text.lower()
