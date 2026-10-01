"""Rank generated images by human preference + prompt match (PickScore, CLIP-H, local on the GPU).

Used by `refkit gen -n N --pick`: the scores pre-sort the candidates and write contact.png (best first, scores
printed on each tile); the art director (Claude) still looks at the top ones and makes the final call. PickScore
is the Windows-friendly member of the preference-scorer family (HPSv3 needs a 7B VLM that fights ComfyUI for VRAM).
Weights (~4 GB) download once into <engine>\\models\\scoring.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import gpu
from .common import MODELS, log

CACHE = MODELS / "scoring"
PROCESSOR = "laion/CLIP-ViT-H-14-laion2B-s32B-b79K"
MODEL = "yuvalkirstain/PickScore_v1"


def pickscore(prompt: str, images: list[Path]) -> list[float]:
    import torch
    from transformers import AutoModel, AutoProcessor

    gpu.free_vram()   # CLIP-H in fp16 needs ~2 GB; ask ComfyUI to drop its models first
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    proc = AutoProcessor.from_pretrained(PROCESSOR, cache_dir=CACHE)
    model = AutoModel.from_pretrained(MODEL, cache_dir=CACHE, dtype=torch.float16 if dev == "cuda" else None).eval().to(dev)
    with torch.no_grad():
        ims = proc(images=[Image.open(p).convert("RGB") for p in images], return_tensors="pt").to(dev)
        txt = proc(text=[prompt], padding=True, truncation=True, max_length=77, return_tensors="pt").to(dev)
        ie = model.get_image_features(**ims)
        te = model.get_text_features(**txt)
        # transformers 5 returns an output object; pooler_output is the projected embedding
        ie, te = (getattr(x, "pooler_output", x) for x in (ie, te))
        ie = ie / ie.norm(dim=-1, keepdim=True)
        te = te / te.norm(dim=-1, keepdim=True)
        scores = (model.logit_scale.exp() * (te @ ie.T))[0].float().cpu().tolist()
    del model
    if dev == "cuda":
        torch.cuda.empty_cache()
    return [round(s, 3) for s in scores]


def contact(ranked: list[tuple[Path, float]], dest: Path, tile: int = 480) -> Path:
    cols = 2 if len(ranked) == 4 else min(4, len(ranked))
    rows = (len(ranked) + cols - 1) // cols
    w0, h0 = Image.open(ranked[0][0]).size
    th = round(tile * h0 / w0)   # tiles follow the images' aspect ratio
    sheet = Image.new("RGB", (cols * tile, rows * (th + 28)), "#16161c")
    d = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=16)
    for i, (p, s) in enumerate(ranked):
        im = Image.open(p).convert("RGB")
        im.thumbnail((tile - 8, th - 8))
        x, y = (i % cols) * tile, (i // cols) * (th + 28)
        sheet.paste(im, (x + (tile - im.width) // 2, y + 4 + (th - 8 - im.height) // 2))
        d.text((x + 8, y + th + 4), f"#{i + 1}  {s:.2f}  {p.stem}", fill="#ece8ff" if i else "#b9f5c0", font=font)
    out = dest / "contact.png"
    sheet.save(out)
    return out


def rank(prompt: str, images: list[Path], dest: Path) -> list[tuple[Path, float]]:
    scores = pickscore(prompt, images)
    ranked = sorted(zip(images, scores), key=lambda t: -t[1])
    sheet = contact(ranked, dest)
    log(f"ranked {len(ranked)} by PickScore: " + ", ".join(f"{p.stem}={s:.2f}" for p, s in ranked))
    log(f"contact sheet (best first): {sheet} — look at the top 2-3 before choosing")
    return ranked
