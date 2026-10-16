"""Portabilidade: o mesmo Órbita no Windows e no Linux (shell, atalhos do menu, prompt do sistema)."""

import os
import sys

import pytest

from agent.actions import builtin_tools, open_apps
from agent.core import agent_loop

posix_only = pytest.mark.skipif(os.name == "nt", reason="só no Linux/macOS")


def test_shell_runs_a_portable_command(brain, tmp_path):
    from agent.core.tools import ToolContext

    tool = brain.registry.get("run_shell")
    result = tool.run({"command": "echo orbita-ok", "cwd": str(tmp_path)}, ToolContext(workspace=tmp_path))
    assert not result.is_error and "orbita-ok" in result.text


@posix_only
def test_shell_is_bash_and_timeout_kills_children(brain, tmp_path):
    from agent.core.tools import ToolContext

    assert builtin_tools._shell_argv("ls")[0].endswith(("bash", "sh"))
    assert "bash" in builtin_tools.SHELL_HELP and "PowerShell" not in builtin_tools.SHELL_HELP
    tool = brain.registry.get("run_shell")
    result = tool.run({"command": "sleep 30 & sleep 30", "timeout": 5}, ToolContext(workspace=tmp_path))
    assert result.is_error and "tempo esgotado" in result.text


def test_timeout_does_not_hang_when_a_child_keeps_the_output_open(brain, tmp_path):
    """Caso real: o ajudante subiu um servidor; o servidor (neto) segurava a saída e o agente travava 30+ min."""
    import time

    from agent.core.tools import ToolContext

    py = sys.executable.replace("\\", "/")
    spawn = (f"import subprocess, sys, time; subprocess.Popen([r'{py}', '-c', 'import time; time.sleep(120)']); "
             "time.sleep(120)")
    command = f"& '{py}' -c \"{spawn}\"" if os.name == "nt" else f"'{py}' -c \"{spawn}\""
    started = time.monotonic()
    result = brain.registry.get("run_shell").run({"command": command, "timeout": 5}, ToolContext(workspace=tmp_path))
    assert result.is_error and "tempo esgotado" in result.text and "background=true" in result.text
    assert time.monotonic() - started < 25


def test_servers_go_to_background_automatically(brain, tmp_path):
    from agent.actions import builtin_tools as bt
    from agent.core.tools import ToolContext

    py = sys.executable
    command = (f"& '{py}' -m http.server 0 --bind 127.0.0.1" if os.name == "nt"
               else f"'{py}' -m http.server 0 --bind 127.0.0.1")
    result = brain.registry.get("run_shell").run({"command": command}, ToolContext(workspace=tmp_path))
    assert not result.is_error and "segundo plano" in result.text and "PID" in result.text
    proc = bt._BACKGROUND[-1]
    assert proc.poll() is None
    bt._kill_tree(proc)
    proc.wait(timeout=10)


def test_system_prompt_names_the_real_os_and_shell():
    expected = "Windows" if os.name == "nt" else ("macOS" if sys.platform == "darwin" else "Linux")
    assert f"computador {expected} do usuário" in agent_loop.BASE_PROMPT
    assert f"terminal ({'PowerShell' if os.name == 'nt' else 'bash'})" in agent_loop.BASE_PROMPT


def test_desktop_entry_lookup(tmp_path):
    apps = tmp_path / "applications"
    apps.mkdir()
    (apps / "org.gnome.Calculator.desktop").write_text(
        "[Desktop Entry]\nName=Calculadora\nName[en]=Calculator\nExec=gnome-calculator %U\n"
        "[Desktop Action new]\nExec=outra-coisa\n", encoding="utf-8")
    (apps / "escondido.desktop").write_text("[Desktop Entry]\nName=Calculadora Secreta\nExec=x\nNoDisplay=true\n",
                                            encoding="utf-8")
    assert open_apps.find_desktop_entry("calculadora", [str(apps)]) == ("Calculadora", ["gnome-calculator"])
    assert open_apps.find_desktop_entry("calculator", [str(apps)]) == ("Calculadora", ["gnome-calculator"])
    assert open_apps.find_desktop_entry("photoshop", [str(apps)]) is None


@posix_only
def test_system_info_without_windows_drive():
    from agent.actions.system_control import SystemControl

    info = SystemControl().get_system_info()
    assert "Erro" not in info.split("\n", 1)[0]
