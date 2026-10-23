"""Execução nativa de Godot/OpenSCAD com a caixa de ferramentas e o runner 3D."""

from __future__ import annotations

import json
from pathlib import Path

from agent.core.studio3d import Studio3D
from agent.core.toolbox import get_toolbox
from agent.core.tools import ToolContext, ToolResult, tool


def register_creative_app_tools(registry, box=None) -> None:
    @tool(registry, "creative_app_run",
          "Run installed Godot or OpenSCAD directly, without a shell or automatic download. "
          "Godot receives --headless --path <current project>; pass native flags such as --import, --script or --quit. "
          "OpenSCAD receives native flags: use -o model.stl scene.scad or -o preview.png --viewall scene.scad. "
          "The full executable path is resolved automatically. Use arguments as separate strings, without shell quoting. "
          "These apps/scripts can change files and are not sandboxed. Inspect preview/export files after execution. "
          "If missing, offer toolbox_install with the app id and the normal permission flow.",
          {"app": {"type": "string", "enum": ["godot", "openscad"]},
           "arguments": {"type": "array", "items": {"type": "string"}, "maxItems": 128},
           "timeout": {"type": "number", "minimum": 1, "maximum": 600}},
          ["app", "arguments"], risk="exec", group="shell")
    def creative_app_run(args, ctx: ToolContext):
        app = args["app"]
        arguments = args["arguments"]
        timeout = args.get("timeout", 120)
        if not isinstance(app, str) or app not in ("godot", "openscad"):
            return ToolResult.error("app deve ser godot ou openscad.")
        if (not isinstance(arguments, list) or len(arguments) > 128 or
                any(not isinstance(value, str) or "\0" in value or len(value) > 4096 for value in arguments)):
            return ToolResult.error("arguments deve conter até 128 textos sem NUL, com até 4096 caracteres cada.")
        if sum(len(value) + 1 for value in arguments) > 16000:
            return ToolResult.error("Os argumentos passam do limite de 16000 caracteres.")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
            return ToolResult.error("timeout deve estar entre 1 e 600 segundos.")
        if ctx.cancel is not None and ctx.cancel.is_set():
            return ToolResult.error("Execução cancelada antes de iniciar.")
        workspace = Path(ctx.workspace).resolve()
        if not workspace.is_dir():
            return ToolResult.error("A pasta do projeto não existe.")
        toolbox = box if box is not None else get_toolbox()
        executable = toolbox.find_executable(app) or toolbox.system_executable(app)
        if not executable or not Path(executable).is_absolute() or not Path(executable).is_file():
            return ToolResult.error(f"{app} não encontrado. Ofereça instalar com toolbox_install id=\"{app}\" "
                                    "ou indique a instalação pela caixa de ferramentas em Conexões.")
        command = [str(executable)]
        if app == "godot":
            command.extend(["--headless", "--path", str(workspace)])
        command.extend(arguments)
        result = Studio3D._run_process(command, workspace, timeout, ctx.cancel)
        text = json.dumps({"app": app, "executable": str(executable), **result}, ensure_ascii=False)
        if result["returncode"] != 0 or result.get("timed_out") or result.get("cancelled"):
            return ToolResult.error(text)
        return text
