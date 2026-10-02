"""Shared paths, subprocess helpers and colour utilities for refkit."""
from __future__ import annotations

import colorsys
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def saved_env(name: str) -> str | None:
    """Process env first; else the user-level value saved in the registry (a terminal opened before it was set)."""
    if os.environ.get(name):
        return os.environ[name]
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    return None

# Nothing machine-specific: the repo is found from this file, the engine folder from ATELIER_ENGINE.
REPO = Path(__file__).resolve().parents[2]            # <repo>/studio/refkit/common.py
STUDIO = REPO / "studio"
# Engine: ComfyUI portable, models, venvs, ComfyUI output. The refkit shim sets ATELIER_ENGINE; default <repo>\engine.
STUDIO_ROOT = Path(saved_env("ATELIER_ENGINE") or REPO / "engine")
MODELS = STUDIO_ROOT / "models"
OUTPUT = REPO / "images"      # default for generated deliverables (git-ignored)
SCRATCH = REPO / "scratch"    # smoke/bench/test runs (git-ignored)
TOKENS_FILE = STUDIO / "tokens.json"
BLENDER_SCRIPTS = Path(__file__).resolve().parent / "blender"

OLLAMA = "http://127.0.0.1:11434"
VISION_MODEL = "qwen3-vl:8b"   # only used with --describe ollama
GEMINI_MODEL = "gemini-flash-latest"   # --describe gemini (own GEMINI_API_KEY)


class RefkitError(SystemExit):
    """A clean, user-facing failure. Uncaught it exits like SystemExit(msg); callers that can degrade
    (e.g. analyze skipping depth) catch it specifically instead of swallowing every SystemExit."""


def safe_name(text: str, limit: int = 40) -> str:
    """Prompt text -> a Windows-safe filename fragment (no `:` NTFS streams, no reserved characters)."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text.strip())
    s = re.sub(r"[\s,]+", "_", s).strip("._ ")[:limit].rstrip("._ ")
    return s or "untitled"


def open_image(path: Path | str) -> Image.Image:
    """Open an image the way ComfyUI's LoadImage sees it: EXIF orientation applied (phone JPEGs)."""
    return ImageOps.exif_transpose(Image.open(path))


def out_dir(src: Path, out: str | None = None) -> Path:
    """Outputs for `ref.png` go to `ref.refkit/` next to it unless --out is given."""
    # Absolute, always: Blender resolves relative output paths against its own base, not our cwd.
    d = Path(out).resolve() if out else src.with_name(src.stem + ".refkit")
    d.mkdir(parents=True, exist_ok=True)
    return d


def tool(name: str) -> str:
    """Resolve a CLI (npm installs `.cmd` shims on Windows, which subprocess can't find by bare name)."""
    path = shutil.which(name)
    if not path:
        raise RefkitError(f"refkit: `{name}` is not on PATH (run <repo>\\setup\\08-visual-tools.ps1)")
    return path


def run(args: list, check: bool = True, **kw) -> subprocess.CompletedProcess:
    args = [str(a) for a in args]
    args[0] = tool(args[0])
    return subprocess.run(args, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def _plain(o):
    """numpy scalars/arrays -> JSON-native types."""
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def save_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_plain), encoding="utf-8")
    return path


JSON_MODE = False   # --json: stdout carries only the result object (meta.emit); logs move to stderr


def say(text: str = "") -> None:
    """Human-readable report output (tables, listings); kept off stdout in --json mode."""
    print(text, flush=True, file=sys.stderr if JSON_MODE else sys.stdout)


def log(msg: str) -> None:
    say(f"refkit: {msg}")


# --- colour -------------------------------------------------------------------------------------

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(round(c)) for c in rgb))


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255, shape (..., 3)) to CIE Lab (D65)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def delta_e(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIE76 distance; good enough for palette matching and flagging."""
    return np.linalg.norm(np.asarray(lab1) - np.asarray(lab2), axis=-1)


def is_teal(rgb) -> bool:
    """Teal/cyan band (hue 150-200 deg, visibly saturated). Only checked when project tokens set forbid_teal."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return bool(150 <= h * 360 <= 200 and s > 0.25 and 0.12 < l < 0.92)


def load_tokens(path: str | None = None) -> dict:
    p = Path(path) if path else TOKENS_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
