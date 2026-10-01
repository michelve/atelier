"""Keep the 16 GB card for one engine at a time: unload Ollama models and ask ComfyUI to free memory."""
from __future__ import annotations

import requests

from . import comfy
from .common import OLLAMA, log


def free_vram(keep: str | None = None) -> None:
    try:
        loaded = requests.get(f"{OLLAMA}/api/ps", timeout=2).json().get("models", [])
        for m in loaded:
            if m["name"] != keep:
                requests.post(f"{OLLAMA}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=30)
                log(f"unloaded Ollama model {m['name']}")
    except requests.RequestException:
        pass
    base = comfy.find() if keep != "comfy" else None
    if base:
        try:
            requests.post(f"{base}/free", json={"unload_models": True, "free_memory": True}, timeout=5)
        except requests.RequestException:
            pass
