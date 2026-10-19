"""Distribuição não inclui dados locais e mantém recursos fora da área gravável."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build_package as build

ROOT = Path(__file__).resolve().parents[1]


def test_resources_are_allowlisted_and_reject_private_files(tmp_path):
    names = ["agent/ui/web/index.html", "agent/ui/web/app.js", "skills/demo/SKILL.md",
             "skills/demo/helper.py", "data/settings.json", ".env", "models/a.gguf",
             "venv/a.py", "skills/demo/.env", "skills/demo/data/private.json",
             "skills/demo/secret.txt", "skills/demo/weights.bin", "agent/ui/web/key.pem"]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("conteúdo", encoding="utf-8")
    resources = build.resources(tmp_path, names)
    assert {path.relative_to(tmp_path).as_posix() for path, _ in resources} == set(names[:4])


def test_resource_symlink_cannot_escape_project(tmp_path):
    outside = tmp_path / "chave.md"
    outside.write_text("segredo", encoding="utf-8")
    target = tmp_path / "repo" / "skills" / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("criação de symlink não autorizada neste Windows")
    with pytest.raises(ValueError, match="recurso"):
        build.resources(tmp_path / "repo", ["skills/demo/SKILL.md"])


def test_resource_directory_link_cannot_include_private_data(tmp_path):
    private = tmp_path / "data"
    private.mkdir()
    (private / "SKILL.md").write_text("chave privada", encoding="utf-8")
    link = tmp_path / "skills" / "demo"
    link.parent.mkdir()
    try:
        link.symlink_to(private, target_is_directory=True)
    except OSError:
        pytest.skip("criação de symlink não autorizada neste Windows")
    with pytest.raises(ValueError, match="recurso"):
        build.resources(tmp_path, ["skills/demo/SKILL.md"])


def test_manifest_records_components_hashes_without_machine_paths():
    manifest = build.manifest(ROOT)
    assert manifest["schema"] == 1
    assert manifest["components"]["desktop"]["included"]
    assert not manifest["components"]["local_voice"]["included"]
    assert not manifest["components"]["ollama"]["included"]
    paths = {row["path"] for row in manifest["resources"]}
    assert {"agent/ui/web/index.html", "agent/ui/web/logo.svg", "skills/spec-plan-tdd/SKILL.md",
            "agent/core/local_models.json"} <= paths
    assert all(len(row["sha256"]) == 64 for row in manifest["resources"])
    assert str(ROOT) not in json.dumps(manifest)


@pytest.mark.parametrize("frozen", [False, True])
def test_config_honors_isolated_home_without_loading_bundled_env(tmp_path, frozen):
    script = ("import sys, json; sys.frozen = " + repr(frozen) + "; "
              "from agent.core import config; "
              "print(json.dumps([str(config.PROJECT_ROOT), str(config.RESOURCE_ROOT), str(config.DATA_DIR)]))")
    env = {**os.environ, "ORBITA_HOME": str(tmp_path)}
    output = subprocess.check_output([sys.executable, "-c", script], cwd=ROOT, env=env, text=True)
    home, resource, data = json.loads(output)
    assert Path(home) == tmp_path
    assert Path(resource) == ROOT
    assert Path(data) == tmp_path / "data"
    assert not list(tmp_path.iterdir())  # importar configuração não cria nem altera preferências


def test_config_frozen_default_uses_user_directory(tmp_path):
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path), "XDG_DATA_HOME": str(tmp_path)}
    env.pop("ORBITA_HOME", None)
    script = "import sys; sys.frozen=True; from agent.core.config import PROJECT_ROOT; print(PROJECT_ROOT)"
    actual = Path(subprocess.check_output([sys.executable, "-c", script], cwd=ROOT, env=env, text=True).strip())
    assert actual == tmp_path / ("Orbita" if os.name == "nt" else "orbita")


def test_frozen_config_loads_only_user_env(tmp_path):
    bundle = tmp_path / "bundle"
    module = bundle / "agent" / "core" / "config.py"
    module.parent.mkdir(parents=True)
    module.write_bytes((ROOT / "agent/core/config.py").read_bytes())
    (bundle / ".env").write_text("ORBITA_PACKAGE_SENTINEL=from-bundle\n", encoding="utf-8")
    user = tmp_path / "user"
    user.mkdir()
    (user / ".env").write_text("ORBITA_PACKAGE_SENTINEL=from-user\n", encoding="utf-8")
    env = {**os.environ, "ORBITA_HOME": str(user)}
    env.pop("ORBITA_PACKAGE_SENTINEL", None)
    script = ("import os, runpy, sys; sys.frozen=True; runpy.run_path(sys.argv[1]); "
              "print(os.environ.get('ORBITA_PACKAGE_SENTINEL'))")
    actual = subprocess.check_output([sys.executable, "-c", script, str(module)], env=env, text=True).strip()
    assert actual == "from-user"
    assert (user / ".env").read_text(encoding="utf-8") == "ORBITA_PACKAGE_SENTINEL=from-user\n"


def test_build_command_separates_optional_engines(tmp_path):
    command = build.command(ROOT, tmp_path, tmp_path / "manifest.json")
    assert "--onedir" in command and "--windowed" in command
    assert "--collect-submodules" in command
    assert "faster_whisper" in command and "torch" in command
    assert not any("data/settings" in arg or ".env" in arg for arg in command)
