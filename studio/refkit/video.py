"""refkit video: prompt / keyframes -> video clip. Generation is cloud (Google, own key; no local video model this
round), finishing is local: SeedVR2 upscale + frame interpolation in ComfyUI core.

  omni       Gemini Omni 1.1 Flash (default): best Google video model, ~$0.10/s at 720p, edit-by-conversation
  veo-fast   Veo 3.1 Fast: cheapest with first+last frame, reference images and extension ($0.10/s 720p)
  veo        Veo 3.1 ($0.40/s)          veo-lite   Veo 3.1 Lite (cheap drafts, no refs/extension, $0.05/s)

  refkit video "slow push-in, steam rises from the cup" --from still.png --yes
  refkit video "day turns to night over the city" --from day.png --to night.png -m veo-fast --yes
  refkit video "make the steam thicker. Keep everything else the same." --continue <interaction id> --yes
  refkit video clip.mp4 --finish-only --upscale --interp 2          (local finish of an existing clip)

Keyframes usually come from `refkit gen` (local, free); describe only the motion in the prompt, not what the frames
already show. 1080p/4K from Omni are just upscales: generate 720p and use --upscale (SeedVR2, local, better).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import comfy, gpu, prompting
from .common import REPO, RefkitError, log, run, safe_name

NANOBANANA = REPO / "nanobanana.py"
MODELS = {"omni": "omni", "veo": "veo", "veo-fast": "veo-fast", "veo-lite": "veo-lite"}


def generate(args, out: Path) -> Path:
    model = args.model or "omni"
    if model not in MODELS:
        raise RefkitError(f"refkit: unknown video model {model!r}; choose from {', '.join(MODELS)}")
    for tip in prompting.lint(model.split("-")[0], args.prompt):
        log(f"prompt tip: {tip}")
    cmd = [sys.executable, str(NANOBANANA), args.prompt, "--video", "-m", MODELS[model], "-o", str(out),
           "--size", args.res]
    if args.frm:
        cmd += ["-i", str(Path(args.frm).resolve())]
    if args.to:
        cmd += ["--to", str(Path(args.to).resolve())]
    for r in args.ref:
        cmd += ["--ref", str(Path(r).resolve())]
    for flag, val in (("--aspect", args.aspect), ("--seconds", args.seconds), ("--continue", args.cont),
                      ("--negative", args.negative)):
        if val:
            cmd += [flag, str(val)]
    if args.yes:
        cmd.append("--yes")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    for line in (res.stderr + res.stdout).splitlines():
        if line.startswith(("cost estimate", "interaction id", "note:")):
            log(line)
    if res.returncode or not out.exists():
        raise RefkitError(f"refkit: video generation did not run: {(res.stderr or res.stdout)[-1500:]}")
    return out


def _video_nodes(wf: dict, clip: str) -> None:
    comfy.patch(wf, lambda n: n["class_type"] in ("LoadVideo", "VHS_LoadVideo"), "file", clip)


def _size(video: Path) -> tuple[int, int]:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
               "-of", "csv=p=0", video]).stdout.strip()
    w, h = (int(v) for v in out.split(",")[:2])
    return w, h


def finish(src: Path, dest: Path, upscale: bool, interp: int, seed: int = 1, target_long: int = 1920) -> Path:
    """Local finish in ComfyUI: SeedVR2 3B upscale to a `target_long` px long side (before interpolation, so fewer
    frames go through the heavy model), then FILM frame interpolation."""
    if not upscale and interp <= 1:
        return src
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    cur = src
    if upscale:
        long_side = max(_size(cur))
        factor = max(1.0, round(target_long / long_side, 3))
        if factor <= 1.0:
            log(f"already {long_side} px on the long side; skipping upscale")
            upscale = False
    if upscale:
        wf = comfy.load_workflow("utility_seedvr2_3b_int8_upscale_video.api")
        _video_nodes(wf, comfy.upload(cur))
        comfy.patch(wf, "ResizeImageMaskNode", "resize_type.multiplier", factor)
        comfy.patch(wf, "SeedVR2PostProcessing", "color_correction_method", "lab")   # templates ship "none" (tints)
        # Split the latent in time (chunking auto) so clips longer than a few seconds fit in 16 GB.
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "Split" in n.get("_meta", {}).get("title", ""),
                    "value", True)
        comfy.patch(wf, lambda n: "seed" in n["inputs"] and not isinstance(n["inputs"]["seed"], list), "seed", seed, expect=None)
        comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", "refkit/video-up", expect=None)
        items = [i for i in comfy.queue(wf, timeout=3600) if str(i.get("filename", "")).lower().endswith((".mp4", ".webm"))]
        if not items:
            raise RefkitError("refkit: SeedVR2 video upscale produced no video")
        cur = comfy.fetch(items[-1], dest).replace(dest / f"{src.stem}-up.mp4")
        log(f"upscaled -> {cur.name}")
    if interp > 1:
        wf = comfy.load_workflow("utility_video_frame_interpolation.api")
        _video_nodes(wf, comfy.upload(cur))
        # The multiplier is a PrimitiveInt that also feeds the fps maths (fps x multiplier).
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveInt" and "Multiplier" in n.get("_meta", {}).get("title", ""),
                    "value", interp)
        comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", "refkit/video-interp", expect=None)
        items = [i for i in comfy.queue(wf, timeout=3600) if str(i.get("filename", "")).lower().endswith((".mp4", ".webm"))]
        if not items:
            raise RefkitError("refkit: frame interpolation produced no video")
        cur = comfy.fetch(items[-1], dest).replace(dest / f"{cur.stem}-x{interp}.mp4")
        log(f"interpolated x{interp} -> {cur.name}")
    return cur


def main(args) -> Path:
    dest = Path(args.out).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if args.finish_only:
        src = Path(args.prompt).resolve()
        if not src.exists():
            raise RefkitError(f"refkit: --finish-only needs a video file, got {args.prompt!r}")
        clip = src
    else:
        if not args.prompt:
            raise RefkitError("refkit: video needs a prompt")
        clip = generate(args, dest / f"{args.model or 'omni'}-{safe_name(args.prompt, 32)}.mp4")
        log(f"clip -> {clip}")
    final = finish(clip, dest, args.upscale, args.interp)
    log(f"final {final}")
    return final
