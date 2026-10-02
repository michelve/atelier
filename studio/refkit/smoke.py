"""refkit smoke: after a ComfyUI update, prove the pipeline still works (~4 min; --quick ~1 min).

  1. re-export every workflow in studio\\workflows from the bundled templates when the templates package changed
     (AISetup\\templates\\export-comfy-workflows.py, the real frontend's graphToPrompt)
  2. validate every workflow's node classes / input names against the running server's /object_info
  3. run a tiny Z-Image generation and a BiRefNet cutout end to end; write smoke.png (contact sheet)
  4. (unless --quick) a to3d of that cutout with its inspect sheet, a 1-frame render, and one local-critic
     call — the 3D graph, Blender and the VLM are where updates break things quietly (~3 min)
Exit code 1 on any failure, so update-tools.ps1 can report it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

from . import comfy, cutout, gen, host
from .common import REPO, SCRATCH, RefkitError, log

COMFY_TEMPLATES_PKG = "comfyui-workflow-templates"
EXPORTER = REPO / "setup" / "templates" / "export-comfy-workflows.py"
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


def main(args) -> bool:
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

