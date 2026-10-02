"""Super-resolution with any spandrel-supported model in <engine>\\models\\upscale_models (shared with ComfyUI).

Runs on CUDA (fp16), Apple MPS (fp32) or the CPU; falls back to Lanczos when no model is installed, so callers
never have to care.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from ..common import MODELS, log

PREFERRED = ("4x-UltraSharp", "RealESRGAN_x4plus", "4x_NMKD-Siax_200k")


def _model_path() -> Path | None:
    folder = MODELS / "upscale_models"
    wanted = os.environ.get("REFKIT_UPSCALER")
    files = sorted(folder.glob("*.pth")) + sorted(folder.glob("*.safetensors")) if folder.exists() else []
    for name in ([wanted] if wanted else []) + list(PREFERRED):
        hit = next((f for f in files if f.stem.lower() == str(name).lower()), None)
        if hit:
            return hit
    return files[0] if files else None


@lru_cache(maxsize=1)
def _load(path: str):
    from spandrel import ModelLoader

    from .. import host
    model = ModelLoader().load_from_file(path).eval()
    dev = host.torch_device()
    if dev == "cuda":
        model = model.cuda().half() if model.supports_half else model.cuda()
    elif dev == "mps":
        model = model.to("mps")   # float32: half precision on MPS is not reliable for every architecture
    return model


def upscale(img: Image.Image, min_side: int) -> Image.Image:
    """Upscale until the short side is >= min_side (model passes, then an exact Lanczos resize)."""
    path = _model_path()
    rgba = img.convert("RGBA")
    if path is None:
        log("no upscale model found; using Lanczos")
    else:
        import torch
        model = _load(str(path))
        dev = next(model.model.parameters()).device
        dtype = next(model.model.parameters()).dtype
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        while min(rgb.size) < min_side:
            t = torch.from_numpy(np.array(rgb)).permute(2, 0, 1)[None].to(dev, dtype) / 255
            with torch.inference_mode():
                out = model(t).clamp(0, 1)
            rgb = Image.fromarray((out[0].permute(1, 2, 0).float().cpu().numpy() * 255).round().astype(np.uint8))
            log(f"upscaled x{model.scale} with {path.stem} -> {rgb.size}")
        alpha = alpha.resize(rgb.size, Image.Resampling.LANCZOS)
        rgba = Image.merge("RGBA", (*rgb.split(), alpha))
    scale = min_side / min(rgba.size)
    if scale > 1:
        rgba = rgba.resize((round(rgba.width * scale), round(rgba.height * scale)), Image.Resampling.LANCZOS)
    return rgba
