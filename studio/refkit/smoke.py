"""refkit smoke: after a ComfyUI update, prove the pipeline still works (~4 min; --quick ~1 min).

  1. re-export every workflow in studio\\workflows from the bundled templates when the templates package changed
     (setup\\shared\\py\\export-comfy-workflows.py, the real frontend's graphToPrompt)
  2. validate every workflow's node classes / input names against the running server's /object_info
  3. run a tiny Z-Image generation and a BiRefNet cutout end to end; write smoke.png (contact sheet)
  4. (unless --quick) a to3d of that cutout with its inspect sheet, a 1-frame render, and one local-critic
     call — the 3D graph, Blender and the VLM are where updates break things quietly (~3 min)
Exit code 1 on any failure, so setup\\update.ps1 can report it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import comfy, cutout, gen, host
from .common import REPO, SCRATCH, RefkitError, log

COMFY_TEMPLATES_PKG = "comfyui-workflow-templates"
EXPORTER = REPO / "setup" / "shared" / "py" / "export-comfy-workflows.py"
STAMP = comfy.WORKFLOWS / ".templates-version"
OUT = SCRATCH / "smoke"


def exporter_python() -> str:
    """A Python that has Playwright (the exporter drives the real ComfyUI frontend). On Windows refkit's own venv
    doesn't, and it may be first on PATH, so: ATELIER_PYTHON if set, else every python on PATH, first one that works.
    On macOS the setup installs Playwright into refkit's venv, so that one is used."""
    if not host.WINDOWS:
        return os.environ.get("ATELIER_PYTHON") or sys.executable
    env = {k: v for k, v in os.environ.items() if k != "PYTHONNOUSERSITE"}
    found = subprocess.run(["where", "python"], capture_output=True, text=True).stdout.split()
    for py in [os.environ.get("ATELIER_PYTHON"), *found, "py"]:
        if not py or str(Path(py).resolve()).startswith(str(Path(sys.prefix).resolve())):
            continue
        ok = subprocess.run([py, "-c", "import playwright"], capture_output=True, env=env).returncode == 0
        if ok:
            return py
    raise RefkitError("refkit: no Python with Playwright found for the workflow exporter "
                      "(pip install playwright && python -m playwright install chromium, or set ATELIER_PYTHON)")


def templates_version() -> str:
    """Version of ComfyUI's bundled templates package (read from ComfyUI's own Python, not ours)."""
    py = host.engine_python(comfy.COMFY_DIR)
    r = subprocess.run([str(py), "-s", "-c", f"import importlib.metadata as m; print(m.version('{COMFY_TEMPLATES_PKG}'))"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def reexport(force: bool = False) -> bool:
    ver = templates_version()
    if not force and STAMP.exists() and STAMP.read_text().strip() == ver:
        log(f"workflows current for templates {ver}")
        return True
    names = sorted(p.name.removesuffix(".api.json") for p in comfy.WORKFLOWS.glob("*.api.json"))
    log(f"re-exporting {len(names)} workflows for templates {ver}…")
    r = subprocess.run([exporter_python(), str(EXPORTER),
                        "--comfy", str(comfy.COMFY_DIR), "--out", str(comfy.WORKFLOWS), "--url", comfy.url(), *names],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       # Playwright is in the system Python's user site; refkit's shim sets PYTHONNOUSERSITE=1.
                       env={k: v for k, v in os.environ.items() if k != "PYTHONNOUSERSITE"})
    if r.returncode:
        log(f"export FAILED:\n{(r.stderr or r.stdout)[-1500:]}")
        return False
    STAMP.write_text(ver)
    return True


def deep(cut: Path) -> bool:
    """3D + render + critic on the smoke cutout. Each step reports on its own; any failure fails the smoke."""
    from . import __main__ as cli
    from . import render, to3d
    ok = True
    try:
        res = to3d.main(cli.build().parse_args(["to3d", str(cut), "--seed", "1",
                                                "--out", str(OUT / "3d")]))
        run = res["runs"][0]
        # qa's gate: non-manifold above 3% of edges (a triangle mesh has ~1.5 edges per triangle)
        bad = run["stats"]["non_manifold_edges"] > 0.045 * run["stats"]["tris"] or not run["stats"]["uv_layers"]
        log(f"{'FAIL' if bad else 'OK  '} to3d -> {run['sheet']} (look at it)")
        ok &= not bad
        render.main(cli.build().parse_args(["render", run["glb"], "--frames", "1", "--res", "640x640",
                                            "--samples", "32", "--out", str(OUT / "render")]))
        log(f"OK   render still -> {OUT / 'render' / 'poster.webp'}")
    except SystemExit as e:
        log(f"FAIL 3D/render: {e}")
        ok = False
    try:
        from . import vlm
        answer = vlm.ask([cut], "Name the object in this image in at most three words.", max_new_tokens=12)
        vlm.unload()
        log(f"OK   local critic answers: {answer!r}")
    except SystemExit as e:   # not installed is a warning, not a failure: the critic is optional
        log(f"WARN local critic unavailable: {e}")
    return ok


def lite() -> bool:
    """Without CUDA (a Mac): prove what runs here end to end. rembg cuts the golden mug back out of a grey backdrop
    (alpha IoU vs the original), a flat test graphic is vectorized and passes qa, and Blender renders a still."""
    from . import __main__ as cli
    from .common import run
    ok = True
    out = OUT / "lite"
    out.mkdir(parents=True, exist_ok=True)
    mug = Image.open(REPO / "studio" / "tests" / "golden" / "inputs" / "mug.png").convert("RGBA")
    photo = Image.new("RGB", mug.size, "#9a9a96")
    photo.paste(mug, (0, 0), mug)
    photo.save(out / "photo.png")
    try:
        cut = np.array(Image.open(cutout.cut(out / "photo.png", out, engine="rembg")).getchannel("A")) > 128
        want = np.array(mug.getchannel("A")) > 128
        iou = float((cut & want).sum() / max((cut | want).sum(), 1))
        log(f"{'OK  ' if iou >= 0.9 else 'FAIL'} rembg cutout, alpha IoU {iou:.3f} vs the original (>= 0.9)")
        ok &= iou >= 0.9
    except RefkitError as e:
        log(f"FAIL rembg cutout: {e}")
        ok = False
    flat = Image.new("RGB", (512, 512), "#0d0d12")
    draw = ImageDraw.Draw(flat)
    draw.rounded_rectangle((96, 96, 416, 416), 48, fill="#8f6bff")
    draw.ellipse((176, 176, 336, 336), fill="#ece8ff")
    flat.save(out / "flat.png")
    vec = out / "flat.refkit"
    ok &= _step("vectorize", cli.main(["vectorize", str(out / "flat.png"), "--preset", "clean", "--out", str(vec)]))
    ok &= _step("qa (SVG vs its reference)", cli.main(["qa", str(vec / "vector.svg"), "--ref", str(out / "flat.png")]))
    glb = out / "cube.glb"
    run(["blender", "-b", "--factory-startup", "--python-expr",
         f"import bpy; bpy.ops.export_scene.gltf(filepath=r'{glb}')"], check=False)
    ok &= _step("render (Cycles still)", cli.main(["render", str(glb), "--frames", "1", "--res", "256x256",
                                                   "--samples", "8", "--out", str(out / "render")]))
    log(f"look at {out / 'render' / 'poster.webp'} and {vec / 'vector.svg'}")
    log("SMOKE PASS" if ok else "SMOKE FAIL")
    return ok


def _step(name: str, code: int) -> bool:
    log(f"{'OK  ' if code == 0 else 'FAIL'} {name}")
    return code == 0


def main(args) -> bool:
    if not host.CUDA:
        return lite()   # the local engine on a Mac is optional and runs no CUDA workflows; check what runs here
    ok = True
    comfy.ensure_current()   # after an update the running server may still be the old version
    if not args.no_export:
        ok &= reexport(args.force_export)
    for wf in sorted(comfy.WORKFLOWS.glob("*.api.json")):
        problems = comfy.validate(comfy.load_workflow(wf.name.removesuffix(".json")))
        log(f"{'OK  ' if not problems else 'FAIL'} {wf.name}" + ("" if not problems else "\n    " + "\n    ".join(problems)))
        ok &= not problems
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        from . import __main__ as cli
        img = Path(gen.main(cli.build().parse_args([
            "gen", "a white ceramic mug on a wooden table, soft daylight, product photo", "-m", "z-image",
            "--size", "768x768", "--seed", "1", "--out", str(OUT)]))["outputs"][0])
        cut = cutout.cut(img, OUT)
        sheet = Image.new("RGB", (1536, 768), "#808080")
        sheet.paste(Image.open(img).convert("RGB").resize((768, 768)), (0, 0))
        c = Image.open(cut).convert("RGBA").resize((768, 768))
        sheet.paste(c, (768, 0), c)
        sheet.save(OUT / "smoke.png")
        log(f"end-to-end OK -> {OUT / 'smoke.png'} (look at it)")
    except RefkitError as e:
        log(f"end-to-end FAILED: {e}")
        ok = False
    if not args.quick and ok:
        ok &= deep(cut)
    log("SMOKE PASS" if ok else "SMOKE FAIL")
    return ok

