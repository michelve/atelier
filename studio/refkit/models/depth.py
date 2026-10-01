"""Depth Anything 3 (mono large) through ComfyUI core nodes. Returns an 8-bit depth map (near = bright)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .. import comfy, gpu
from ..common import RefkitError


def estimate(rgb: np.ndarray, resolution: int = 1008) -> np.ndarray:
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "depth-in.png"
        Image.fromarray(rgb).save(src)
        wf = comfy.load_workflow("utility_depth_anything3_image_depth_estimation.api")
        comfy.patch(wf, "LoadImage", "image", comfy.upload(src))
        comfy.patch(wf, "DA3Inference", "resolution", resolution)
        render = next((k for k, n in wf.items() if n["class_type"] == "DA3Render"), None)
        if render is None:
            raise RefkitError("refkit: depth workflow has no DA3Render node — re-export it")
        for k in [k for k, n in wf.items() if n["class_type"] in ("PreviewImage", "ImageCompare")]:
            del wf[k]
        wf["save"] = {"class_type": "SaveImage", "inputs": {"images": [render, 0], "filename_prefix": "refkit/depth"}}
        item = next(i for i in comfy.queue(wf) if i.get("type") == "output")
        out = comfy.fetch(item, Path(tmp))
        depth = np.array(Image.open(out).convert("L").resize((rgb.shape[1], rgb.shape[0]), Image.Resampling.BICUBIC))
    return depth
