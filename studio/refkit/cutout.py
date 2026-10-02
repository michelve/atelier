"""refkit cutout: subject -> clean RGBA with decontaminated edges.

  no prompt      BiRefNet background removal (ComfyUI core)
  --prompt TEXT  SAM 3.1 text-prompted segmentation, e.g. --prompt "column" or "cube, sphere:2" (all instances,
                 up to --max each; 'concept:N' overrides)
  --engine qwen  Qwen-Image 2.1 background removal (slower, ~15 s; best on hair, fur, glass, soft edges)
  --engine rembg local rembg CLI (no ComfyUI needed)

Edges: the mask is feathered slightly, then colours in the semi-transparent band are replaced by the nearest solid
subject colour (removes the light/dark halo left by the old background).
"""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import comfy, gpu, meta
from .common import RefkitError, log, open_image, out_dir, run, safe_name


def sam3_prompt(prompt: str, max_det: int) -> str:
    """SAM 3 text syntax: comma-separated concepts, each 'concept:N' for up to N instances (default 1)."""
    parts = [p.strip() for p in prompt.split(",") if p.strip()]
    return ", ".join(p if re.search(r":\s*\d+\s*$", p) else f"{p}:{max_det}" for p in parts)


def mask_workflow(image: str, prompt: str | None, threshold: float, max_det: int = 50) -> dict:
    if prompt:
        wf = comfy.load_workflow("utility_image_segment_sam3.api")
        for n in wf.values():
            if n["class_type"] == "LoadImage":
                n["inputs"]["image"] = image
            elif n["class_type"] == "CLIPTextEncode":
                n["inputs"]["text"] = sam3_prompt(prompt, max_det)
            elif n["class_type"] == "SAM3_Detect":
                n["inputs"]["threshold"] = threshold
        det = next(k for k, n in wf.items() if n["class_type"] == "SAM3_Detect")
        for k in [k for k, n in wf.items() if n["class_type"] in ("MaskPreview", "PreviewImage", "JoinImageWithAlpha")]:
            del wf[k]
    else:
        wf = {
            "1": {"class_type": "LoadImage", "inputs": {"image": image}},
            "2": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": "birefnet.safetensors"}},
            "3": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["2", 0], "image": ["1", 0]}},
        }
        det = "3"
    wf["m2i"] = {"class_type": "MaskToImage", "inputs": {"mask": [det, 0]}}
    wf["save"] = {"class_type": "SaveImage", "inputs": {"images": ["m2i", 0], "filename_prefix": "refkit/mask"}}
    return wf


def decontaminate(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Push solid subject colours outward into the soft edge band (inpaint from the inside).
    Only the subject's bounding box (+margin) is processed; the empty background beyond it is masked anyway."""
    band = ((alpha > 0) & (alpha < 250)).astype(np.uint8) * 255
    if not band.any():
        return rgb
    ys, xs = np.nonzero(alpha)
    m = 16
    y0, y1 = max(ys.min() - m, 0), min(ys.max() + m + 1, alpha.shape[0])
    x0, x1 = max(xs.min() - m, 0), min(xs.max() + m + 1, alpha.shape[1])
    crop_rgb, crop_a, crop_band = rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1], band[y0:y1, x0:x1]
    outside = (crop_a == 0).astype(np.uint8) * 255
    fill = cv2.inpaint(cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR), cv2.bitwise_or(crop_band, outside), 3, cv2.INPAINT_TELEA)
    fill = cv2.cvtColor(fill, cv2.COLOR_BGR2RGB)
    out = rgb.copy()
    region = out[y0:y1, x0:x1]
    region[crop_band > 0] = fill[crop_band > 0]
    return out


def qwen_mask(src: Path, work: Path) -> np.ndarray:
    """Qwen-Image 2.1 background removal: the model repaints the image as RGBA; only its alpha is used, on the
    original pixels (resolution 0 keeps the input size, so the mask lines up exactly)."""
    wf = comfy.load_workflow("image_qwen_image_2_1_background_removal.api")
    comfy.patch(wf, "LoadImage", "image", comfy.upload(src))
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", "refkit/qwen-cut", expect=None)
    for k in [k for k, n in wf.items() if n["class_type"] == "ImageCompare"]:
        del wf[k]
    items = [i for i in comfy.queue(wf) if i.get("type") == "output"]
    if not items:
        raise RefkitError("refkit: Qwen background removal returned nothing")
    p = comfy.fetch(items[0], work)
    rgba = open_image(p).convert("RGBA")
    p.unlink()
    return np.array(rgba)[..., 3]


def get_mask(src: Path, prompt: str | None, engine: str, threshold: float, work: Path, max_det: int = 50) -> np.ndarray:
    if engine == "rembg":
        tmp = work / "rembg.png"
        run(["rembg", "i", src, tmp])
        return np.array(Image.open(tmp).convert("RGBA"))[..., 3]
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    if engine == "qwen":
        if prompt:
            raise RefkitError("refkit: --engine qwen removes the background of the whole image; use SAM (--prompt) to pick objects")
        return qwen_mask(src, work)
    items = [i for i in comfy.queue(mask_workflow(comfy.upload(src), prompt, threshold, max_det)) if i.get("type") == "output"]
    if not items:
        raise RefkitError("refkit: segmentation returned nothing (try a different --prompt or lower --threshold)")
    m = comfy.fetch(items[0], work)
    mask = np.array(Image.open(m).convert("L"))
    m.unlink()
    return mask


def cut(src: Path, work: Path, prompt: str | None = None, engine: str = "comfy", threshold: float = 0.5,
        feather: float = 0.8, max_det: int = 50) -> Path:
    img = np.array(open_image(src).convert("RGB"))   # EXIF-rotated like ComfyUI's LoadImage sees it
    mask = get_mask(src, prompt, engine, threshold, work, max_det)
    if mask.shape != img.shape[:2]:
        # A different aspect means a rotated mask (EXIF mismatch), which a resize would silently misalign.
        if abs(mask.shape[0] / mask.shape[1] - img.shape[0] / img.shape[1]) > 0.02:
            raise RefkitError(f"refkit: mask {mask.shape} does not match image {img.shape[:2]} (orientation mismatch)")
        mask = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
    if feather > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), feather)
    mask[mask < 8] = 0
    rgb = decontaminate(img, mask)
    out = work / (f"cutout-{safe_name(prompt, 30)}.png" if prompt else "cutout.png")
    Image.fromarray(np.dstack([rgb, mask])).save(out, optimize=True)
    cov = float(np.mean(mask > 128))
    log(f"{out} (subject covers {cov:.0%} of the frame)")
    return out


def main(args) -> Path:
    src = Path(args.image).resolve()
    out = cut(src, out_dir(src, args.out), args.prompt, args.engine, args.threshold, args.feather, args.max)
    model = "sam3" if args.prompt else {"qwen": "qwen-rgba", "rembg": None}.get(args.engine, "birefnet")
    meta.record(out, "cutout", model=model, prompt=args.prompt, engine=args.engine, inputs=[src])
    return out
