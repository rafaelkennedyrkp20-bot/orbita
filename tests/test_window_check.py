"""Linux sem as bibliotecas do QtWebEngine: o Órbita diz o que instalar em vez de fechar com traceback."""

import pytest

from agent.main import LINUX_QT_APT, window_problem


def test_missing_linux_library_names_the_package_and_the_command():
    # Erro real num Ubuntu 24.04 enxuto (WSL), ao importar PyQt6.QtWebEngineCore.
    error = ImportError("libxkbfile.so.1: cannot open shared object file: No such file or directory")
    text = window_problem(error)
    assert "libxkbfile.so.1" in text and "libxkbfile1" in text
    assert LINUX_QT_APT in text
    for package in ("libxkbfile1", "libxcb-icccm4", "libxcb-keysyms1", "libxcb-shape0", "libpcsclite1"):
        assert package in LINUX_QT_APT


def test_unknown_import_error_points_to_requirements():
    text = window_problem(ImportError("No module named 'PyQt6'"))
    assert "pip install -r requirements.txt" in text and "apt" not in text


def test_window_problem_is_empty_when_the_window_loads():
    pytest.importorskip("PyQt6.QtWebEngineWidgets")
    assert window_problem() == ""
