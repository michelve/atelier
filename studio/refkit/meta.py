"""Run records: one sidecar format for every refkit deliverable, an append-only run index, and --json results.

  record(out, "to3d", model=..., seed=..., inputs=[src])  writes <out>.json next to the file and appends one line
                                                         to <repo>/images/runs.jsonl (`refkit runs` reads it)
  emit({...})                                            with --json: the command's result as one JSON line on
                                                         stdout (logs go to stderr), so Claude parses results
                                                         instead of scraping log text

A sidecar answers "how was this made, can I remake it, may I use it": command, model + licence, workflow and the
versions it ran on, seeds, prompt (+ enhanced prompt), input file hashes (lineage), scores, qa, timings, cost.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from functools import cache
from pathlib import Path

from . import common
from .common import OUTPUT, REPO, save_json

SCHEMA = 1
INDEX = OUTPUT / "runs.jsonl"

# Model licences as published (checked 2026-10-01). Shown with results so nothing non-commercial ends up in
# client work by accident.
LICENCES = {
    "z-image": "Apache-2.0",
    "qwen": "Qwen Research License (non-commercial)",
    "qwen-edit": "Qwen Research License (non-commercial)",
    "qwen-rgba": "Qwen Research License (non-commercial)",
    "krea": "Krea 2 Community License (free under $1M revenue)",
    "krea-style": "Krea 2 Community License (free under $1M revenue)",
    "klein-edit": "Apache-2.0",
    "hidream": "MIT (Gemma-4 text encoder: Gemma terms)",
    "hidream-edit": "MIT (Gemma-4 text encoder: Gemma terms)",
    "banana": "Google Gemini API terms (paid, SynthID watermark)",
    "banana-pro": "Google Gemini API terms (paid, SynthID watermark)",
    "pixal3d": "MIT",
    "pixal3d-mv": "MIT",
    "trellis2": "MIT (DINOv3 encoder: Meta DINOv3 License)",
    "hunyuan3d": "Tencent Hunyuan Community License (excludes EU/UK/South Korea; outputs may not train other AI)",
    "seedvr2": "Apache-2.0",
    "birefnet": "MIT",
    "sam3": "SAM License",
    "omni": "Google Gemini API terms (paid, SynthID watermark)",
    "veo": "Google Gemini API terms (paid, SynthID watermark)",
}


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


@cache
def versions() -> dict:
    """What produced it: refkit commit, workflow export version, ComfyUI version (if a server is up)."""
    out = {}
    try:
        out["refkit"] = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                                       text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        out["refkit"] = None
    stamp = REPO / "studio" / "workflows" / ".templates-version"
    out["workflow_templates"] = stamp.read_text().strip() if stamp.exists() else None
    from . import comfy
    base = comfy.find()
    stats = comfy._stats(base) if base else None
    out["comfyui"] = (stats or {}).get("system", {}).get("comfyui_version")
    return out


def record(out: Path, command: str, *, inputs: list[Path] | None = None, model: str | None = None,
           files: list[Path] | None = None, index: bool = True, **fields) -> dict:
    """Write <out>.json (sidecar) and append the run to the index. Extra keyword fields are stored as given."""
    out = Path(out)
    rec = {"schema": SCHEMA, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "command": command, "output": str(out)}
    if model:
        rec["model"] = model
        rec["licence"] = LICENCES.get(model, "see reference/tools.md")
    rec.update({k: v for k, v in fields.items() if v is not None})
    if files:
        rec["files"] = [str(f) for f in files]
    if inputs:
        rec["inputs"] = [{"path": str(p), "sha1": file_hash(p)} for p in map(Path, inputs) if p.exists()]
    rec["versions"] = versions()
    save_json(out.with_suffix(".json"), rec)
    if index:
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        with open(INDEX, "a", encoding="utf-8") as f:
            f.write(json.dumps({k: rec[k] for k in ("time", "command", "output", "model", "seed", "prompt")
                                if k in rec}, ensure_ascii=False) + "\n")
    return rec


def emit(result: dict) -> None:
    """The command's machine-readable result: printed as the last stdout line when --json is on."""
    if common.JSON_MODE:
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)


def runs(last: int = 20, command: str | None = None) -> list[dict]:
    if not INDEX.exists():
        return []
    rows = [json.loads(ln) for ln in INDEX.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if command:
        rows = [r for r in rows if r.get("command") == command]
    return rows[-last:]


def main(args) -> dict:
    rows = runs(args.last, args.command)
    if common.JSON_MODE:
        return {"runs": rows}
    for r in rows:
        extra = " ".join(f"{k}={r[k]}" for k in ("model", "seed") if k in r)
        print(f"{r['time']}  {r['command']:8s} {extra:40s} {r['output']}")
    if not rows:
        print(f"no runs recorded yet ({INDEX})")
    return {"runs": rows}
