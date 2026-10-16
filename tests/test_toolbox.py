"""Caixa de ferramentas: catálogo válido e instalação segura, tudo sem internet."""

import hashlib
import io
import json
import re
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

from agent.core import toolbox as tb
from agent.core.tools import ToolContext, ToolRegistry

OFFICIAL = {  # domínio + começo do caminho de cada projeto
    "imagemagick": ("github.com", "/ImageMagick/ImageMagick/"),
    "openscad": ("files.openscad.org", "/"),
    "blender": ("download.blender.org", "/release/"),
    "godot": ("github.com", "/godotengine/godot/"),
    "ffmpeg": ("github.com", "/GyanD/codexffmpeg/"),   # builds Windows da gyan.dev, indicadas em ffmpeg.org
}


def test_catalog_is_valid_and_official():
    tools = tb.load_catalog()
    assert [t["id"] for t in tools] == ["imagemagick", "openscad", "blender", "godot", "ffmpeg"]
    for item in tools:
        assert item["name"] and item["purpose"] and item["version"] and item["test"]
        assert "windows" in item["packages"], item["id"]
        assert item["packages"].get("linux") or item.get("linux_packages"), item["id"]
        for platform, pkg in item["packages"].items():
            url = urlparse(pkg["url"])
            host, prefix = OFFICIAL[item["id"]]
            assert url.scheme == "https" and url.netloc == host and url.path.startswith(prefix), pkg["url"]
            assert item["version"].split("-stable")[0] in pkg["url"], "versão fixa na URL"
            assert re.fullmatch(r"[0-9a-f]{64}", pkg["sha256"]), (item["id"], platform)
            assert isinstance(pkg["size"], int) and pkg["size"] > 1_000_000
            assert pkg["format"] in tb.FORMATS and pkg["exe"] and pkg["sha256_source"]


# ── Catálogo falso + download falso (copia um zip local) ──────

def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def fake(tmp_path, monkeypatch):
    payload = _zip_bytes({"fake-1.0/bin/fake.exe": "binário falso", "fake-1.0/LEIA.txt": "oi"})
    source = tmp_path / "fake-1.0.zip"
    source.write_bytes(payload)
    pkg = {"url": "https://example.org/releases/fake-1.0.zip", "sha256": hashlib.sha256(payload).hexdigest(),
           "size": len(payload), "format": "zip", "exe": "fake.exe", "sha256_source": "teste"}
    catalog = {"tools": [
        {"id": "fake", "name": "Fake", "purpose": "teste", "version": "1.0", "test": ["--version"],
         "packages": {"windows": pkg}, "linux_packages": {"apt": "sudo apt install fake"}},
    ]}
    catalog_path = tmp_path / "catalog.json"

    def save():
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    save()
    fetched = []

    def fetch(url, target, on_bytes, cancel=None, limit=0):
        fetched.append(url)
        data = source.read_bytes()
        Path(target).write_bytes(data)
        on_bytes(len(data))

    monkeypatch.setattr(tb.shutil, "which", lambda name: None)   # nada "no PATH" durante os testes
    box = tb.Toolbox(root=tmp_path / "tools", catalog_path=catalog_path, platform="windows", fetch=fetch)
    events = []
    box.add_listener(events.append)
    return {"box": box, "pkg": pkg, "catalog": catalog, "save": save, "fetched": fetched,
            "events": events, "source": source, "root": tmp_path / "tools"}


def test_install_from_local_zip_and_find_executable(fake):
    box = fake["box"]
    assert box.find_executable("fake") is None
    exe = box.install("fake")
    assert exe == fake["root"] / "fake" / "1.0" / "fake-1.0" / "bin" / "fake.exe"
    assert box.find_executable("fake") == exe
    assert fake["fetched"] == ["https://example.org/releases/fake-1.0.zip"]
    status = box.status("fake")
    assert status["installed"] and status["exe"] == str(exe) and status["source"] == "example.org"
    assert [e["state"] for e in fake["events"]][-1] == "done"
    assert not list((fake["root"] / "fake").glob("*.part")) and not list((fake["root"] / "fake").glob(".staging*"))
    assert box.install("fake") == exe and len(fake["fetched"]) == 1   # já instalado: não baixa de novo


def test_wrong_hash_is_refused_and_deleted(fake):
    fake["catalog"]["tools"][0]["packages"]["windows"]["sha256"] = "0" * 64
    fake["save"]()
    with pytest.raises(ValueError, match="SHA-256"):
        fake["box"].install("fake")
    folder = fake["root"] / "fake"
    assert list(folder.iterdir()) == []                      # sem .part, sem staging, sem versão
    assert fake["box"].find_executable("fake") is None
    assert fake["events"][-1]["state"] == "error"


def test_wrong_size_is_refused(fake):
    fake["catalog"]["tools"][0]["packages"]["windows"]["size"] += 1
    fake["save"]()
    with pytest.raises(ValueError, match="Tamanho"):
        fake["box"].install("fake")
    assert list((fake["root"] / "fake").iterdir()) == []


def test_only_https_catalog_urls(fake):
    fake["catalog"]["tools"][0]["packages"]["windows"]["url"] = "http://example.org/fake-1.0.zip"
    fake["save"]()
    with pytest.raises(ValueError):
        fake["box"].install("fake")
    with pytest.raises(KeyError):
        fake["box"].install("https://evil.example/x.zip")
    assert fake["fetched"] == []


def test_zip_slip_is_refused(fake):
    payload = _zip_bytes({"../fora.exe": "x", "fake.exe": "x"})
    fake["source"].write_bytes(payload)
    pkg = fake["catalog"]["tools"][0]["packages"]["windows"]
    pkg.update(sha256=hashlib.sha256(payload).hexdigest(), size=len(payload))
    fake["save"]()
    with pytest.raises(ValueError, match="perigoso"):
        fake["box"].install("fake")
    assert not (fake["root"] / "fake" / "fora.exe").exists()
    assert list((fake["root"] / "fake").iterdir()) == []


def test_remove(fake):
    box = fake["box"]
    box.install("fake")
    assert box.remove("fake") is True
    assert box.find_executable("fake") is None and not (fake["root"] / "fake").exists()
    assert box.remove("fake") is False


def test_linux_without_package_shows_package_manager(fake):
    box = tb.Toolbox(root=fake["root"], catalog_path=fake["box"].catalog_path, platform="linux",
                     fetch=fake["box"].fetch)
    status = box.status("fake")
    assert not status["available"] and status["package_commands"]["apt"] == "sudo apt install fake"
    registry = ToolRegistry()
    tb.register_toolbox_tools(registry, box)
    out = registry.get("toolbox_install").run({"id": "fake"}, ToolContext(workspace=fake["root"]))
    assert "sudo apt install fake" in out.text and "nada foi baixado" in out.text
    assert fake["fetched"] == []


def test_agent_tools_risk_and_output(fake, monkeypatch):
    box = fake["box"]
    registry = ToolRegistry()
    tb.register_toolbox_tools(registry, box)
    install, listing = registry.get("toolbox_install"), registry.get("toolbox_list")
    assert install.risk == "exec" and listing.risk == "read"
    assert install.parameters["properties"]["id"]["enum"] == ["fake"]
    assert "não instalado" in listing.run({}, ToolContext(workspace=fake["root"])).text
    detail = box.approval_detail("fake")
    assert "Fake 1.0" in detail and "https://example.org/releases/fake-1.0.zip" in detail and "MB" in detail
    monkeypatch.setattr(box, "run_test", lambda tool_id: "fake 1.0")
    out = install.run({"id": "fake"}, ToolContext(workspace=fake["root"], cancel=threading.Event()))
    assert not out.is_error and str(box.find_executable("fake")) in out.text and "fake 1.0" in out.text
    assert "instalado:" in listing.run({}, ToolContext(workspace=fake["root"])).text


def test_builtin_registry_has_toolbox():
    from agent.actions.builtin_tools import register_builtin_tools
    registry = ToolRegistry()
    register_builtin_tools(registry, None)
    assert registry.get("toolbox_install").risk == "exec"
    assert registry.get("run_shell") is not None and registry.get("check_web_page") is not None
