"""Convert ComfyUI UI templates (graphs with subgraphs) to API-format JSON by letting the real frontend do it.

ComfyUI's /prompt endpoint only takes API format; templates ship as UI graphs. The frontend's
app.graphToPrompt() flattens subgraphs and resolves widgets exactly like "Export (API)" in the UI.
Needs ComfyUI running on --url. Usage:
  python export-comfy-workflows.py --comfy <engine>\\ComfyUI --out <repo>\\studio\\workflows TEMPLATE ...
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("templates", nargs="+")
ap.add_argument("--comfy", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--url", default="http://127.0.0.1:8188")
a = ap.parse_args()

# ComfyUI's bundled templates package: in the portable build's embedded Python (Windows) or the engine venv (macOS).
TEMPLATE_GLOBS = ("python_embeded/Lib/site-packages/comfyui_workflow_templates_json/templates",
                  "venv/lib/python3*/site-packages/comfyui_workflow_templates_json/templates")


def templates_dir(comfy: str) -> Path | None:
    return next((hit for g in TEMPLATE_GLOBS for hit in Path(comfy).glob(g)), None)


tpl_dir = templates_dir(a.comfy)
if tpl_dir is None:
    raise SystemExit(f"ComfyUI's templates package not found under {a.comfy}")
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(a.url)
    page.wait_for_function("() => window.app && window.app.graph && window.app.graphToPrompt", timeout=120_000)
    for name in a.templates:
        graph = json.loads((tpl_dir / f"{name}.json").read_text(encoding="utf-8"))
        api = page.evaluate(
            """async (g) => {
                await window.app.loadGraphData(g, true, true, null, { showMissingModelsDialog: false,
                                                                        showMissingNodesDialog: false });
                const p = await window.app.graphToPrompt();
                return p.output;
            }""", graph)
        (out / f"{name}.api.json").write_text(json.dumps(api, indent=2), encoding="utf-8")
        types = sorted({n["class_type"] for n in api.values()})
        print(f"{name}: {len(api)} nodes  [{', '.join(types)}]")
    browser.close()
