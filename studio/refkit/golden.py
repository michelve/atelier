"""refkit bench --golden: the fixed-seed regression set (studio/tests/golden/golden.json).

  refkit bench --golden --label before          run every job, write <scratch>/golden/before/ + sheet.png
  refkit bench --golden --label after --compare before
                                                 same jobs, plus compare-before.png: each job's old | new side
                                                 by side with times and peak VRAM, to look at before keeping a change
  refkit bench --golden --label x --only 3d-mug,3d-camera

Jobs run through the normal CLI code paths (the same argument parser), so what is measured is what users get.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import SCRATCH, STUDIO, RefkitError, log

GOLDEN = STUDIO / "tests" / "golden"
OUT = SCRATCH / "golden"
TILE = 640


def _argv(job: dict, spec: dict, dest: Path, done: dict) -> list[str]:
    kind = job["kind"]
    if kind == "gen":
        return ["gen", job["prompt"], "-m", job["model"], "--seed", str(job["seed"]), "--size", job["size"], "--out", str(dest)]
    if kind == "edit":
        src = GOLDEN / spec["inputs"][job["input"]]["file"]
        return ["gen", job["prompt"], "-m", job["model"], "-i", str(src), "--seed", str(job["seed"]), "--out", str(dest)]
    if kind == "to3d":
        src = GOLDEN / spec["inputs"][job["input"]]["file"]
        return ["to3d", str(src), "--seed", str(job["seed"]), "--out", str(dest),
                *(["--hard-edges"] if job.get("hard_edges") else [])]
    if kind == "upscale":
        src = done.get(job["from"])
        if not src:
            raise RefkitError(f"golden: {job['id']} needs {job['from']} first")
        return ["upscale", str(src), "--seed", str(job["seed"]), "--out", str(dest)]
    raise RefkitError(f"golden: unknown job kind {kind!r}")


def _preview(kind: str, result) -> Path | None:
    """The image that represents a job's result on the sheet."""
    if kind == "to3d":
        run = result["runs"][0]
        return Path(run["sheet"]) if run.get("sheet") else Path(run["thumbnail"])
    outs = result.get("outputs") or []
    return Path(outs[0]) if outs else None


def _tile(path: Path | None, label: str, font) -> Image.Image:
    tile = Image.new("RGB", (TILE, TILE + 24), "#2a2a2e")
    if path and path.exists():
        im = Image.open(path).convert("RGBA")
        im.thumbnail((TILE, TILE))
        tile.paste(im, ((TILE - im.width) // 2, (TILE - im.height) // 2), im)
    ImageDraw.Draw(tile).text((6, TILE + 4), label, fill="#f2f2f2", font=font)
    return tile


def run(args) -> dict:
    from . import __main__ as cli
    from .bench import VramPeak
    spec = json.loads((GOLDEN / "golden.json").read_text(encoding="utf-8"))
    label = args.label or time.strftime("%Y%m%d-%H%M")
    root = OUT / label
    root.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None
    results, done = [], {}
    for job in spec["jobs"]:
        if only and job["id"] not in only:
            continue
        dest = root / job["id"]
        dest.mkdir(parents=True, exist_ok=True)
        argv = _argv(job, spec, dest, done)
        log(f"golden {job['id']}: refkit {' '.join(argv[:1] + argv[2:4])} …")
        ns = cli.build().parse_args(argv)
        from importlib import import_module
        module = import_module(f".{ns.cmd}", __package__)
        t = time.time()
        rec = {"id": job["id"], "kind": job["kind"]}
        with VramPeak() as vp:
            try:
                res = module.main(ns)
                rec["ok"] = True
            except (SystemExit, Exception) as e:   # one broken job is a result, not a reason to stop
                res, rec["ok"], rec["error"] = None, False, str(e)[:400]
        rec["seconds"], rec["peak_vram_mb"] = round(time.time() - t, 1), vp.peak
        prev = _preview(job["kind"], res) if res else None
        rec["preview"] = str(prev) if prev else None
        if prev and job["kind"] in ("gen", "edit"):
            done[job["id"]] = prev
        results.append(rec)
        log(json.dumps(rec))
        (root / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    font = ImageFont.load_default(size=16)
    tiles = [_tile(Path(r["preview"]) if r.get("preview") else None,
                   f"{r['id']}  {r['seconds']}s  {r['peak_vram_mb']} MB" + ("" if r["ok"] else "  FAILED"), font)
             for r in results]
    cols = 4
    sheet = Image.new("RGB", (cols * TILE, ((len(tiles) + cols - 1) // cols) * (TILE + 24)), "#1c1c20")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * TILE, (i // cols) * (TILE + 24)))
    sheet.save(root / "sheet.png")
    out = {"label": label, "results": results, "sheet": str(root / "sheet.png")}
    if args.compare:
        out["compare"] = str(compare(args.compare, label, results, font))
    log(f"golden {label}: {sum(r['ok'] for r in results)}/{len(results)} ok -> {out.get('compare', out['sheet'])}")
    return out


def compare(old_label: str, new_label: str, new: list[dict], font) -> Path:
    old_file = OUT / old_label / "results.json"
    if not old_file.exists():
        raise RefkitError(f"golden: no results for label {old_label!r} in {OUT}")
    old = {r["id"]: r for r in json.loads(old_file.read_text(encoding="utf-8"))}
    rows = []
    for r in new:
        o = old.get(r["id"], {})
        pair = Image.new("RGB", (TILE * 2, TILE + 24), "#1c1c20")
        pair.paste(_tile(Path(o["preview"]) if o.get("preview") else None,
                         f"{old_label}: {o.get('seconds', '-')}s {o.get('peak_vram_mb', '-')} MB", font), (0, 0))
        pair.paste(_tile(Path(r["preview"]) if r.get("preview") else None,
                         f"{new_label}: {r['seconds']}s {r['peak_vram_mb']} MB", font), (TILE, 0))
        ImageDraw.Draw(pair).text((TILE - 60, 4), r["id"], fill="#ffd27a", font=font)
        rows.append(pair)
    sheet = Image.new("RGB", (TILE * 2, len(rows) * (TILE + 24)), "#1c1c20")
    for i, row in enumerate(rows):
        sheet.paste(row, (0, i * (TILE + 24)))
    path = OUT / new_label / f"compare-{old_label}.png"
    sheet.save(path)
    return path
