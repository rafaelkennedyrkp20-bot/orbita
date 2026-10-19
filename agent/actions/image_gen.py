"""
image_gen.py — Geração de imagens e montagem curta.

A imagem sai pelo backend escolhido:
    - "api": /images/generations (OpenAI e compatíveis) ou OpenRouter
    - "comfy": ComfyUI já aberto neste computador, só em loopback

O ComfyUI não é instalado daqui, peso nenhum é baixado e uma falha local
não cai numa API paga. A revisão antes de gravar recusa os dois caminhos
antes de qualquer rede ou processo. O clipe curto só junta imagens locais
com o ffmpeg, dentro de um limite pequeno, e também não é um modelo de vídeo.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from agent.actions.builtin_tools import save_artifact_bytes
from agent.actions.short_clip import MAX_IMAGES, ClipError, _number, _remote, _size, render_clip
from agent.core.tools import ToolContext, ToolRegistry, ToolResult, tool

logger = logging.getLogger(__name__)

_STAGED = (
    "A revisão antes de gravar está ligada. A imagem não foi gerada, "
    "porque isso gravaria direto no disco."
)
_STAGED_CLIP = (
    "A revisão antes de gravar está ligada. O clipe não foi montado, "
    "porque isso gravaria direto no disco."
)


def register_image_tool(registry: ToolRegistry, services) -> None:

    @tool(registry, "generate_image",
          "Generate an image from a detailed visual prompt. Backend is the user's setting: "
          "a configured image API, or a ComfyUI server the user already opened on localhost. "
          "Do not install ComfyUI and do not download weights. If ComfyUI fails, stop; "
          "do not switch to a paid API. Supports style, negative prompt, seed and save_to.",
          {"prompt": {"type": "string", "description": "Detailed scene/subject description"},
           "size": {"type": "string", "description": "e.g. 512x512 or 1024x1024. ComfyUI: multiples of 64, up to 1536."},
           "style": {"type": "string", "description": "Reusable style anchor (palette, lighting, lens, art direction)"},
           "negative_prompt": {"type": "string", "description": "Elements to avoid"},
           "shot_id": {"type": "string", "description": "Optional storyboard id, e.g. shot_01"},
           "seed": {"type": "integer", "description": "Optional seed. Repeating it does not promise the same picture."},
           "save_to": {"type": "string", "description": "Optional destination path (.png)"}},
          ["prompt"], risk="write", group="imagem")
    def generate_image(args, ctx: ToolContext):
        if services.settings.get("staged_writes") == "on":
            return ToolResult.error(_STAGED)
        backend = str(services.settings.get("image_backend") or "api").strip().lower()
        if backend == "comfy":
            return _generate_comfy(services, args, ctx)
        return _generate_api(services, args, ctx)

    @tool(registry, "make_short_clip",
          "Assemble a short local slideshow from image files already on disk, using ffmpeg. "
          "Maximum 8 seconds, 1280x720, 12 images and 8 fps. This is not a video model. "
          "Do not download weights or call a cloud video API. If ffmpeg is missing, stop and say so.",
          {"images": {"type": "array", "items": {"type": "string"},
                      "description": "Local image paths already on disk. Maximum 12."},
           "seconds": {"type": "number", "description": "Duration, up to 8 seconds. Default 4."},
           "size": {"type": "string", "description": "Even size up to 1280x720. Default 640x360."},
           "save_to": {"type": "string", "description": "Optional .mp4 path inside the allowed folder"}},
          ["images"], risk="write", group="imagem")
    def make_short_clip(args, ctx: ToolContext):
        return _make_short_clip(services, args, ctx)


def _full_prompt(args) -> str:
    full_prompt = (args.get("prompt") or "").strip()
    if args.get("style"):
        full_prompt = f"[Style Anchor: {args['style'].strip()}]\n{full_prompt}"
    if args.get("negative_prompt"):
        full_prompt = f"{full_prompt}\n[Avoid: {args['negative_prompt'].strip()}]"
    return full_prompt


def _seed(value) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**64 - 1:
        raise ValueError
    return value


def _comfy_size(text: str) -> tuple[int, int]:
    raw = (text or "512x512").lower().replace(" ", "")
    if "x" not in raw:
        raise ValueError
    width_text, height_text = raw.split("x", 1)
    width, height = int(width_text), int(height_text)
    if width % 64 or height % 64 or not 256 <= width <= 1536 or not 256 <= height <= 1536:
        raise ValueError
    if width * height > 1536 * 1024:
        raise ValueError
    return width, height


def _device_label(report: dict) -> str:
    names = []
    for device in report.get("devices") or []:
        if isinstance(device, dict) and isinstance(device.get("name"), str):
            names.append(device["name"][:80])
    return ", ".join(names)[:200]


def _conversation_id(ctx: ToolContext) -> str:
    session = getattr(ctx, "session", None)
    brain = getattr(session, "brain", None)
    return str(getattr(brain, "conversation_id", "") or "")


def _remember(path: str, args, ctx: ToolContext, *, model: str, backend: str, seed, size: str,
              device: str = "", kind: str = "image") -> None:
    from agent.core.gallery import get_gallery

    try:
        get_gallery().add(
            path=path, prompt=args.get("prompt") or "", model=model, backend=backend,
            project=str(ctx.workspace), kind=kind, seed=seed, size=size, device=device,
            conversation_id=_conversation_id(ctx),
        )
    except OSError:
        logger.warning("Não foi possível atualizar a galeria")


def _write_sidecar(path: str, args, *, model: str, size: str, seed) -> None:
    if not any(args.get(key) for key in ("style", "negative_prompt", "shot_id")):
        return
    meta_path = Path(path).with_suffix(".meta.json")
    meta = {
        "shot_id": args.get("shot_id") or Path(path).stem,
        "model": model,
        "size": size,
        "seed": seed,
        "prompt": args.get("prompt") or "",
        "style": args.get("style") or "",
        "negative_prompt": args.get("negative_prompt") or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _save_png(data: bytes, args, ctx: ToolContext) -> str | ToolResult:
    path = save_artifact_bytes(data, ".png")
    if args.get("save_to"):
        target = ctx.resolve(args["save_to"])
        blocked = ctx.reject_write(target)
        if blocked:
            return ToolResult.error(blocked)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        path = str(target)
    return path


def _generate_api(services, args, ctx: ToolContext):
    ref = services.settings.get("image_model") or services.route_model("imagem") or ""
    if ":" not in ref:
        return ToolResult.error(
            "Nenhum modelo de imagem disponível. Configure uma chave (OpenAI, xAI ou OpenRouter) "
            "ou defina o modelo em Configurações → Modelos."
        )
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
    full_prompt = _full_prompt(args)
    size = args.get("size") or "1024x1024"
    try:
        seed = _seed(args.get("seed"))
    except ValueError:
        return ToolResult.error("Semente inválida.")
    try:
        if "openrouter" in base:
            data = _openrouter_image(base, headers, model, full_prompt)
        else:
            data = _openai_image(base, headers, model, full_prompt, size)
    except Exception as error:
        return ToolResult.error(f"Falha ao gerar imagem com {ref}: {error}")
    saved = _save_png(data, args, ctx)
    if isinstance(saved, ToolResult):
        return saved
    _write_sidecar(saved, args, model=ref, size=size, seed=seed)
    _remember(saved, args, ctx, model=ref, backend="api", seed=seed, size=size)
    ctx.emit("preview", {"path": saved})
    return ToolResult(text=f"Imagem gerada com {ref}: {saved}", images=[saved])


def _generate_comfy(services, args, ctx: ToolContext):
    """Usa só o ComfyUI local. Não há segundo caminho para uma API paga."""
    from agent.actions.comfyui import ComfyCancelled, ComfyClient, ComfyError

    if ctx.cancel is not None and ctx.cancel.is_set():
        return ToolResult.error("Geração cancelada.")
    url = (services.settings.get("comfyui_url") or "http://127.0.0.1:8188").strip()
    checkpoint = (services.settings.get("comfyui_checkpoint") or "").strip()
    if not checkpoint:
        return ToolResult.error(
            "Escolha um checkpoint já instalado no ComfyUI. O Órbita não baixa pesos nem instala o serviço."
        )
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return ToolResult.error("Falta o texto da imagem.")
    try:
        width, height = _comfy_size(args.get("size") or "512x512")
        seed = _seed(args.get("seed"))
    except ValueError:
        return ToolResult.error(
            "Tamanho ou semente inválidos para o ComfyUI. Use múltiplos de 64, entre 256 e 1536, "
            "até 1,5 megapixel (ex.: 512x512). Nada foi enfileirado."
        )
    try:
        client = ComfyClient(url)
    except ComfyError as error:
        return ToolResult.error(str(error))
    report = client.health()
    status = report.get("status")
    if status == "unreachable":
        detail = report.get("detail") or "sem resposta"
        return ToolResult.error(
            f"O ComfyUI não respondeu ({detail}). Abra o serviço você mesmo; "
            "o Órbita não instala nem encerra um ComfyUI já aberto."
        )
    if status == "incompatible":
        missing = ", ".join(report.get("missing_nodes") or []) or "nós padrão"
        return ToolResult.error(f"Faltam nós padrão no ComfyUI ({missing}). Nada foi enfileirado e nenhum modelo foi baixado.")
    if status != "ready" or checkpoint not in (report.get("checkpoints") or []):
        return ToolResult.error("Esse checkpoint não está instalado no ComfyUI. Nada foi baixado.")
    if ctx.cancel is not None and ctx.cancel.is_set():
        return ToolResult.error("Geração cancelada.")

    def resource_slot():
        from agent.core.inference_queue import INFERENCE_QUEUE
        return INFERENCE_QUEUE.slot("local-gpu", cancel=ctx.cancel)

    def on_progress(info):
        ctx.emit("status", {"text": f"ComfyUI: {info.get('state') or 'trabalhando'}"})

    try:
        data, meta = client.generate_image(
            _full_prompt(args), checkpoint, seed=seed, width=width, height=height,
            negative_prompt=(args.get("negative_prompt") or "")[:8000], steps=20,
            cancel=ctx.cancel, on_progress=on_progress, resource_slot=resource_slot,
        )
    except ComfyCancelled as error:
        return ToolResult.error(str(error))
    except ComfyError as error:
        return ToolResult.error(str(error))
    saved = _save_png(data, args, ctx)
    if isinstance(saved, ToolResult):
        return saved
    size = f"{width}x{height}"
    model = f"comfyui:{checkpoint}"
    _write_sidecar(saved, args, model=model, size=size, seed=seed)
    _remember(saved, args, ctx, model=model, backend="comfyui", seed=seed, size=size,
              device=_device_label(report))
    ctx.emit("preview", {"path": saved})
    return ToolResult(
        text=(f"Imagem gerada no ComfyUI ({checkpoint}), semente {seed}: {saved}. "
              "O mesmo pedido pode não repetir o desenho. Nenhum peso foi baixado."),
        images=[saved],
    )


def _local_frames(args, ctx: ToolContext) -> list[Path]:
    images = args.get("images")
    if isinstance(images, str) or not isinstance(images, list) or not images:
        raise ClipError(f"Informe uma lista com até {MAX_IMAGES} imagens que já estão no disco.")
    if len(images) > MAX_IMAGES:
        raise ClipError(f"São {len(images)} imagens. O limite é {MAX_IMAGES}. Nada foi executado.")
    frames = []
    for item in images:
        if not isinstance(item, str) or _remote(item):
            raise ClipError("O clipe só usa arquivos locais. Endereço remoto não entra e nada foi baixado.")
        path = ctx.resolve(item)
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
            raise ClipError(f"Imagem local inválida ou ausente: {item}")
        frames.append(path)
    return frames


def _make_short_clip(services, args, ctx: ToolContext):
    if services.settings.get("staged_writes") == "on":
        return ToolResult.error(_STAGED_CLIP)
    if ctx.cancel is not None and ctx.cancel.is_set():
        return ToolResult.error("Montagem cancelada antes de começar. Nenhum processo foi aberto.")
    try:
        seconds = _number(args.get("seconds", 4), minimum=0.5, maximum=8, label="Duração")
        width, height = _size(args.get("size") or "640x360")
        frames = _local_frames(args, ctx)
    except ClipError as error:
        return ToolResult.error(str(error))
    if args.get("save_to"):
        target = ctx.resolve(args["save_to"])
        if target.suffix.lower() != ".mp4":
            return ToolResult.error("O clipe curto é um .mp4.")
    else:
        from agent.actions.builtin_tools import ARTIFACTS_DIR
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        target = ARTIFACTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S_%f}.mp4"
    blocked = ctx.reject_write(target)
    if blocked:
        return ToolResult.error(blocked)
    try:
        render_clip(frames, target, seconds=seconds, width=width, height=height, cancel=ctx.cancel)
    except ClipError as error:
        return ToolResult.error(str(error))
    size = f"{width}x{height}"
    _remember(str(target), args, ctx, model="ffmpeg", backend="ffmpeg", seed=None, size=size, kind="clip")
    ctx.emit("preview", {"path": str(target), "kind": "file"})
    return ToolResult(text=(
        f"Clipe curto montado com o ffmpeg ({seconds:g}s, {size}): {target}. "
        "Isto é uma montagem das imagens locais, não um modelo de vídeo. Nenhum peso foi baixado."
    ))


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


def comfy_status_message(report: dict) -> str:
    """Texto da consulta de saúde, sem enfileirar geração."""
    status = report.get("status")
    if status == "ready":
        names = ", ".join(str(name) for name in (report.get("checkpoints") or [])[:12])
        return "ComfyUI pronto. Checkpoints já instalados: " + (names or "nenhum") + ". Nada foi baixado."
    if status == "no_models":
        return "O ComfyUI respondeu, mas não há checkpoint instalado. O Órbita não baixa pesos."
    if status == "incompatible":
        missing = ", ".join(report.get("missing_nodes") or []) or "nós padrão"
        return f"Faltam nós padrão ({missing}). Nada foi enfileirado."
    if status == "unreachable":
        return "O ComfyUI não respondeu. Abra o serviço você mesmo; o Órbita não instala nem encerra esse programa."
    return "Não foi possível ler o ComfyUI."
