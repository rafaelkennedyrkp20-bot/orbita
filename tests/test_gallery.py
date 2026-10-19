"""Galeria em disco temporário: outro projeto, arquivo ausente e dois tipos de exclusão."""

from agent.core.gallery import Gallery, project_key


def test_project_key_normalizes_case_and_slashes():
    assert project_key(r"E:\Projetos\Orbita") == "e:/projetos/orbita"
    assert project_key("E:/Projetos/Orbita/") == project_key(r"E:\Projetos\Orbita")


def test_gallery_survives_reload_and_hides_other_projects(tmp_path):
    path = tmp_path / "gallery.json"
    gallery = Gallery(path)
    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    item = gallery.add(path=str(image), prompt="uma árvore sk-abcdefghijklmnopqrstuvwxyz",
                       model="comfyui:sd15.safetensors", backend="comfyui", project=r"E:\ProjetoA",
                       seed=7, size="512x512", device="GPU teste")
    gallery.add(path=str(tmp_path / "b.png"), prompt="outro", model="api", backend="api",
                project=r"E:\ProjetoB")
    again = Gallery(path)
    rows = again.list(r"e:/projetoA")
    assert len(rows) == 1
    assert rows[0]["id"] == item["id"]
    assert rows[0]["exists"] is True
    assert rows[0]["seed"] == 7
    assert "sk-" not in rows[0]["prompt"] and "[removido]" in rows[0]["prompt"]
    assert again.list(r"E:\ProjetoB")[0]["exists"] is False
    assert again.list(r"E:\ProjetoA", query="árvore")[0]["id"] == item["id"]
    assert again.list(r"E:\ProjetoA", query="outro") == []


def test_forget_keeps_the_file_and_other_project_cannot_delete_it(tmp_path):
    gallery = Gallery(tmp_path / "gallery.json")
    image = tmp_path / "foto.png"
    image.write_bytes(b"png")
    item = gallery.add(path=str(image), prompt="foto", model="api", backend="api", project=tmp_path / "a")
    assert "outro projeto" in gallery.forget(item["id"], project=tmp_path / "b")
    assert image.is_file()
    assert gallery.forget(item["id"], project=tmp_path / "a") is None
    assert image.is_file()
    assert gallery.list(tmp_path / "a") == []


def test_delete_file_removes_only_that_entry(tmp_path):
    gallery = Gallery(tmp_path / "gallery.json")
    image = tmp_path / "foto.png"
    image.write_bytes(b"png")
    other = tmp_path / "outra.png"
    other.write_bytes(b"png")
    item = gallery.add(path=str(image), prompt="foto", model="api", backend="api", project="proj")
    kept = gallery.add(path=str(other), prompt="outra", model="api", backend="api", project="proj")
    assert gallery.delete_file(item["id"], project="outro") 
    assert image.is_file() and len(gallery.list("proj")) == 2
    assert gallery.delete_file(item["id"], project="proj") is None
    assert not image.is_file()
    assert other.is_file()
    assert [row["id"] for row in gallery.list("proj")] == [kept["id"]]


def test_missing_file_stays_on_the_list(tmp_path):
    gallery = Gallery(tmp_path / "gallery.json")
    gallery.add(path=str(tmp_path / "sumiu.png"), prompt="sumiu", model="ffmpeg", backend="ffmpeg",
                project="proj", kind="clip")
    rows = gallery.list("proj")
    assert rows[0]["exists"] is False and rows[0]["kind"] == "clip"
    assert gallery.delete_file(rows[0]["id"], project="proj") is None
    assert gallery.list("proj") == []


def test_corrupt_index_does_not_crash(tmp_path):
    path = tmp_path / "gallery.json"
    path.write_text("{", encoding="utf-8")
    assert Gallery(path).list("proj") == []
