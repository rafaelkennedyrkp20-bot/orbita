"""Entrada congelada; subprocessos internos não devem iniciar outra janela do aplicativo."""

import json
import multiprocessing
import runpy
import sys


def main() -> int:
    multiprocessing.freeze_support()
    if sys.argv[1:2] == ["-c"]:
        raise SystemExit("Este executável não é um interpretador Python. Instale Python para executar código.")
    if sys.argv[1:2] == ["-m"]:
        if len(sys.argv) < 3 or sys.argv[2] not in {"agent.actions.web_check", "agent.core.grok_bridge"}:
            raise SystemExit("Este executável não é um interpretador Python. Instale Python para executar código.")
        module = sys.argv[2]
        sys.argv = [module, *sys.argv[3:]]
        runpy.run_module(module, run_name="__main__")
        return 0
    if sys.argv[1:] == ["--package-check"]:
        from agent.core.config import DATA_DIR, PROJECT_ROOT, RESOURCE_ROOT
        try:
            from agent.core.local_catalog import load_catalog
            from agent.ui.brand import WEB_DIR
            from PyQt6.QtWebEngineWidgets import QWebEngineView

            assert QWebEngineView is not None
            assert load_catalog()
            required = [WEB_DIR / "index.html", WEB_DIR / "logo.svg", RESOURCE_ROOT / "components.json"]
            if not all(path.is_file() for path in required):
                raise RuntimeError("Pacote incompleto: recursos desktop ausentes.")
            result = {"ok": True, "home": str(PROJECT_ROOT), "data": str(DATA_DIR), "web": str(WEB_DIR)}
        except Exception as error:
            result = {"ok": False, "error": str(error)}
        # --windowed não tem stdout no Windows; resultado também permite smoke test por arquivo.
        report = PROJECT_ROOT / "package-check.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result), encoding="utf-8")
        if sys.stdout is not None:
            print(json.dumps(result))
        return 0 if result["ok"] else 1
    runpy.run_module("agent.main", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
