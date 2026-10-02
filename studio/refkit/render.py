"""refkit render: model or .blend -> Cycles/OptiX frames -> MP4 (H.264) + WebM (VP9) + AVIF/WebP poster."""
from __future__ import annotations

import time
from pathlib import Path

from . import gpu, meta
from .common import BLENDER_SCRIPTS, RefkitError, log, out_dir, run

HERO_LOOP_BUDGET_MB = 3.0   # checklist budget for a hero loop; over it we say so (qa enforces it too)


def blender(script: str, *args) -> str:
    res = run(["blender", "-b", "--factory-startup", "-P", BLENDER_SCRIPTS / script, "--", *args], check=False)
    out = res.stdout + res.stderr
    if res.returncode != 0 or "Traceback" in out:
        tail = "\n".join(out.splitlines()[-25:])
        raise RefkitError(f"refkit: Blender {script} failed:\n{tail}")
    return out


def encode(frames: list[Path], dest: Path, fps: int = 24, transparent: bool = False, av1: bool = False) -> dict:
    # Frames are named by frame number; a .blend rendered --as-is may start anywhere (e.g. 0010.png).
    start = int(frames[0].stem)
    pattern = str(frames[0].parent / "%04d.png")
    src = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", fps, "-start_number", start, "-i", pattern]
    mp4, webm = dest / "turntable.mp4", dest / "turntable.webm"
    run([*src, "-c:v", "libx264", "-preset", "slow", "-crf", 20, "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4])
    run([*src, "-c:v", "libvpx-vp9", "-b:v", 0, "-crf", 32, "-row-mt", 1,
         "-pix_fmt", "yuva420p" if transparent else "yuv420p", webm])
    files = {"mp4": mp4.name, "webm": webm.name}
    if av1:
        av1_out = dest / "turntable-av1.mp4"
        run([*src, "-c:v", "libsvtav1", "-preset", 6, "-crf", 32, "-pix_fmt", "yuv420p10le", "-movflags", "+faststart", av1_out])
        files["av1"] = av1_out.name
    for f in (mp4, webm):
        mb = f.stat().st_size / 1e6
        if mb > HERO_LOOP_BUDGET_MB:
            log(f"{f.name} is {mb:.1f} MB (hero-loop budget {HERO_LOOP_BUDGET_MB} MB): lower --res or use --av1")
    return files


def poster(frame: Path, dest: Path) -> dict:
    avif, webp = dest / "poster.avif", dest / "poster.webp"
    run(["avifenc", "-q", 70, "-s", 4, frame, avif])
    run(["cwebp", "-quiet", "-q", 82, "-exact", frame, "-o", webp])
    return {"avif": avif.name, "webp": webp.name}


def main(args) -> dict:
    src = Path(args.input).resolve()
    if not src.exists():
        raise RefkitError(f"refkit: no such file: {src}")
    dest = out_dir(src, args.out)
    frames = dest / "frames"
    for old in frames.glob("*.png"):
        old.unlink()
    gpu.free_vram()
    t = time.time()
    extra = ["--as-is"] if args.as_is else []
    extra += ["--transparent"] if args.transparent else []
    extra += ["--ground"] if args.ground else []
    extra += ["--res", args.res] if args.res else []
    extra += ["--samples", args.samples] if args.samples else []
    out = blender("turntable.py", "--input", src, "--out", dest, "--frames", args.frames, "--look", args.look, *extra)
    device = next((ln for ln in out.splitlines() if ln.startswith("TURNTABLE device")), "device ?")
    rendered = sorted(frames.glob("*.png"))
    if not rendered:
        raise RefkitError("refkit: Blender rendered no frames")
    log(f"rendered {len(rendered)} frame(s) in {time.time() - t:.0f}s ({device.removeprefix('TURNTABLE ')})")
    files = poster(rendered[0], dest)
    if len(rendered) > 1:
        files |= encode(rendered, dest, transparent=args.transparent, av1=args.av1)
    log("wrote " + ", ".join(str(dest / f) for f in files.values()))
    meta.record(dest / files["webp"], "render", frames=len(rendered), look=args.look, as_is=args.as_is or None,
                transparent=args.transparent or None, ground=args.ground or None, inputs=[src],
                files=[dest / f for f in files.values()], seconds=round(time.time() - t, 1))
    return {"outputs": [str(dest / f) for f in files.values()], "folder": str(dest)}
