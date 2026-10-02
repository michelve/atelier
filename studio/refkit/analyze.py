"""refkit analyze: read a reference image and write what a designer would note before starting.

Output (in <ref>.refkit/): analysis.json, sheet.png (contact sheet), edges.png, mask.png, depth.png (when a depth
model is available), palette.png. Claude reads analysis.json + sheet.png to plan the route.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

from .common import (GEMINI_MODEL, OLLAMA, VISION_MODEL, RefkitError, delta_e, log, open_image, out_dir, rgb_to_hex,
                     rgb_to_lab, run, save_json)

VISION_PROMPT = (
    "You are an art director. Describe this reference image for someone who must recreate it. Be concrete and brief. "
    "Cover: subject and composition; style (flat vector / illustration / 3D render / photo / UI); shapes and corner "
    "style (rounded or sharp); materials and lighting; perspective and camera; typography if any; notable small "
    "details that are easy to miss. Answer as JSON with keys: subject, style, composition, shapes, materials, "
    "lighting, camera, typography, details (list), recreate_as (one of: vector, raster, 3d, ui)."
)


def palette(rgb: np.ndarray, k: int = 8, alpha: np.ndarray | None = None) -> list[dict]:
    """k-means in Lab on opaque pixels, near-duplicates merged (dE < 6), sorted by coverage."""
    px = rgb.reshape(-1, 3)
    if alpha is not None:
        px = px[alpha.reshape(-1) > 200]
    if len(px) > 60000:
        px = px[np.random.default_rng(0).choice(len(px), 60000, replace=False)]
    lab = rgb_to_lab(px).astype(np.float32)
    k = min(k, max(1, len(np.unique(px, axis=0))))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.2)
    _, labels, centers = cv2.kmeans(lab, k, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    labels = labels.reshape(-1)
    swatches = []
    for i in range(k):
        members = px[labels == i]
        if not len(members):
            continue
        swatches.append({"rgb": np.median(members, axis=0), "lab": centers[i], "n": len(members)})
    merged: list[dict] = []
    for s in sorted(swatches, key=lambda s: -s["n"]):
        near = next((m for m in merged if delta_e(m["lab"], s["lab"]) < 6), None)
        if near:
            near["n"] += s["n"]
        else:
            merged.append(s)
    total = sum(m["n"] for m in merged)
    return [{"hex": rgb_to_hex(m["rgb"]), "pct": round(100 * m["n"] / total, 1),
             "lab": [round(float(v), 1) for v in m["lab"]]} for m in merged]


def structure(rgb: np.ndarray, alpha: np.ndarray | None) -> tuple[dict, np.ndarray]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 160)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    small = cv2.resize(rgb, (128, 128), interpolation=cv2.INTER_AREA).reshape(-1, 3)
    unique_colors = len(np.unique(small // 8, axis=0))
    # Flat art has few colours and crisp, sparse edges; photos and renders have many of both.
    flatness = float(np.mean(cv2.Laplacian(gray, cv2.CV_64F) == 0))
    corners = np.concatenate([rgb[:8, :8], rgb[:8, -8:], rgb[-8:, :8], rgb[-8:, -8:]]).reshape(-1, 3)
    info = {
        "edge_density": round(float(np.mean(edges > 0)), 4),
        "contours": len(contours),
        "unique_colors_128px": unique_colors,
        "flat_pixel_ratio": round(flatness, 3),
        "background": {"hex": rgb_to_hex(np.median(corners, axis=0)),
                       "uniform": bool(np.std(corners.astype(float), axis=0).max() < 6)},
        "has_alpha": alpha is not None and bool((alpha < 250).any()),
    }
    info["looks_like"] = ("flat" if unique_colors < 180 and flatness > 0.45 else
                          "illustration" if unique_colors < 900 else "photo/render")
    return info, edges


def cutout_mask(src: Path, rgb: np.ndarray, alpha: np.ndarray | None, work: Path) -> np.ndarray:
    """Existing alpha if the image has one, else rembg (u2net / birefnet via its CLI)."""
    if alpha is not None and (alpha < 250).any():
        return alpha
    out = work / "cutout.png"
    try:
        run(["rembg", "i", src, out])
        return np.array(Image.open(out).convert("RGBA"))[..., 3]
    except (Exception, RefkitError) as e:  # rembg is optional for analysis
        log(f"rembg skipped: {e}")
        return np.full(rgb.shape[:2], 255, np.uint8)


def depth_map(rgb: np.ndarray) -> np.ndarray | None:
    """Depth Anything 3 when installed in the refkit venv; None otherwise."""
    try:
        from .models import depth  # lazy: pulls torch + weights
    except ImportError:
        return None
    try:
        return depth.estimate(rgb)
    except (Exception, RefkitError) as e:  # ComfyUI down/failing must not abort the whole analysis
        log(f"depth skipped: {e}")
        return None


def object_on_plain(rgb: np.ndarray, mask: np.ndarray) -> bool:
    """One dominant subject (its largest part >= 85% of the mask, covering 5-75% of the frame) on a plain background:
    the kind of image to3d reconstructs well. A hint only. "Plain" = little texture away from the subject (mean
    gradient magnitude < 8 outside a 15 px band; studio sweeps may still shade light to dark). Calibrated
    2026-10-02: plain studio backdrops 4.5-5, a product on a table with a blurred room 12, a busy workshop 21."""
    fg = mask > 128
    cover = fg.mean()
    if not 0.05 <= cover <= 0.75:
        return False
    n, _, stats, _ = cv2.connectedComponentsWithStats(fg.astype(np.uint8))
    if n < 2 or stats[1:, cv2.CC_STAT_AREA].max() < 0.85 * fg.sum():
        return False
    away = cv2.dilate(fg.astype(np.uint8), np.ones((31, 31), np.uint8)) == 0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    grad = np.hypot(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    return bool(away.any() and float(grad[away].mean()) < 8)


def ocr(src: Path, min_conf: float = 80) -> str:
    """Text in the image, or "". Sparse-text mode finds "words" in foliage and fur, so only confident,
    real-looking words are kept (TSV output carries a per-word confidence). Reliable on screenshots and graphics;
    text inside photos is usually missed, so read it from sheet.png instead."""
    try:
        tsv = run(["tesseract", src, "-", "--psm", "11", "tsv"], check=False).stdout
    except SystemExit:
        return ""
    words = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        word = cols[11].strip()
        if conf >= min_conf and len(word) >= 2 and sum(c.isalnum() for c in word) >= 0.6 * len(word):
            words.append(word)
    return " ".join(words)


def _parse(text: str) -> dict | str:
    try:
        return json.loads(text)
    except ValueError:
        return text


def describe(img: Image.Image, how: str) -> dict | str | None:
    """Optional text description. Default is none: the Claude session reading sheet.png is the art director.

    gemini: own GEMINI_API_KEY (google-genai).  ollama: local qwen3-vl, unloaded afterwards to free the GPU.
    """
    if how == "none":
        return None
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    if how == "gemini":
        try:
            from google import genai
            from google.genai import types

            from .host import secret
            r = genai.Client(api_key=secret("GEMINI_API_KEY") or secret("GOOGLE_API_KEY")).models.generate_content(
                model=GEMINI_MODEL,
                contents=[types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"), VISION_PROMPT],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2))
            return _parse(r.text or "")
        except Exception as e:
            return f"gemini unavailable: {e}"
    try:
        r = requests.post(f"{OLLAMA}/api/generate", timeout=300, json={
            "model": VISION_MODEL, "prompt": VISION_PROMPT, "images": [base64.b64encode(buf.getvalue()).decode()],
            "format": "json", "stream": False, "keep_alive": 0, "options": {"temperature": 0.2}})
        r.raise_for_status()
        return _parse(r.json().get("response", ""))
    except requests.RequestException as e:
        return f"ollama unavailable ({e.__class__.__name__}); start it with `ollama serve`"


def contact_sheet(panels: list[tuple[str, Image.Image]], pal: list[dict], dest: Path) -> None:
    tile = 360
    font = ImageFont.load_default(size=16)
    sheet = Image.new("RGB", (tile * len(panels), tile + 110), "#16161c")
    d = ImageDraw.Draw(sheet)
    for i, (label, im) in enumerate(panels):
        im = im.convert("RGBA")
        im.thumbnail((tile - 16, tile - 40))
        bg = Image.new("RGBA", im.size, "#2a2a33")
        bg.alpha_composite(im)
        sheet.paste(bg.convert("RGB"), (i * tile + (tile - im.width) // 2, 32 + (tile - 40 - im.height) // 2))
        d.text((i * tile + 10, 8), label, fill="#ece8ff", font=font)
    x = 10
    for sw in pal:
        w = max(40, int((tile * len(panels) - 20) * sw["pct"] / 100))
        d.rounded_rectangle((x, tile + 12, x + w - 4, tile + 62), radius=10, fill=sw["hex"])
        if w >= 120:  # narrow swatches get no label rather than overlapping ones
            d.text((x + 4, tile + 70), f"{sw['hex']} {sw['pct']}%", fill="#c9c6dd", font=font)
        x += w
    sheet.save(dest)


def main(args) -> Path:
    src = orig = Path(args.image).resolve()
    work = out_dir(src, args.out)
    raw = Image.open(src)
    img = open_image(src)
    img.load()
    if (raw.getexif() or {}).get(0x0112, 1) != 1:
        # rembg/tesseract read pixels as stored; give them the upright image so masks and text line up.
        src = work / "_upright.png"
        img.save(src)
    rgba = np.array(img.convert("RGBA"))
    alpha = rgba[..., 3] if img.mode in ("RGBA", "LA", "P") else None
    rgb = rgba[..., :3].copy()
    log(f"analyzing {src.name} ({img.width}x{img.height}, {img.mode})")

    pal = palette(rgb, k=args.colors, alpha=alpha)
    info, edges = structure(rgb, alpha)
    Image.fromarray(edges).save(work / "edges.png")
    mask = cutout_mask(src, rgb, alpha, work)
    Image.fromarray(mask).save(work / "mask.png")
    ys, xs = np.nonzero(mask > 128)
    subject = {}
    if len(xs):
        subject = {"bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                   "coverage_pct": round(100 * len(xs) / mask.size, 1)}

    depth = depth_map(rgb) if not args.fast else None
    if depth is not None:
        Image.fromarray(depth).save(work / "depth.png")
    text = ocr(src)
    vision = describe(img, args.describe)

    hint = vision.get("recreate_as") if isinstance(vision, dict) else None
    route = "vector" if info["looks_like"] == "flat" else (hint or "raster")
    candidate_3d = object_on_plain(rgb, mask) if info["looks_like"] != "flat" else False
    result = {
        "source": str(orig), "size": [img.width, img.height], "mode": img.mode,
        "palette": pal,
        "structure": info, "subject": subject, "ocr_text": text, "vision": vision or "not requested (read sheet.png; or --describe gemini|ollama)",
        "suggested_route": route,
        "3d_candidate": candidate_3d,
        "files": {"sheet": "sheet.png", "edges": "edges.png", "mask": "mask.png",
                  "depth": "depth.png" if depth is not None else None},
    }
    save_json(work / "analysis.json", result)
    panels = [("reference", img), ("edges", Image.fromarray(edges)), ("mask", Image.fromarray(mask))]
    if depth is not None:
        panels.append(("depth", Image.fromarray(depth)))
    contact_sheet(panels, pal, work / "sheet.png")
    log(f"route: {route} | palette: {' '.join(s['hex'] for s in pal)}" +
        (" | one object on a plain background: a good `cutout` -> `to3d` input" if candidate_3d else ""))
    log(f"wrote {work / 'analysis.json'} and sheet.png")
    return work
