"""refkit video: prompt / keyframes -> video clip, local (free) or Google (own key, paid); finishing is local:
SeedVR2 upscale + frame interpolation in ComfyUI core.

  wan        local, Wan 2.2 TI2V 5B (Apache-2.0): 720p 24 fps from a keyframe (--from) or text, ~220 s per 5 s
  wan-fast   local, Wan 2.2 I2V 14B + lightx2v 4-step LoRA: 480p 16 fps from a keyframe, ~75 s per 5 s (drafts:
             it invented an object in the 2026-10-01 test, so check every frame)
  omni       Gemini Omni 1.1 Flash (default): best Google video model, ~$0.10/s at 720p, edit-by-conversation
  veo-fast   Veo 3.1 Fast: cheapest with first+last frame, reference images and extension ($0.10/s 720p)
  veo        Veo 3.1 ($0.40/s)          veo-lite   Veo 3.1 Lite (cheap drafts, no refs/extension, $0.05/s)
Local first+last frame (Wan FLF2V) and LTX-2.5 (gated download) are not wired yet; use -m veo-fast for --to.

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

from . import comfy, gen, gpu, meta, prompting
from .common import REPO, RefkitError, log, open_image, run, safe_name

NANOBANANA = REPO / "nanobanana.py"
MODELS = {"omni": "omni", "veo": "veo", "veo-fast": "veo-fast", "veo-lite": "veo-lite"}
LOCAL = {"wan": "video_wan2_2_5B_ti2v", "wan-fast": "video_wan2_2_14B_i2v"}


def local(args, out: Path, seed: int) -> Path:
    """Wan 2.2 in ComfyUI. Sizes keep the keyframe's orientation (720p for wan, 480p for wan-fast)."""
    model = args.model
    if args.to:
        raise RefkitError("refkit: --to (first+last frame) isn't wired for local models yet; use -m veo-fast --yes")
    if model == "wan-fast" and not args.frm:
        raise RefkitError("refkit: -m wan-fast animates a keyframe: pass --from IMG (or use -m wan for text-to-video)")
    portrait = (args.aspect == "9:16")
    if args.frm:
        w0, h0 = open_image(args.frm).size
        portrait = portrait or h0 > w0
    seconds = args.seconds or 5
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    wf = comfy.load_workflow(LOCAL[model] + ".api")
    comfy.patch(wf, lambda n: n["class_type"] == "CLIPTextEncode" and "Positive" in comfy.title(n), "text", args.prompt)
    if model == "wan":
        w, h = (704, 1280) if portrait else (1280, 704)
        lat = next(k for k, n in wf.items() if n["class_type"] == "Wan22ImageToVideoLatent")
        wf[lat]["inputs"].update(width=w, height=h, length=int(seconds * 24) + 1)
        if args.frm:
            wf["key"] = {"class_type": "LoadImage", "inputs": {"image": comfy.upload(Path(args.frm).resolve())}}
            wf["key_fit"] = {"class_type": "ImageScale", "inputs": {"image": ["key", 0], "upscale_method": "lanczos",
                                                                   "width": w, "height": h, "crop": "center"}}
            wf[lat]["inputs"]["start_image"] = ["key_fit", 0]
    else:
        w, h = (480, 832) if portrait else (832, 480)
        comfy.patch(wf, "LoadImage", "image", comfy.upload(Path(args.frm).resolve()))
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "4steps" in comfy.title(n), "value", True)
        comfy.patch(wf, "WanImageToVideo", "width", w)
        comfy.patch(wf, "WanImageToVideo", "height", h)
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveFloat" and "Duration" in comfy.title(n), "value",
                    float(seconds))
    gen.seed_all(wf, seed)
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", "refkit/video-local", expect=None)
    items = [i for i in comfy.queue(wf, timeout=3600) if str(i.get("filename", "")).lower().endswith((".mp4", ".webm"))]
    if not items:
        raise RefkitError(f"refkit: {model} produced no video")
    return comfy.fetch(items[-1], out.parent).replace(out)


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


def record_cloud(clip: Path, args) -> dict:
    """Sidecar for a paid Google clip, merged into the JSON nanobanana.py writes (its interaction_id is kept)."""
    refs = [Path(p) for p in [args.frm, args.to, *args.ref] if p]
    return meta.record(clip, "video", model=args.model or "omni", prompt=args.prompt, paid=True, res=args.res,
                       seconds=args.seconds, aspect=args.aspect, inputs=refs or None)


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
        name = dest / f"{args.model or 'omni'}-{safe_name(args.prompt, 32)}.mp4"
        if args.model in LOCAL:
            import random
            seed = args.seed if args.seed is not None else random.randrange(2**31)
            clip = local(args, name, seed)
            meta.record(clip, "video", model=args.model, prompt=args.prompt, seed=seed, seconds=args.seconds or 5,
                        workflow=LOCAL[args.model], inputs=[Path(args.frm)] if args.frm else None)
        else:
            clip = generate(args, name)
            record_cloud(clip, args)
        log(f"clip -> {clip}")
    final = finish(clip, dest, args.upscale, args.interp)
    log(f"final {final}")
    return final
