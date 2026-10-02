"""refkit fix: repair one region of an image (hands, a face, garbled text, a logo) and leave the rest untouched.

  refkit fix img.png --region "hand" --prompt "Fix the hand: five natural fingers, relaxed pose."
  refkit fix img.png --region "sign text" --prompt "The sign reads \\"OPEN\\" in clean white capitals."
  refkit fix img.png --mask mask.png --prompt "…"            your own mask (white = the part to redraw)
  --engine qwen    (default) Qwen-Image 2.1 edit of the region with the instruction (best for anatomy and text)
  --engine zimage  Z-Image img2img of the region at --denoise (0.3-0.45): re-detail without changing the content;
                   --prompt then describes the region instead of instructing

SAM 3.1 finds every instance of --region (each is fixed on its own). Each crop gets context (box +40%) and is
enlarged to ~1 MP so the model has pixels to work with, redrawn, shrunk back and blended in through a feathered
mask, so only the region changes. Output: <img>-fix-<seed>.png next to the input (or --out) with a sidecar.
"""
from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import comfy, gen, gpu, meta
from .common import RefkitError, log, open_image, out_dir

CONTEXT = 0.4      # crop = region box grown by this fraction on each side
WORK_PX = 1024     # crops are redrawn at about this long side
MIN_AREA = 0.0005  # ignore SAM specks smaller than this share of the image


def regions(mask: np.ndarray) -> list[tuple[np.ndarray, tuple[int, int, int, int]]]:
    """Connected parts of a mask -> (part mask, crop box with context)."""
    h, w = mask.shape
    n, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 127).astype(np.uint8))
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < MIN_AREA * h * w:
            continue
        side = max(bw, bh) * (1 + 2 * CONTEXT)
        cx, cy = x + bw / 2, y + bh / 2
        x0, y0 = max(0, int(cx - side / 2)), max(0, int(cy - side / 2))
        x1, y1 = min(w, int(cx + side / 2)), min(h, int(cy + side / 2))
        out.append(((labels == i).astype(np.uint8) * 255, (x0, y0, x1, y1)))
    return out


def redraw(crop: Image.Image, prompt: str, engine: str, denoise: float, seed: int, work: Path) -> Image.Image:
    scale = WORK_PX / max(crop.size)
    size = (max(64, round(crop.width * scale / 32) * 32), max(64, round(crop.height * scale / 32) * 32))
    big = crop.resize(size, Image.LANCZOS)
    src = work / f"fix-in-{seed}.png"
    big.save(src)
    if engine == "qwen":
        # Consistency LoRA: the redrawn crop stays on the original's pixels, so the blend lines up.
        wf = gen.build("qwen-edit", f"{prompt} Keep everything else exactly the same.", [comfy.upload(src)], None,
                       seed, "refkit/fix", consistent=True)
    else:
        wf = gen.build("z-image", prompt, [], f"{size[0]}x{size[1]}", seed, "refkit/fix")
        latent = next(k for k, n in wf.items() if n["class_type"] == "EmptySD3LatentImage")
        vae = next(n["inputs"]["vae"] for n in wf.values() if n["class_type"] == "VAEDecode")
        wf["fix_load"] = {"class_type": "LoadImage", "inputs": {"image": comfy.upload(src)}}
        wf[latent] = {"class_type": "VAEEncode", "inputs": {"pixels": ["fix_load", 0], "vae": vae}}
        comfy.patch(wf, "KSampler", "denoise", denoise)
    items = [i for i in comfy.queue(wf) if i.get("type") == "output"]
    if not items:
        raise RefkitError("refkit: the fix pass produced no image")
    p = comfy.fetch(items[0], work)
    out = open_image(p).convert("RGB").resize(crop.size, Image.LANCZOS)
    p.unlink()
    src.unlink(missing_ok=True)
    return out


def blend(base: np.ndarray, new: np.ndarray, part: np.ndarray) -> np.ndarray:
    """Feathered paste: the region (grown a little) fully replaced, fading out over a soft edge."""
    ys, xs = np.nonzero(part)
    size = max(np.ptp(ys), np.ptp(xs)) + 1 if len(ys) else 64
    grow = max(3, int(size * 0.08))
    m = cv2.dilate(part, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    m = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), max(1.5, grow / 2))[..., None]
    return (new * m + base * (1 - m)).round().astype(np.uint8)


def main(args) -> dict:
    src = Path(args.image).resolve()
    dest = out_dir(src, args.out) if args.out else src.parent
    img = open_image(src)
    alpha = np.array(img.getchannel("A")) if img.mode == "RGBA" else None
    rgb = np.array(img.convert("RGB"))
    seed = args.seed if args.seed is not None else random.randrange(2**31)
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    if args.mask:
        mask = np.array(open_image(args.mask).convert("L").resize(img.size))
    elif args.region:
        from .cutout import get_mask
        mask = get_mask(src, args.region, "comfy", args.threshold, dest)
    else:
        raise RefkitError("refkit: fix needs --region TEXT (SAM finds it) or --mask FILE")
    parts = regions(mask)
    if not parts:
        raise RefkitError(f"refkit: nothing found for --region {args.region!r} (lower --threshold or pass --mask)")
    out = rgb.copy()
    for i, (part, (x0, y0, x1, y1)) in enumerate(parts):
        crop = Image.fromarray(out[y0:y1, x0:x1])
        new = np.array(redraw(crop, args.prompt, args.engine, args.denoise, seed + i, dest))
        out[y0:y1, x0:x1] = blend(out[y0:y1, x0:x1], new, part[y0:y1, x0:x1])
        log(f"region {i + 1}/{len(parts)} at {x0},{y0} {x1 - x0}x{y1 - y0} redrawn ({args.engine})")
    final = dest / f"{src.stem}-fix-{seed}.png"
    Image.fromarray(np.dstack([out, alpha]) if alpha is not None else out).save(final)
    meta.record(final, "fix", model="qwen-edit" if args.engine == "qwen" else "z-image", prompt=args.prompt,
                region=args.region, seed=seed, engine=args.engine, denoise=args.denoise if args.engine == "zimage" else None,
                regions=len(parts), inputs=[src] + ([Path(args.mask)] if args.mask else []))
    log(f"{final} ({len(parts)} region(s) fixed) — compare with the input at 100%")
    return {"outputs": [str(final)], "regions": len(parts), "seed": seed}

