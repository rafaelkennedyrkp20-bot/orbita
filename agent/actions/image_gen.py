"""
image_gen.py — Geração de imagens pelo modelo de imagem configurado.

Suporta:
    - APIs com /images/generations no formato OpenAI (OpenAI gpt-image, xAI, Gemini/Imagen
      pela camada compatível, servidores locais compatíveis)
    - OpenRouter (modelos de imagem via chat com `modalities: ["image", "text"]`)

Configuração (Configurações → Imagem): settings "image_model" = "provedor:modelo".
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path

import httpx

from agent.actions.builtin_tools import save_artifact_bytes
from agent.core.tools import ToolContext, ToolRegistry, ToolResult, tool


def register_image_tool(registry: ToolRegistry, services) -> None:

    @tool(registry, "generate_image",
          "Generate an image from a detailed visual prompt using the configured image model. "
          "Supports style anchors, negative prompts and shot_id metadata for multi-shot consistency. "
          "Returns the saved file path and shows it to the user.",
          {"prompt": {"type": "string", "description": "Detailed scene/subject description"},
           "size": {"type": "string", "description": "e.g. 1024x1024, 1536x1024, 1024x1536"},
           "style": {"type": "string", "description": "Reusable style anchor (palette, lighting, lens, art direction) for consistency across shots"},
           "negative_prompt": {"type": "string", "description": "Elements to avoid (e.g. 'blurry, watermark, distorted text')"},
           "shot_id": {"type": "string", "description": "Optional storyboard/keyframe ID, e.g. 'shot_01'"},
           "save_to": {"type": "string", "description": "Optional destination path (.png)"}},
          ["prompt"], risk="write", group="imagem")
    def generate_image(args, ctx: ToolContext):
        # Modelo definido pelo usuário; senão, o roteador escolhe o melhor modelo de imagem com acesso.
        ref = services.settings.get("image_model") or services.route_model("imagem") or ""
        if ":" not in ref:
            return ToolResult.error("Nenhum modelo de imagem disponível. Configure uma chave (OpenAI, xAI ou OpenRouter) "
                                    "ou defina o modelo em Configurações → Modelos e economia.")
        provider_name, model = ref.split(":", 1)
        cfg = services.settings.provider(provider_name)
        from agent.core.local_policy import refusal

        blocked = refusal(services.settings, provider_name, cfg, what="a geração de imagem")
        if blocked:
            return ToolResult.error(blocked)
        key = services.settings.api_key(cfg)
        if cfg.get("api_key_env") and not key:
            return ToolResult.error(f"Falta a chave {cfg['api_key_env']} para gerar imagens.")
        base = cfg.get("base_url", "").rstrip("/")
        headers = {"Authorization": f"Bearer {key}"} if key else {}

        full_prompt = args["prompt"].strip()
        if args.get("style"):
            full_prompt = f"[Style Anchor: {args['style'].strip()}]\n{full_prompt}"
        if args.get("negative_prompt"):
            full_prompt = f"{full_prompt}\n[Avoid: {args['negative_prompt'].strip()}]"

        size = args.get("size") or "1024x1024"
        try:
            if "openrouter" in base:
                data = _openrouter_image(base, headers, model, full_prompt)
            else:
                data = _openai_image(base, headers, model, full_prompt, size)
        except Exception as error:
            return ToolResult.error(f"Falha ao gerar imagem com {ref}: {error}")

        path = save_artifact_bytes(data, ".png")
        if args.get("save_to"):
            target = ctx.resolve(args["save_to"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            path = str(target)

        if any(args.get(k) for k in ("style", "negative_prompt", "shot_id")):
            meta_path = Path(path).with_suffix(".meta.json")
            meta = {
                "shot_id": args.get("shot_id") or Path(path).stem,
                "model": ref,
                "size": size,
                "prompt": args["prompt"],
                "style": args.get("style") or "",
                "negative_prompt": args.get("negative_prompt") or "",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            try:
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass

        ctx.emit("preview", {"path": path})
        return ToolResult(text=f"Imagem gerada com {ref}: {path}", images=[path])


def _openai_image(base: str, headers: dict, model: str, prompt: str, size: str) -> bytes:
    response = httpx.post(f"{base}/images/generations", headers=headers, timeout=300,
                          json={"model": model, "prompt": prompt, "size": size, "n": 1})
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
    item = response.json()["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    return httpx.get(item["url"], timeout=120).content


def _openrouter_image(base: str, headers: dict, model: str, prompt: str) -> bytes:
    response = httpx.post(f"{base}/chat/completions", headers=headers, timeout=300, json={
        "model": model, "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": prompt}],
    })
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
    message = response.json()["choices"][0]["message"]
    for image in message.get("images") or []:
        url = image.get("image_url", {}).get("url", "")
        if url.startswith("data:"):
            return base64.b64decode(url.split(",", 1)[1])
        if url:
            return httpx.get(url, timeout=120).content
    raise RuntimeError("O modelo não retornou imagem. Ele suporta geração de imagens?")

