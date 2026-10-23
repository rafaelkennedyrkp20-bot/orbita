"""Ferramentas 3D comuns a qualquer provedor e à equipe, com permissões normais."""

from __future__ import annotations

import json

from agent.core.studio3d import get_studio3d
from agent.core.tools import ToolContext, ToolResult, tool


def register_studio3d_tools(registry, studio=None) -> None:
    def current():
        return studio or get_studio3d()

    def lease(ctx, engine):
        from agent.core.mcp_hub import SERVER_LEASES

        owner = ctx.session or ctx
        if not SERVER_LEASES.acquire(f"studio3d-{engine}", owner, cancel=ctx.cancel, timeout=30):
            raise InterruptedError(f"{engine} ocupado por outro agente ou operação cancelada. Aguarde e consulte o estado.")
        return owner

    def engine_operation(ctx, operation, engine="unreal"):
        from agent.core.mcp_hub import SERVER_LEASES

        owner = lease(ctx, engine)
        try:
            return json.dumps(operation(), ensure_ascii=False)
        finally:
            if ctx.session is None:
                SERVER_LEASES.release_all(owner)

    @tool(registry, "studio3d_status",
          "Inspect 3D integrations (Unreal Remote Control, Unity, Blender, Godot, OpenSCAD). "
          "refresh=true checks local Unreal/Unity protocols without running scripts or changing a scene. "
          "If Blender/Godot/OpenSCAD is missing, request toolbox_install with permission; do not claim installed. "
          "Unity/Unreal require the official distributors and licenses. Unity project bridge: unity_install_bridge. "
          "Available API or executable does not mean a scene/render was validated.",
          {"refresh": {"type": "boolean"}}, group="shell")
    def studio3d_status(args, ctx: ToolContext):
        status = current().probe(cancel=ctx.cancel) if args.get("refresh") else current().status()
        return json.dumps(status, ensure_ascii=False)

    @tool(registry, "studio3d_configure",
          "Configure a local 3D connection after identifying the installed app/project. Saves preferences only; "
          "does not download, open apps or run code. Unreal uses official Remote Control on loopback; "
          "Blender path empty keeps autodetection. For Unity first use unity_install_bridge in an existing project. "
          "An editor reserved by another session cannot be redirected. Then call studio3d_status refresh=true.",
          {"unreal": {"type": "object", "properties": {"enabled": {"type": "boolean"}, "url": {"type": "string"}},
                      "additionalProperties": False},
           "blender": {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": False},
           "unity": {"type": "object", "properties": {"enabled": {"type": "boolean"}, "project_path": {"type": "string"}},
                     "additionalProperties": False}}, risk="write", group="shell")
    def studio3d_configure(args, ctx: ToolContext):
        if not args:
            return ToolResult.error("Informe ao menos uma integração para configurar.")
        if ctx.cancel is not None and ctx.cancel.is_set():
            return ToolResult.error("Configuração 3D cancelada.")
        status = current().configure(args)
        ctx.emit("studio3d", {"status": status})
        return json.dumps(status, ensure_ascii=False)

    @tool(registry, "unreal_describe",
          "Describe properties and Blueprint-callable functions of an object in the connected Unreal Editor. "
          "Read only; requires enabled local Remote Control API and a known UObject path.",
          {"object_path": {"type": "string"}}, ["object_path"], group="shell")
    def unreal_describe(args, ctx: ToolContext):
        return engine_operation(ctx, lambda: current().unreal_describe(args["object_path"], cancel=ctx.cancel))

    @tool(registry, "unreal_call",
          "Call a Blueprint-callable function in the connected Unreal Editor via official Remote Control API. "
          "Executes code and can change the scene/project. Uses generateTransaction=true; not all functions are undoable. "
          "Inspect the object first. Never blindly repeat after timeout: the operation may already have executed.",
          {"object_path": {"type": "string"}, "function_name": {"type": "string"},
           "parameters": {"type": "object", "description": "Exact C++/Blueprint function parameter names and values"}},
          ["object_path", "function_name"], risk="exec", group="shell")
    def unreal_call(args, ctx: ToolContext):
        return engine_operation(ctx, lambda: current().unreal_call(args["object_path"], args["function_name"],
                                                                 args.get("parameters", {}), cancel=ctx.cancel))

    @tool(registry, "blender_run_script",
          "Run an existing project Python script with bpy in installed Blender, background/factory startup. "
          "Uses the project as working directory; no shell and no automatic installation. "
          "Create a preview image and inspect it, then verify exported GLB/FBX/STL. Non-zero Python exit is an error.",
          {"script_path": {"type": "string", "description": "Existing .py file inside current project"},
           "timeout": {"type": "number", "minimum": 1, "maximum": 600}}, ["script_path"], risk="exec", group="shell")
    def blender_run_script(args, ctx: ToolContext):
        result = current().blender_run_script(args["script_path"], ctx.workspace, args.get("timeout", 120), cancel=ctx.cancel)
        text = json.dumps(result, ensure_ascii=False)
        if result["returncode"] != 0 or result.get("timed_out") or result.get("cancelled"):
            return ToolResult.error(text)
        return text

    @tool(registry, "unity_install_bridge",
          "Install the bundled native editor bridge in an existing Unity project. This writes Assets/Editor/OrbitaBridge.cs "
          "and a local token in Library/Orbita, and enables the local Unity connection. Unity will compile and run this editor script "
          "when the project is opened/refreshed, so this requires execution permission. Does not download or open Unity; "
          "preserves an existing different OrbitaBridge.cs. If Unity itself is missing, ask to install it from the official Unity Hub.",
          {"project_path": {"type": "string", "description": "Absolute root containing Assets and ProjectSettings/ProjectVersion.txt"}},
          ["project_path"], risk="exec", group="shell")
    def unity_install_bridge(args, ctx: ToolContext):
        root = current()._unity_project(args["project_path"])
        for relative in ("Assets/Editor/OrbitaBridge.cs", "Library/Orbita/bridge-token.txt"):
            blocked = ctx.reject_write(current()._unity_target(root, relative))
            if blocked:
                return ToolResult.error(blocked)
        if ctx.cancel is not None and ctx.cancel.is_set():
            return ToolResult.error("Instalação da ponte Unity cancelada.")
        result = current().unity_install_bridge(str(root))
        ctx.emit("studio3d", {"status": current().status()})
        return json.dumps(result, ensure_ascii=False)

    @tool(registry, "unity_scene",
          "Read the active scene hierarchy in the Unity project connected through the native OrbitaUnity/1 editor bridge. "
          "Returns at most 1000 transforms with instance ids and positions. No code execution or scene changes.", group="shell")
    def unity_scene(args, ctx: ToolContext):
        return engine_operation(ctx, lambda: current().unity_scene(cancel=ctx.cancel), engine="unity")

    @tool(registry, "unity_create_primitive",
          "Create a primitive in the active Unity scene through the native editor bridge, with Undo support. "
          "Does not save the scene or execute arbitrary C#. Use unity_scene first; do not repeat after timeout without checking.",
          {"primitive": {"type": "string", "enum": ["cube", "sphere", "plane", "capsule", "cylinder", "quad"]},
           "name": {"type": "string", "maxLength": 120},
           "position": {"type": "object", "properties": {k: {"type": "number"} for k in ("x", "y", "z")},
                        "required": ["x", "y", "z"]}}, ["primitive", "name"], risk="exec", group="shell")
    def unity_create_primitive(args, ctx: ToolContext):
        return engine_operation(ctx, lambda: current().unity_create_primitive(args["primitive"], args["name"],
                                args.get("position"), cancel=ctx.cancel), engine="unity")
