"""refkit status: what this machine can do right now (tools, models, servers, GPU)."""
from __future__ import annotations

import os
import shutil

import requests

from . import caps, comfy, host
from .common import MODELS, OLLAMA, OUTPUT, REPO, STUDIO, STUDIO_ROOT, say

TOOLS = ["blender", "magick", "inkscape", "potrace", "vtracer", "svgo", "resvg", "pngquant", "cwebp", "avifenc",
         "oxipng", "ffmpeg", "ffprobe", "gltf-transform", "gltfpack", "toktx", "f3d", "rembg", "exiftool",
         "tesseract", "blender-mcp", "comfy", "claude", "gemini"]


def main() -> None:
    say("paths")
    say(f"  repo    {REPO}")
    say(f"  engine  {STUDIO_ROOT}  (ATELIER_ENGINE{'' if os.environ.get('ATELIER_ENGINE') else ' not set: default'})")
    say(f"  output  {OUTPUT}")
    say("tools")
    missing = [t for t in TOOLS if not shutil.which(t)]
    say(f"  {len(TOOLS) - len(missing)}/{len(TOOLS)} on PATH" + (f"; missing: {', '.join(missing)}" if missing else ""))

    say(f"models ({MODELS})")
    for d in sorted(p for p in MODELS.iterdir() if p.is_dir()) if MODELS.exists() else []:
        files = [f for f in d.iterdir() if f.suffix in (".safetensors", ".pth", ".gguf", ".ckpt")]
        if files:
            gb = sum(f.stat().st_size for f in files) / 1e9
            say(f"  {d.name:20s} {len(files)} file(s) {gb:5.1f} GB  {', '.join(f.stem for f in files)}")
        partial = list(d.glob("*.part"))
        if partial:
            say(f"  {d.name:20s} downloading: {', '.join(p.stem for p in partial)}")

    say("workflows")
    for w in sorted((STUDIO / "workflows").glob("*.api.json")):
        say(f"  {w.name.removesuffix('.api.json')}")

    say("servers")
    base = comfy.find()
    if base:
        s = requests.get(f"{base}/system_stats", timeout=3).json()
        dev = s["devices"][0]
        # "cuda:0 NVIDIA GeForce RTX 4080 SUPER : cudaMallocAsync" -> the card name
        name = dev["name"].split(" : ")[0].split(" ", 1)[-1]
        say(f"  ComfyUI {s['system']['comfyui_version']} up at {base}, {name}, "
              f"VRAM free {dev['vram_free'] / 1e9:.1f}/{dev['vram_total'] / 1e9:.1f} GB")
        # Other Claude sessions share this server: their jobs queue with yours, and a restart would kill them.
        running, queued = comfy.jobs(base)
        say(f"  jobs: {running} running, {queued} queued")
        if (want := comfy.installed_version()) and want != s["system"]["comfyui_version"]:
            say(f"  ComfyUI {want} is installed but not running yet: `refkit smoke` restarts it when no jobs run")
    else:
        say("  ComfyUI down (starts automatically when needed; or run `comfy` / Comfy Desktop)")
    try:
        ps = requests.get(f"{OLLAMA}/api/ps", timeout=2).json().get("models", [])
        say(f"  Ollama up (optional), loaded: {', '.join(m['name'] for m in ps) or 'none'}")
    except requests.RequestException:
        say("  Ollama down (optional, not needed by refkit)")
    if gpu := host.gpu_line():
        say(f"  {gpu}")
    say("capabilities")
    for line in caps.summary():
        say(f"  {line}")
