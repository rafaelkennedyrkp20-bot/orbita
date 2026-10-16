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

import httpx

from agent.actions.builtin_tools import save_artifact_bytes
from agent.core.tools import ToolContext, ToolRegistry, ToolResult, tool


def register_image_tool(registry: ToolRegistry, services) -> None:

    @tool(registry, "generate_image",
          "Generate an image from a detailed visual prompt using the configured image model. "
          "Returns the saved file path and shows it to the user.",
          {"prompt": {"type": "string"},
           "size": {"type": "string", "description": "e.g. 1024x1024, 1536x1024, 1024x1536"},
           "save_to": {"type": "string", "description": "Optional destination path (.png)"}},
          ["prompt"], risk="write", group="imagem")
    def generate_image(args, ctx: ToolContext):
        # Modelo definido pelo usuário; senão, o roteador escolhe o melhor modelo de imagem com acesso.
        ref = services.settings.get("image_model") or services.route_model("imagem") or ""
        if ":" not in ref:
            return ToolResult.error("Nenhum modelo de imagem disponível. Configure uma chave (OpenAI ou OpenRouter) "
                                    "ou defina o modelo em Configurações → Modelos e economia.")
        provider_name, model = ref.split(":", 1)
        cfg = services.settings.provider(provider_name)
        key = services.settings.api_key(cfg)
        if cfg.get("api_key_env") and not key:
            return ToolResult.error(f"Falta a chave {cfg['api_key_env']} para gerar imagens.")
        base = cfg.get("base_url", "").rstrip("/")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        if "openrouter" in base:
            data = _openrouter_image(base, headers, model, args["prompt"])
        else:
            data = _openai_image(base, headers, model, args["prompt"], args.get("size") or "1024x1024")
        path = save_artifact_bytes(data, ".png")
        if args.get("save_to"):
            target = ctx.resolve(args["save_to"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            path = str(target)
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

