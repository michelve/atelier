"""What this machine can run. Windows (NVIDIA) runs everything; on macOS the commands and models that need CUDA stop
before doing any work and say what to use instead, rather than failing deep inside ComfyUI or torch."""
from __future__ import annotations

from .common import STUDIO_ROOT, RefkitError
from .host import CUDA

# Commands whose models need CUDA (int8/fp8 weights with CUDA-only kernels, 4-bit bitsandbytes), and the alternative.
NEEDS_CUDA = {
    "upscale": "SeedVR2 needs an NVIDIA GPU. Here: `refkit gen -m banana-pro` redraws at 4K (paid), or "
               "`refkit vectorize` for flat art",
    "to3d": "image-to-3D (Pixal3D, TRELLIS.2, Hunyuan3D) needs an NVIDIA GPU; run it on the Windows PC",
    "critique": "the local judge (Qwen3-VL in 4-bit) needs an NVIDIA GPU; look at the candidates yourself",
    "fix": "the region redraw (Qwen-Image edit, Z-Image) needs an NVIDIA GPU; for an edit use "
           "`refkit gen -m banana -i IMAGE` (paid)",
    "bench": "bench tunes ComfyUI's CUDA launch flags; there is nothing to tune without NVIDIA",
}
CLOUD_GEN = {"banana", "banana-pro"}
LOCAL_VIDEO = {"wan", "wan-fast"}
# Local gen models verified to run without CUDA on the optional macOS engine (bf16 builds); add one only after it
# has run there and the result was looked at.
ENGINE_GEN: set[str] = set()


def engine_installed() -> bool:
    return (STUDIO_ROOT / "ComfyUI" / "ComfyUI" / "main.py").exists()


def check(args) -> None:
    """Raise a RefkitError naming the alternative when this command/model can't run on this machine."""
    if CUDA:
        return
    cmd, why = args.cmd, None
    if cmd in NEEDS_CUDA:
        why = NEEDS_CUDA[cmd]
    elif cmd == "gen":
        model = args.model or ("qwen-edit" if args.image else "z-image")
        if model not in CLOUD_GEN and not (model in ENGINE_GEN and engine_installed()):
            why = (f"`-m {model}` runs on an NVIDIA GPU (CUDA-only weights). Here: `-m banana` or `-m banana-pro` "
                   "(Google, paid: it shows the cost and needs --yes)")
    elif cmd == "video":
        if args.model in LOCAL_VIDEO:
            why = "local video (Wan) needs an NVIDIA GPU. Here: `-m omni` or `-m veo` (Google, paid)"
        elif args.upscale:
            why = "--upscale (SeedVR2) needs an NVIDIA GPU; leave it out"
        elif args.interp > 1 and not engine_installed():
            why = "--interp (FILM) needs the optional local engine (setup step 5)"
    elif cmd == "cutout":
        if args.engine == "qwen":
            why = "--engine qwen needs an NVIDIA GPU; use the default cutout or --engine rembg"
        elif args.prompt and not engine_installed():
            why = ("picking objects by name (--prompt, SAM 3.1) needs the optional local engine (setup step 5); "
                   "--engine rembg cuts out the main subject")
    if why:
        raise RefkitError(f"refkit {cmd}: {why}")


def summary() -> list[str]:
    """Lines for `refkit status`."""
    if CUDA:
        return ["everything (NVIDIA, CUDA)"]
    engine = "installed (experimental)" if engine_installed() else "not installed (optional, setup step 5)"
    return [
        "runs here: analyze, vectorize, render, inspect, qa, runs, status, smoke; gen and video through Google "
        "(paid, --yes)",
        f"local engine: {engine}; without it cutout uses rembg",
        "needs the NVIDIA PC: " + ", ".join(sorted(NEEDS_CUDA)) + ", local gen and video models",
    ]
