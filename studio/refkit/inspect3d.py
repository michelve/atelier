"""refkit inspect: QA views of a 3D model — what Claude (or the critic) looks at before calling a mesh done.

  refkit inspect model.glb               8 views: textured (Cycles) row + clay (geometry) row -> views.png
  refkit inspect model.glb --views 4     front/right/back/left only

Writes <model>.inspect/ (or --out): views/*.png, views.png (contact sheet), stats.json (verts, faces, UV layers,
open / non-manifold edges, degenerate faces, materials and texture sizes; used by `qa`). to3d runs it on every
result, so every mesh comes with a sheet to look at.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import gpu
from .common import RefkitError, log
from .render import blender

TILE = 320


def sheet(views_dir: Path, azimuths: list[int], dest: Path) -> Path:
    """Two rows (textured over clay), one column per azimuth, on a mid-grey so dark and light materials both read."""
    font = ImageFont.load_default(size=14)
    img = Image.new("RGB", (TILE * len(azimuths), TILE * 2 + 22), "#6b6b70")
    d = ImageDraw.Draw(img)
    for col, az in enumerate(azimuths):
        for row, mode in enumerate(("beauty", "clay")):
            p = views_dir / f"{mode}_{az:03d}.png"
            if p.exists():
                tile = Image.open(p).convert("RGBA").resize((TILE, TILE), Image.LANCZOS)
                img.paste(tile, (col * TILE, row * TILE), tile)
        d.text((col * TILE + 6, TILE * 2 + 3), f"{az} deg", fill="#f2f2f2", font=font)
    out = dest / "views.png"
    img.save(out)
    return out


def render_views(model: Path, dest: Path, **opts) -> dict:
    """Run blender/views.py; opts map to its flags (views, azimuths, elev, fov, fill, modes, res)."""
    model = Path(model).resolve()
    if not model.exists():
        raise RefkitError(f"refkit: no such file: {model}")
    dest.mkdir(parents=True, exist_ok=True)
    gpu.free_vram()   # Cycles needs the VRAM ComfyUI may be holding
    flags = [x for k, v in opts.items() if v is not None and v is not False
             for x in ((f"--{k}",) if v is True else (f"--{k}", v))]
    blender("views.py", "--input", model, "--out", dest, *flags)
    return json.loads((dest / "stats.json").read_text(encoding="utf-8"))


def inspect(model: Path, dest: Path, views: int = 8, res: int = 640) -> dict:
    stats = render_views(model, dest, views=views, res=res)
    stats["sheet"] = str(sheet(dest / "views", stats["azimuths"], dest))
    log(f"{stats['tris']:,} tris, {stats['verts']:,} verts, UVs {stats['uv_layers'] or 'none'}, "
        f"{stats['boundary_edges']} open / {stats['non_manifold_edges']} non-manifold edges -> {stats['sheet']}")
    return stats


def main(args) -> dict:
    src = Path(args.model).resolve()
    # meshopt-compressed GLBs (to3d's model.glb) import fine in Blender, unlike f3d/trimesh.
    dest = Path(args.out).resolve() if args.out else src.with_name(src.stem + ".inspect")
    return inspect(src, dest, args.views, args.res)
