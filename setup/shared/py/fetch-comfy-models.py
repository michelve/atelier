"""Download the models that ComfyUI workflow templates reference, into the shared store (resumable).

Each bundled template lists its models (directory, name, url) in node properties, so this reads the
templates instead of a hand-kept list that would drift. Usage:
  python fetch-comfy-models.py --comfy <engine>\\ComfyUI --dest <engine>\\models TEMPLATE [TEMPLATE ...]
  --extra DIR=URL   additional files (e.g. upscale_models=https://.../4x-UltraSharp.safetensors)
  --dry-run         list what would be downloaded
  --skip NAME       a model file a template lists but refkit doesn't use (repeatable)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ap = argparse.ArgumentParser()
ap.add_argument("templates", nargs="*")
ap.add_argument("--comfy", required=True)
ap.add_argument("--dest", required=True)
ap.add_argument("--extra", action="append", default=[])
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--skip", action="append", default=[])
a = ap.parse_args()

tpl_dir = next(Path(a.comfy).glob("python_embeded/Lib/site-packages/comfyui_workflow_templates_json/templates"))
dest = Path(a.dest)


def models_in(obj):
    if isinstance(obj, dict):
        for m in obj.get("models", []) if isinstance(obj.get("models"), list) else []:
            if isinstance(m, dict) and m.get("url") and m.get("name") and m.get("directory"):
                yield m["directory"], m["name"], m["url"]
        for v in obj.values():
            yield from models_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from models_in(v)


wanted: dict[Path, str] = {}
for t in a.templates:
    f = tpl_dir / f"{t}.json"
    if not f.exists():
        sys.exit(f"template not found: {f}")
    for directory, name, url in models_in(json.loads(f.read_text(encoding="utf-8"))):
        if name not in a.skip:
            wanted[dest / directory / name] = url
for e in a.extra:
    directory, url = e.split("=", 1)
    wanted[dest / directory / url.rsplit("/", 1)[-1].split("?")[0]] = url


def size_of(url: str) -> int:
    r = requests.head(url, allow_redirects=True, timeout=30)
    return int(r.headers.get("x-linked-size") or r.headers.get("content-length") or 0)


def download(path: Path, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = size_of(url)
    if path.exists() and (not total or path.stat().st_size == total):
        print(f"  have  {path.relative_to(dest)}")
        return
    part = path.with_suffix(path.suffix + ".part")
    for attempt in range(1, 6):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=60, allow_redirects=True) as r:
                if r.status_code == 416:  # already complete
                    break
                r.raise_for_status()
                mode = "ab" if have and r.status_code == 206 else "wb"
                t0, done = time.time(), (have if mode == "ab" else 0)
                with open(part, mode) as fh:
                    for chunk in r.iter_content(8 << 20):
                        fh.write(chunk)
                        done += len(chunk)
                rate = (done - have) / max(time.time() - t0, 1e-3) / 1e6
                print(f"  got   {path.relative_to(dest)}  {done / 1e9:.2f} GB  ({rate:.0f} MB/s)")
            break
        except requests.RequestException as e:
            print(f"  retry {attempt}/5 {path.name}: {e}")
            time.sleep(5 * attempt)
    else:
        sys.exit(f"failed: {url}")
    if total and part.stat().st_size != total:
        sys.exit(f"size mismatch for {path.name}: {part.stat().st_size} != {total}")
    part.replace(path)


print(f"{len(wanted)} model file(s) -> {dest}")
for path, url in sorted(wanted.items()):
    if a.dry_run:
        print(f"  {path.relative_to(dest)}  <- {url}")
    else:
        download(path, url)
