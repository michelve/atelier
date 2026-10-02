"""Rank generated images so the art director (Claude) looks at the best ones first (`refkit gen -n N --pick`).

  text -> image   HPSv3++ (Qwen3-VL-8B reward model, NF4, ~9 GB VRAM): human preference + prompt match. It runs in
                  its own environment (<engine>\\tools\\hpsv3-4bit, pinned transformers) as a subprocess.
  edits (-i)      EditScore (LoRA on the shared local Qwen3-VL-8B, vlm.py): scores the result against the *source*
                  image and the instruction (prompt following x consistency x quality), not the prompt alone.
  fallback        PickScore (CLIP-H, ~2 GB) when the above aren't installed.
Every scorer writes contact.png (best first, scores on the tiles); the scores pre-sort, Claude decides.
ComfyUI is asked to free its VRAM first: the card holds one engine at a time.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import gpu, host
from .common import MODELS, STUDIO_ROOT, log, run

CACHE = MODELS / "scoring"
PROCESSOR = "laion/CLIP-ViT-H-14-laion2B-s32B-b79K"
MODEL = "yuvalkirstain/PickScore_v1"
HPS_TOOL = STUDIO_ROOT / "tools" / "hpsv3-4bit"
HPS_WEIGHTS = CACHE / "HPSv3-PlusPlus-bnb-NF4"


def hpsv3pp(prompt: str, images: list[Path]) -> list[float] | None:
    """HPSv3++ scores, or None when the tool or its weights aren't installed (caller falls back)."""
    exe = host.venv_bin(HPS_TOOL / ".venv", "hpsv3pp-score")
    if not (exe.exists() and (HPS_WEIGHTS / "config.json").exists()):
        return None
    gpu.free_vram()
    with tempfile.TemporaryDirectory() as tmp:
        rec, out = Path(tmp) / "records.json", Path(tmp) / "scores.json"
        rec.write_text(json.dumps([{"id": str(i), "image": str(p), "prompt": prompt} for i, p in enumerate(images)]),
                       encoding="utf-8")
        # The weights are a local folder. The first run fetches the scorer's verified upstream source files once
        # (SHA-256 checked) into upstream-cache; after that it runs offline. (--local-files-only would also block
        # that one-time fetch.)
        env = {**os.environ, "PYTHONNOUSERSITE": "1"}
        res = run([exe, "--input", rec, "--output", out, "--model", HPS_WEIGHTS,
                   "--source-dir", HPS_TOOL / "upstream-cache"], check=False, env=env)
        if res.returncode or not out.exists():
            log(f"HPSv3++ failed, using PickScore: {(res.stderr or res.stdout)[-300:]}")
            return None
        rows = {r["id"]: r["score"] for r in json.loads(out.read_text(encoding="utf-8"))["scores"]}
    return [round(rows[str(i)], 3) for i in range(len(images))]


def editscore(instruction: str, source: Path, images: list[Path]) -> list[float] | None:
    """EditScore overall (0-10) per edit result, or None when the local VLM/LoRA isn't installed."""
    from . import vlm
    if not ((vlm.BASE / "config.json").exists() and (vlm.EDITSCORE_LORA / "adapter_config.json").exists()):
        return None
    try:
        ev = vlm.editscore()
        scores = [round(float(ev.evaluate([str(source), str(p)], instruction)["overall"]), 3) for p in images]
    except (SystemExit, Exception) as e:   # not installed, import/driver error, OOM, unparsable verdict
        log(f"EditScore unavailable, using PickScore: {str(e)[:160]}")
        return None
    finally:
        vlm.unload()
    return scores


def pickscore(prompt: str, images: list[Path]) -> list[float]:
    import torch
    from transformers import AutoModel, AutoProcessor

    gpu.free_vram()   # CLIP-H in fp16 needs ~2 GB; ask ComfyUI to drop its models first
    dev = host.torch_device()
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
    host.empty_cache(dev)
    return [round(s, 3) for s in scores]


def contact(ranked: list[tuple[Path, float]], dest: Path, tile: int = 480, name: str = "contact.png") -> Path:
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
    out = dest / name
    sheet.save(out)
    return out


def rank(prompt: str, images: list[Path], dest: Path, source: Path | None = None,
         name: str = "contact.png") -> list[tuple[Path, float]]:
    """Edits (source given) -> EditScore; text->image -> HPSv3++; either missing -> PickScore."""
    scores, scorer = (editscore(prompt, source, images), "EditScore") if source else (hpsv3pp(prompt, images), "HPSv3++")
    if scores is None:
        scores, scorer = pickscore(prompt, images), "PickScore"
    ranked = sorted(zip(images, scores), key=lambda t: -t[1])
    sheet = contact(ranked, dest, name=name)
    log(f"ranked {len(ranked)} by {scorer}: " + ", ".join(f"{p.stem}={s:.2f}" for p, s in ranked))
    log(f"contact sheet (best first): {sheet} — look at the top 2-3 before choosing")
    return ranked
