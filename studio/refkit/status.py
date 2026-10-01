"""refkit status: what this machine can do right now (tools, models, servers, GPU)."""
from __future__ import annotations

import os
import shutil
import subprocess

import requests

from . import comfy
from .common import MODELS, OLLAMA, OUTPUT, REPO, STUDIO, STUDIO_ROOT

TOOLS = ["blender", "magick", "inkscape", "potrace", "vtracer", "svgo", "resvg", "pngquant", "cwebp", "avifenc",
         "oxipng", "ffmpeg", "ffprobe", "gltf-transform", "gltfpack", "toktx", "f3d", "rembg", "exiftool",
         "tesseract", "blender-mcp", "comfy", "claude", "gemini"]


def main() -> None:
    print("paths")
    print(f"  repo    {REPO}")
    print(f"  engine  {STUDIO_ROOT}  (ATELIER_ENGINE{'' if os.environ.get('ATELIER_ENGINE') else ' not set: default'})")
    print(f"  output  {OUTPUT}")
    print("tools")
    missing = [t for t in TOOLS if not shutil.which(t)]
    print(f"  {len(TOOLS) - len(missing)}/{len(TOOLS)} on PATH" + (f"; missing: {', '.join(missing)}" if missing else ""))

    print(f"models ({MODELS})")
    for d in sorted(p for p in MODELS.iterdir() if p.is_dir()) if MODELS.exists() else []:
        files = [f for f in d.iterdir() if f.suffix in (".safetensors", ".pth", ".gguf", ".ckpt")]
        if files:
            gb = sum(f.stat().st_size for f in files) / 1e9
            print(f"  {d.name:20s} {len(files)} file(s) {gb:5.1f} GB  {', '.join(f.stem for f in files)}")
        partial = list(d.glob("*.part"))
        if partial:
            print(f"  {d.name:20s} downloading: {', '.join(p.stem for p in partial)}")

    print("workflows")
    for w in sorted((STUDIO / "workflows").glob("*.api.json")):
        print(f"  {w.name.removesuffix('.api.json')}")

    print("servers")
    base = comfy.find()
    if base:
        s = requests.get(f"{base}/system_stats", timeout=3).json()
        dev = s["devices"][0]
        # "cuda:0 NVIDIA GeForce RTX 4080 SUPER : cudaMallocAsync" -> the card name
        name = dev["name"].split(" : ")[0].split(" ", 1)[-1]
        print(f"  ComfyUI {s['system']['comfyui_version']} up at {base}, {name}, "
              f"VRAM free {dev['vram_free'] / 1e9:.1f}/{dev['vram_total'] / 1e9:.1f} GB")
    else:
        print("  ComfyUI down (starts automatically when needed; or run `comfy` / Comfy Desktop)")
    try:
        ps = requests.get(f"{OLLAMA}/api/ps", timeout=2).json().get("models", [])
        print(f"  Ollama up (optional), loaded: {', '.join(m['name'] for m in ps) or 'none'}")
    except requests.RequestException:
        print("  Ollama down (optional, not needed by refkit)")
    try:
        smi = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
        used, total, util = (v.strip() for v in smi.split(","))
        print(f"  GPU {used}/{total} MiB used, {util}% busy")
    except Exception:
        pass
