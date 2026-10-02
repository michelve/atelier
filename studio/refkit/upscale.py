"""refkit upscale: detail-restoring upscale with SeedVR2 (ComfyUI core), optional light refine pass first.

  refkit upscale img.png                     2x, SeedVR2 3B int8 (~10-30 s)
  refkit upscale img.png --long 4096         to a 4096 px long side
  refkit upscale img.png --model 7b          7B for hero images (slower, sharper)
  refkit upscale img.png --refine "prompt"   first re-draw at <= ~2 MP with Z-Image (denoise 0.3) to clean
                                             generator artifacts, then upscale (hires-fix, core nodes only)
Alpha is kept (the workflow joins the input's alpha before resizing). Output: <img>.refkit/ or --out.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from . import comfy, gen, gpu, meta
from .common import RefkitError, log, open_image, out_dir

WORKFLOW = {"3b": "utility_seedvr2_3b_int8_upscale_image", "7b": "utility_seedvr2_7b_int8_upscale_image"}


def refine(src: Path, dest: Path, prompt: str, denoise: float, seed: int) -> Path:
    """Z-Image img2img: the text->image workflow with the empty latent swapped for the encoded input."""
    im = open_image(src).convert("RGB")
    scale = min(1.0, math.sqrt(2_000_000 / (im.width * im.height)))   # Z-Image is happiest around 1-2 MP
    w, h = (max(16, round(v * scale / 16) * 16) for v in im.size)
    small = dest / f"{src.stem}-refine-in.png"
    im.resize((w, h), 1).save(small)   # 1 = LANCZOS
    wf = gen.build("z-image", prompt, [], f"{w}x{h}", seed, "refkit/refine")
    latent = next(k for k, n in wf.items() if n["class_type"] == "EmptySD3LatentImage")
    vae = next(n["inputs"]["vae"] for n in wf.values() if n["class_type"] == "VAEDecode")
    wf["refine_load"] = {"class_type": "LoadImage", "inputs": {"image": comfy.upload(small)}}
    wf[latent] = {"class_type": "VAEEncode", "inputs": {"pixels": ["refine_load", 0], "vae": vae}}
    comfy.patch(wf, "KSampler", "denoise", denoise)
    items = [i for i in comfy.queue(wf) if i.get("type") == "output"]
    if not items:
        raise RefkitError("refkit: refine pass produced no image")
    out = comfy.fetch(items[0], dest).replace(dest / f"{src.stem}-refined.png")
    small.unlink(missing_ok=True)
    log(f"refined at {w}x{h} (denoise {denoise}) -> {out.name}")
    return out


def upscale(src: Path, dest: Path, factor: float, model: str, seed: int) -> Path:
    wf = comfy.load_workflow(WORKFLOW[model] + ".api")
    comfy.patch(wf, "LoadImage", "image", comfy.upload(src))
    comfy.patch(wf, "ResizeImageMaskNode", "resize_type.multiplier", round(factor, 3))
    comfy.patch(wf, "KSampler", "seed", seed)
    comfy.patch(wf, "SeedVR2PostProcessing", "color_correction_method", "lab")   # templates ship "none" (tints)
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", "refkit/upscale", expect=None)
    for k in [k for k, n in wf.items() if n["class_type"] == "ImageCompare"]:
        del wf[k]
    items = [i for i in comfy.queue(wf, timeout=3600) if i.get("type") == "output"]
    if not items:
        raise RefkitError("refkit: SeedVR2 produced no image")
    return comfy.fetch(items[0], dest)


def main(args) -> dict:
    src = Path(args.image).resolve()
    dest = out_dir(src, args.out)
    w, h = open_image(src).size
    seed = args.seed if args.seed is not None else random.randrange(2**31)
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    cur = src
    if args.refine:
        cur = refine(src, dest, args.refine, args.denoise, seed)
    cw, ch = open_image(cur).size
    target_long = args.long or max(w, h) * args.scale
    factor = target_long / max(cw, ch)
    if factor <= 1.0:
        raise RefkitError(f"refkit: already {max(cw, ch)} px on the long side (target {target_long}); nothing to upscale")
    if max(cw, ch) * factor > 8192:
        raise RefkitError("refkit: target above 8192 px; upscale in two steps or lower --long")
    out = upscale(cur, dest, factor, args.model, seed)
    final = out.replace(dest / f"{src.stem}-x{factor:.2g}-seedvr2{args.model}.png")
    fw, fh = open_image(final).size
    meta.record(final, "upscale", model="seedvr2", variant=args.model, seed=seed, size=f"{fw}x{fh}",
                refine=args.refine, denoise=args.denoise if args.refine else None, inputs=[src])
    log(f"{final} ({w}x{h} -> {fw}x{fh}, SeedVR2 {args.model})")
    return {"outputs": [str(final)], "seed": seed, "size": [fw, fh]}
