"""refkit vectorize: raster reference -> clean, optimised SVG, tuned against the reference.

Pipeline: (upscale small inputs) -> edge-preserving denoise -> snap to palette -> trace -> svgo -> resvg re-render ->
score (SSIM + colour error, penalised by path count). Tries a small grid of tracer settings and keeps the best.
Colour art goes through vtracer; --mono uses potrace (smoother single-colour curves, e.g. logos, icons, line art).
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import cv2
import numpy as np
import vtracer
from PIL import Image
from skimage.metrics import structural_similarity

from .common import delta_e, hex_to_rgb, log, open_image, out_dir, rgb_to_hex, rgb_to_lab, run, save_json

# (filter_speckle, color_precision, layer_difference, corner_threshold, path_precision)
PRESETS = {
    "clean": (8, 5, 24, 60, 2),
    "balanced": (4, 6, 16, 60, 3),
    "detailed": (2, 7, 10, 45, 3),
    "flat": (10, 4, 32, 90, 2),
}


def prepare(img: Image.Image, palette_hex: list[str] | None, colors: int, min_side: int) -> tuple[Image.Image, np.ndarray]:
    rgba = img.convert("RGBA")
    if min(rgba.size) < min_side:
        from .models import upscale  # Real-ESRGAN class model when present, Lanczos otherwise
        rgba = upscale.upscale(rgba, min_side)
    arr = np.array(rgba)
    rgb = cv2.bilateralFilter(arr[..., :3], 7, 40, 7)
    # Snap every pixel to the nearest palette colour so the tracer sees flat regions, not gradients of noise.
    if palette_hex:
        pal = np.array([hex_to_rgb(h) for h in palette_hex], dtype=np.float64)
    else:
        from .analyze import palette
        pal = np.array([hex_to_rgb(s["hex"]) for s in palette(rgb, k=colors, alpha=arr[..., 3])], dtype=np.float64)
    idx = nearest(rgb, pal)
    # Majority (mode) filter on palette *labels* removes single-pixel islands without inventing colours
    # (a per-channel median mixes channels of different swatches where 3+ regions meet).
    best_n = np.zeros(idx.shape, np.uint8)
    smooth = idx.copy()
    for k in range(len(pal)):
        n = cv2.boxFilter((idx == k).astype(np.uint8), -1, (3, 3), normalize=False)
        better = n > best_n
        smooth[better], best_n[better] = k, n[better]
    snapped = pal[smooth].astype(np.uint8)
    return Image.fromarray(np.dstack([snapped, arr[..., 3]]), "RGBA"), pal


def nearest(rgb: np.ndarray, pal: np.ndarray) -> np.ndarray:
    """Index of the nearest palette colour (Lab) per pixel; one palette entry at a time to keep memory flat."""
    lab = rgb_to_lab(rgb.reshape(-1, 3)).astype(np.float32)
    pal_lab = rgb_to_lab(pal).astype(np.float32)
    best = np.full(len(lab), np.inf, np.float32)
    idx = np.zeros(len(lab), np.uint8)
    for k, c in enumerate(pal_lab):
        d = np.linalg.norm(lab - c, axis=1)
        closer = d < best
        best[closer], idx[closer] = d[closer], k
    return idx.reshape(rgb.shape[:2])


def snap_fills(svg: Path, pal: np.ndarray) -> int:
    """Replace every traced fill with the exact nearest palette hex (vtracer's layer merging averages colours)."""
    text = svg.read_text(encoding="utf-8")
    found = sorted(set(re.findall(r'fill="(#[0-9a-fA-F]{6})"', text)))
    if not found:
        return 0
    got = np.array([hex_to_rgb(h) for h in found], dtype=np.float64)
    idx = nearest(got.reshape(1, -1, 3).astype(np.uint8), pal).reshape(-1)
    mapping = {h: rgb_to_hex(pal[i]) for h, i in zip(found, idx)}
    text = re.sub(r'fill="(#[0-9a-fA-F]{6})"', lambda m: f'fill="{mapping[m.group(1)]}"', text)
    svg.write_text(text, encoding="utf-8")
    return sum(1 for h, v in mapping.items() if h.lower() != v.lower())


def trace_color(src: Path, dst: Path, preset: tuple) -> None:
    speckle, cprec, layer, corner, pprec = preset
    vtracer.convert_image_to_svg_py(
        str(src), str(dst), colormode="color", hierarchical="stacked", mode="spline",
        filter_speckle=speckle, color_precision=cprec, layer_difference=layer, corner_threshold=corner,
        length_threshold=4.0, max_iterations=10, splice_threshold=45, path_precision=pprec)


def trace_mono(prepared: Image.Image, dst: Path, work: Path, color: str, turd: int) -> None:
    arr = np.array(prepared.convert("RGBA"))
    gray = cv2.cvtColor(arr[..., :3], cv2.COLOR_RGB2GRAY)
    opaque = arr[..., 3] > 128
    if (~opaque).mean() > 0.05:
        ink = opaque   # logo on transparency: whatever is opaque is the shape, whatever its tone
    else:
        border = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
        # Ink is whatever contrasts with the background: dark on light, or light on dark.
        ink = (gray >= 128) if np.median(border) < 128 else (gray < 128)
    pbm = work / "mono.pbm"
    Image.fromarray(np.where(ink, 0, 255).astype(np.uint8)).convert("1").save(pbm)
    run(["potrace", pbm, "-s", "-o", dst, "--turdsize", str(turd), "--alphamax", "1.0",
         "--opttolerance", "0.2", "--color", color])


def optimise(svg: Path) -> None:
    run(["svgo", "--multipass", "--quiet", "-i", svg, "-o", svg])
    # vtracer/potrace write width/height only; a viewBox is what lets the SVG scale responsively.
    text = svg.read_text(encoding="utf-8")
    if "viewBox" not in text:
        m = re.search(r'<svg[^>]*?\bwidth="([\d.]+)(?:px|pt)?"[^>]*?\bheight="([\d.]+)(?:px|pt)?"', text)
        if m:
            text = text.replace("<svg", f'<svg viewBox="0 0 {m.group(1)} {m.group(2)}"', 1)
            svg.write_text(text, encoding="utf-8")


def render(svg: Path, png: Path, size: tuple[int, int]) -> Image.Image:
    run(["resvg", svg, png, "-w", str(size[0]), "-h", str(size[1])])
    return Image.open(png).convert("RGBA")


def score(ref: Image.Image, out: Image.Image, out_bg: tuple | None = None) -> dict:
    """SSIM on luminance and mean colour error over opaque pixels, both composited on the same grey.
    out_bg: backdrop for the SVG render when it has no background layer (mono traces of an opaque reference)."""
    def flat(im, colour=(128, 128, 128)):
        bg = Image.new("RGBA", im.size, (*colour, 255))
        bg.alpha_composite(im.resize(ref.size, Image.Resampling.LANCZOS))
        return np.array(bg.convert("RGB"))
    a, b = flat(ref.convert("RGBA")), flat(out, out_bg or (128, 128, 128))
    ssim = structural_similarity(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), cv2.cvtColor(b, cv2.COLOR_RGB2GRAY), data_range=255)  # pyright: ignore[reportArgumentType]
    de = float(np.mean(delta_e(rgb_to_lab(a), rgb_to_lab(b))))
    return {"ssim": round(float(ssim), 4), "mean_delta_e": round(de, 2)}  # pyright: ignore[reportArgumentType]


def svg_stats(svg: Path) -> dict:
    text = svg.read_text(encoding="utf-8")
    paths = len(re.findall(r"<path\b", text))
    nodes = len(re.findall(r"[MLHVCSQTAZmlhvcsqtaz]", " ".join(re.findall(r'\bd="([^"]*)"', text))))
    return {"paths": paths, "nodes": nodes, "kb": round(svg.stat().st_size / 1024, 1)}


def main(args) -> Path:
    src = Path(args.image).resolve()
    work = out_dir(src, args.out)
    ref = open_image(src).convert("RGBA")
    pal = None
    if args.palette:
        pal = [h.strip() for h in args.palette.split(",")]
    elif (work / "analysis.json").exists() and not args.colors_given:
        pal = [s["hex"] for s in json.loads((work / "analysis.json").read_text(encoding="utf-8"))["palette"]]
        log(f"using palette from analysis.json: {' '.join(pal)}")

    prepared, pal_rgb = prepare(ref, pal, args.colors, args.min_side)
    r = np.array(ref)
    border = np.concatenate([r[0], r[-1], r[:, 0], r[:, -1]])
    # Opaque reference: a mono SVG is only the ink, so score it on the reference's own background colour.
    mono_bg = tuple(int(v) for v in np.median(border[:, :3], axis=0)) if (border[:, 3] > 250).all() else None
    prep_png = work / "vector-prepared.png"
    prepared.save(prep_png)

    candidates = []
    presets = [args.preset] if args.preset else list(PRESETS)
    for name in (["mono"] if args.mono else presets):
        svg = work / f"vector-{name}.svg"
        if args.mono:
            trace_mono(prepared, svg, work, args.mono_color, 4)
        else:
            trace_color(prep_png, svg, PRESETS[name])
            snap_fills(svg, pal_rgb)
        optimise(svg)
        stats = svg_stats(svg)
        s = score(ref, render(svg, work / f"vector-{name}.png", ref.size), mono_bg if args.mono else None)
        # Reward fidelity, lightly punish complexity: a clean 300-path SVG beats a noisy 3000-path one at similar SSIM.
        s["rank"] = round(s["ssim"] - s["mean_delta_e"] / 200 - np.log10(max(stats["paths"], 1)) / 50, 4)
        candidates.append({"preset": name, "svg": svg.name, **stats, **s})
        log(f"{name:9s} ssim {s['ssim']:.3f}  dE {s['mean_delta_e']:5.2f}  paths {stats['paths']:5d}  {stats['kb']} KB")

    best = max(candidates, key=lambda c: c["rank"])
    final = work / "vector.svg"
    shutil.copyfile(work / best["svg"], final)
    render(final, work / "vector-preview.png", ref.size)
    report = {"best": best, "candidates": candidates, "target_ssim": args.target,
              "meets_target": best["ssim"] >= args.target, "palette": pal}
    save_json(work / "vector-report.json", report)
    log(f"best: {best['preset']} -> {final} (ssim {best['ssim']}, target {args.target}"
        f"{'' if report['meets_target'] else ' NOT met: try --preset detailed, more --colors, or --mono'})")
    return final
