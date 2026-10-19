"""Clipe curto: limite antes de executar, sem ffmpeg real e sem modelo de vídeo."""

import threading
from pathlib import Path

from agent.actions.image_gen import register_image_tool
from agent.actions.short_clip import ClipError, render_clip
from agent.core.gallery import Gallery
from agent.core.tools import ToolContext


def _png(folder: Path, name: str = "a.png") -> Path:
    path = folder / name
    path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return path


def test_render_refuses_limits_and_missing_ffmpeg(tmp_path, monkeypatch):
    frame = _png(tmp_path)
    dest = tmp_path / "out.mp4"
    try:
        render_clip([frame] * 13, dest, seconds=4, width=640, height=360, ffmpeg="ffmpeg")
    except ClipError as error:
        assert "12" in str(error)
    else:
        raise AssertionError("aceitou imagens demais")
    try:
        render_clip([frame], dest, seconds=9, width=640, height=360, ffmpeg="ffmpeg")
    except ClipError as error:
        assert "8" in str(error)
    else:
        raise AssertionError("aceitou duração demais")
    monkeypatch.setattr("agent.actions.short_clip.shutil.which", lambda name: None)
    try:
        render_clip([frame], dest, seconds=2, width=640, height=360)
    except ClipError as error:
        assert "ffmpeg" in str(error).lower()
        assert "não baixa" in str(error).lower()
    else:
        raise AssertionError("rodou sem ffmpeg")
    assert not dest.exists()


def test_render_builds_a_bounded_command_and_cancel_removes_the_file(tmp_path):
    frame = _png(tmp_path)
    dest = tmp_path / "out.mp4"
    seen = {}

    def runner(argv, cancel):
        seen["argv"] = argv
        assert float(argv[argv.index("-t") + 1]) <= 8
        assert argv[argv.index("-r") + 1] == "8"
        assert int(argv[argv.index("-frames:v") + 1]) <= 64
        assert "http" not in " ".join(argv)
        dest.write_bytes(b"mp4")
        cancel.set()
        return -1

    cancel = threading.Event()
    try:
        render_clip([frame, _png(tmp_path, "b.png")], dest, seconds=4, width=640, height=360,
                    cancel=cancel, runner=runner, ffmpeg="ffmpeg")
    except ClipError as error:
        assert "cancelada" in str(error).lower()
    else:
        raise AssertionError("cancelamento não subiu")
    assert not dest.exists()
    assert seen["argv"][0] == "ffmpeg"


def test_tool_blocks_staged_remote_and_outside_project(brain, tmp_path, monkeypatch):
    register_image_tool(brain.registry, brain)

    def boom(*args, **kwargs):
        raise AssertionError("ffmpeg foi chamado")

    monkeypatch.setattr("agent.actions.image_gen.render_clip", boom)
    tool = brain.registry.get("make_short_clip")
    brain.settings.set("staged_writes", "on", save=False)
    staged = tool.run({"images": ["a.png"]}, ToolContext(workspace=tmp_path))
    assert staged.is_error and "revisão" in staged.text.lower()
    brain.settings.set("staged_writes", "off", save=False)
    remote = tool.run({"images": ["https://example.com/a.png"]}, ToolContext(workspace=tmp_path))
    assert remote.is_error and "remoto" in remote.text.lower()
    brain.settings.set("file_scope", "project", save=False)

    class Session:
        settings = brain.settings
        workspace = tmp_path

    outside = tool.run({"images": [str(_png(tmp_path))], "save_to": str(tmp_path.parent / "fora.mp4")},
                       ToolContext(workspace=tmp_path, session=Session()))
    assert outside.is_error and "Escopo" in outside.text
    assert not (tmp_path.parent / "fora.mp4").exists()


def test_tool_records_a_local_clip_without_calling_image_apis(brain, tmp_path, monkeypatch):
    register_image_tool(brain.registry, brain)
    gallery = Gallery(tmp_path / "gallery.json")
    monkeypatch.setattr("agent.core.gallery.get_gallery", lambda: gallery)
    monkeypatch.setattr("agent.actions.image_gen._openai_image", lambda *a, **k: (_ for _ in ()).throw(AssertionError("API")))

    def fake_render(frames, dest, **kwargs):
        assert len(frames) == 1
        assert kwargs["seconds"] <= 8
        dest.write_bytes(b"mp4")

    monkeypatch.setattr("agent.actions.image_gen.render_clip", fake_render)
    dest = tmp_path / "clipe.mp4"
    result = brain.registry.get("make_short_clip").run({
        "images": [str(_png(tmp_path))], "seconds": 4, "size": "640x360", "save_to": str(dest),
        "prompt": "passeio",
    }, ToolContext(workspace=tmp_path))
    assert not result.is_error and dest.is_file()
    assert "modelo de vídeo" in result.text and "Nenhum peso foi baixado" in result.text
    rows = gallery.list(tmp_path)
    assert rows[0]["kind"] == "clip" and rows[0]["backend"] == "ffmpeg" and rows[0]["exists"]
