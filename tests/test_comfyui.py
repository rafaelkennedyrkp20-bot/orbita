"""Contrato HTTP do ComfyUI sem executar modelos ou instalar componentes."""

import json
import threading
from contextlib import contextmanager

import httpx
import pytest

from agent.actions.comfyui import ComfyCancelled, ComfyClient, ComfyError


PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-fixture"
NODES = ("CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage", "KSampler", "VAEDecode", "SaveImage")


class Server:
    def __init__(self):
        self.calls = []
        self.workflow = None
        self.mode = "success"
        self.cancel = None
        self.checkpoints = ["sd15.safetensors"]
        self.missing_node = None
        self.filename = None

    def handle(self, request):
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if path == "/system_stats":
            return httpx.Response(200, json={"system": {"comfyui_version": "test"}, "devices": [{"name": "test GPU"}]})
        if path.startswith("/object_info/"):
            node = path.rsplit("/", 1)[1]
            data = {} if node == self.missing_node else {node: {"input": {"required": {}}}}
            if node == "CheckpointLoaderSimple" and data:
                data[node]["input"]["required"]["ckpt_name"] = [self.checkpoints]
            return httpx.Response(200, json=data)
        if path == "/prompt":
            self.workflow = body["prompt"]
            if self.mode == "reject":
                return httpx.Response(400, json={"error": "invalid"})
            if self.cancel:
                self.cancel.set()
            return httpx.Response(200, json={"prompt_id": "ours", "node_errors": {}})
        if path == "/queue" and request.method == "POST":
            assert body == {"delete": ["ours"]}
            return httpx.Response(200, content=b"")
        if path == "/queue":
            ours = [[0, "ours", {}, {}, []]]
            return httpx.Response(200, json={"queue_running": ours if self.mode == "running" else [],
                                            "queue_pending": [[1, "someone-else", {}, {}, []]]})
        if path == "/history/ours":
            if self.mode in {"pending", "running"}:
                return httpx.Response(200, json={})
            if self.mode == "failure":
                entry = {"status": {"status_str": "error", "completed": False}, "outputs": {}}
            else:
                filename = self.filename or self.workflow["9"]["inputs"]["filename_prefix"] + "_00001_.png"
                entry = {"status": {"status_str": "success", "completed": True},
                         "outputs": {"9": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}}}
            return httpx.Response(200, json={"ours": entry})
        if path == "/view":
            assert request.url.params["type"] == "output"
            return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        raise AssertionError(f"Requisição inesperada: {request.method} {path}")

    def client(self, **kwargs):
        return ComfyClient("http://127.0.0.1:8188", transport=httpx.MockTransport(self.handle),
                           poll_interval=0.001, **kwargs)


def test_health_lists_models_and_reports_missing_nodes():
    server = Server()
    assert server.client().health()["checkpoints"] == ["sd15.safetensors"]
    server.checkpoints = []
    assert server.client().health()["status"] == "no_models"
    server.missing_node = "KSampler"
    assert server.client().health()["status"] == "incompatible"


def test_success_builds_only_standard_workflow_and_preserves_metadata():
    server = Server()
    events = []
    image, metadata = server.client().generate_image("uma árvore", "sd15.safetensors", seed=42,
                                                     width=512, height=768, on_progress=events.append)
    assert image == PNG
    assert metadata["seed"] == 42 and metadata["prompt_id"] == "ours"
    assert metadata["width"] == 512 and metadata["height"] == 768
    assert metadata["devices"] == [{"name": "test GPU"}]
    assert metadata["duration_seconds"] >= 0
    assert set(node["class_type"] for node in server.workflow.values()) == set(NODES)
    assert server.workflow["3"]["inputs"]["seed"] == 42
    assert server.workflow["6"]["inputs"]["text"] == "uma árvore"
    assert events[-1]["state"] == "completed"


def test_missing_model_and_nodes_fail_before_enqueue():
    server = Server()
    with pytest.raises(ComfyError, match="checkpoint"):
        server.client().generate_image("árvore", "absent.safetensors")
    server.missing_node = "VAEDecode"
    with pytest.raises(ComfyError, match="nós"):
        server.client().generate_image("árvore", "sd15.safetensors")
    assert not any(path == "/prompt" for _, path, _ in server.calls)


@pytest.mark.parametrize("kwargs", [{"width": 513}, {"height": 0}, {"steps": 1000},
                                    {"seed": -1}, {"width": True}, {"prompt": ""}])
def test_invalid_generation_parameters_do_not_touch_server(kwargs):
    server = Server()
    with pytest.raises(ComfyError):
        server.client().generate_image(**({"prompt": "árvore", "checkpoint": "sd15.safetensors"} | kwargs))
    assert server.calls == []


@pytest.mark.parametrize("url", ["http://user:secret@localhost:8188", "http://localhost:8188/?token=secret",
                                "file:///tmp/comfy", "http://example.com:8188", "http://localhost:8188/#frag"])
def test_url_rejects_credentials_external_hosts_and_non_http(url):
    with pytest.raises(ComfyError):
        ComfyClient(url)


@pytest.mark.parametrize("mode", ["pending", "running"])
def test_cancel_deletes_only_own_pending_job_and_never_interrupts_others(mode):
    server = Server()
    server.mode = mode
    server.cancel = threading.Event()
    with pytest.raises(ComfyCancelled) as caught:
        server.client().generate_image("árvore", "sd15.safetensors", cancel=server.cancel)
    assert caught.value.prompt_id == "ours"
    assert caught.value.may_still_run is (mode == "running")
    mutations = [(path, body) for method, path, body in server.calls if method == "POST"]
    assert mutations[-1] == ("/queue", {"delete": ["ours"]})
    assert not any(path == "/interrupt" for _, path, _ in server.calls)


def test_pre_cancel_does_not_enqueue_or_query_server():
    server = Server()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ComfyCancelled):
        server.client().generate_image("árvore", "sd15.safetensors", cancel=cancel)
    assert server.calls == []


def test_server_failure_is_reported_without_polling_forever():
    server = Server()
    server.mode = "failure"
    with pytest.raises(ComfyError, match="falhou"):
        server.client().generate_image("árvore", "sd15.safetensors")


@pytest.mark.parametrize("filename", ["../secret.png", "C:\\secret.png", "../../.env", "/other.png"])
def test_output_traversal_is_rejected_before_download(filename):
    server = Server()
    server.filename = filename
    with pytest.raises(ComfyError, match="arquivo"):
        server.client().generate_image("árvore", "sd15.safetensors")
    assert not any(path == "/view" for _, path, _ in server.calls)


def test_response_size_is_bounded():
    server = Server()
    with pytest.raises(ComfyError, match="limite"):
        server.client(max_image_bytes=8).generate_image("árvore", "sd15.safetensors")


def test_timeout_removes_only_owned_job():
    server = Server()
    server.mode = "pending"
    with pytest.raises(ComfyError, match="prazo"):
        server.client(total_timeout=0.03).generate_image("árvore", "sd15.safetensors")
    assert ("POST", "/queue", {"delete": ["ours"]}) in server.calls


def test_optional_resource_slot_wraps_generation_and_releases():
    server = Server()
    phases = []
    @contextmanager
    def slot():
        phases.append("acquired")
        try:
            yield True
        finally:
            phases.append("released")
    server.client().generate_image("árvore", "sd15.safetensors", resource_slot=slot)
    assert phases == ["acquired", "released"]


def test_unreachable_service_health_is_actionable():
    def offline(request):
        raise httpx.ConnectError("secret server diagnostic", request=request)
    info = ComfyClient(transport=httpx.MockTransport(offline)).health()
    assert info["status"] == "unreachable"
    assert "secret" not in str(info)


def test_malformed_output_is_reported_as_protocol_error():
    server = Server()
    def broken(request):
        if request.url.path == "/history/ours":
            return httpx.Response(200, json={"ours": {"status": {"completed": True}, "outputs": {"9": []}}})
        return server.handle(request)
    client = ComfyClient(transport=httpx.MockTransport(broken))
    with pytest.raises(ComfyError, match="imagem"):
        client.generate_image("árvore", "sd15.safetensors")


def test_progress_callback_failure_removes_owned_job_before_propagating():
    server = Server()
    def broken(event):
        raise RuntimeError("callback quebrado")
    with pytest.raises(RuntimeError, match="callback quebrado"):
        server.client().generate_image("árvore", "sd15.safetensors", on_progress=broken)
    assert ("POST", "/queue", {"delete": ["ours"]}) in server.calls


def test_denied_resource_never_contacts_server():
    server = Server()
    @contextmanager
    def slot():
        yield False
    with pytest.raises(ComfyCancelled):
        server.client().generate_image("árvore", "sd15.safetensors", resource_slot=slot)
    assert server.calls == []


@pytest.mark.parametrize("response", [httpx.Response(200, content=b"not-json"),
                                     httpx.Response(200, json=[]),
                                     httpx.Response(302, headers={"location": "https://example.org"})])
def test_incompatible_responses_do_not_follow_redirect_or_reflect_payload(response):
    def handler(request):
        assert request.url.host == "127.0.0.1"
        return response
    info = ComfyClient(transport=httpx.MockTransport(handler)).health()
    assert info["status"] == "unreachable"
    assert "example.org" not in str(info)
