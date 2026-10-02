"""refkit bench: A/B ComfyUI launch flags on fixed-seed jobs (wall time, peak VRAM, output drift vs baseline).

  refkit bench                         baseline + the built-in candidate flag sets
  refkit bench --set "ck=--use-ck-attention" --set "fast=--fast fp16_accumulation cublas_ops"
  refkit bench --full                  also time one Pixal3D image->3D job per flag set (~100 s each)

Each set restarts our ComfyUI with `comfy <flags>` (the shim) on :8188 (any server of ours is stopped first), runs:
Z-Image cold (includes model load), Z-Image warm x3, FLUX.2 klein edit, then Z-Image again (model A->B->A
switch: catches the int8 ConvRot reload stall, comfy-kitchen #196). Outputs are compared with the first set's
(mean absolute pixel difference) so a faster flag that changes the picture is visible, not just its speed.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import comfy, gen, to3d
from .common import SCRATCH, RefkitError, log, say

# Launch flags are compared with refkit's per-workflow Comfy Kitchen node switched off (it would otherwise run in every
# set); "kitchen-node" is the baseline flags with the node on, i.e. what refkit actually runs.
DEFAULT_SETS = [
    ("baseline", ""),
    ("kitchen-node", ""),
    ("ck-attn", "--use-ck-attention"),
    ("fast", "--fast fp16_accumulation cublas_ops"),
    ("ck+fast", "--use-ck-attention --fast fp16_accumulation cublas_ops"),
    ("fp8mm", "--fast fp8_matrix_mult --disable-dynamic-vram"),
    ("high-ram", "--high-ram"),
]
PROMPT = ("studio product photo of a matte ceramic teapot with a bamboo handle on a linen tablecloth, soft window "
          "light from the left, shallow depth of field, the word \"TEA\" embossed on the side")
EDIT = "Change the teapot glaze to deep glossy cobalt blue. Keep everything else the same."
OUT = SCRATCH / "bench"


class VramPeak:
    def __init__(self):
        self.peak, self._stop = 0, threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                used = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                      capture_output=True, text=True, timeout=5).stdout.strip()
                self.peak = max(self.peak, int(used.splitlines()[0]))
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass
            time.sleep(0.25)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(2)


def start(flags: str, timeout: int = 240) -> subprocess.Popen:
    comfy.stop()
    proc = comfy.launch(8188, flags.split(), new_group=False)
    t = time.time()
    while time.time() - t < timeout:
        if comfy.find():
            return proc
        if proc.poll() is not None:
            raise SystemExit(f"refkit bench: ComfyUI exited with flags {flags!r}; see comfyui.log")
        time.sleep(1)
    raise SystemExit(f"refkit bench: ComfyUI did not start with flags {flags!r}")


def run_job(wf: dict, dest: Path, name: str, timeout: int = 1800) -> tuple[float, Path | None]:
    t = time.time()
    items = comfy.queue(wf, timeout)
    dt = time.time() - t
    out = None
    for it in items:
        if it.get("type") == "output" and str(it["filename"]).lower().endswith(".png"):
            out = comfy.fetch(it, dest).replace(dest / f"{name}.png")
    return dt, out


def diff(a: Path | None, b: Path | None) -> float | None:
    if not (a and b and a.exists() and b.exists()):
        return None
    x = np.asarray(Image.open(a).convert("RGB"), dtype=np.float32)
    y = np.asarray(Image.open(b).convert("RGB").resize((x.shape[1], x.shape[0])), dtype=np.float32)
    return round(float(np.abs(x - y).mean()), 2)


def bench_set(label: str, flags: str, full: bool, cutout: Path | None) -> dict:
    dest = OUT / label
    dest.mkdir(parents=True, exist_ok=True)
    comfy.ATTENTION = "comfy kitchen attention" if label == "kitchen-node" else "pytorch attention"
    t0 = time.time()
    start(flags)
    res: dict = {"label": label, "flags": flags, "startup_s": round(time.time() - t0, 1)}
    try:
        with VramPeak() as vp:
            z = lambda seed: gen.build("z-image", PROMPT, [], "1024x1024", seed, f"refkit/bench-{label}")  # noqa: E731
            res["zimage_cold_s"], cold = run_job(z(101), dest, "zimage-101")
            warm = [run_job(z(s), dest, f"zimage-{s}")[0] for s in (102, 103, 104)]
            res["zimage_warm_s"] = round(sum(warm) / len(warm), 2)
            if not cold:
                raise SystemExit("Z-Image produced no image")
            k = gen.build("klein-edit", EDIT, [comfy.upload(cold)], "1024x1024", 7, f"refkit/bench-{label}")
            res["klein_s"], _ = run_job(k, dest, "klein-7")
            res["zimage_after_switch_s"], _ = run_job(z(105), dest, "zimage-105")
            if full and cutout:
                wf = to3d.build("pixal3d", comfy.upload(cutout), 1234, texture=2048, tris=60000,
                                prefix=f"refkit/bench-{label}", use_alpha=True)
                t = time.time()
                comfy.queue(wf, timeout=3600)
                res["pixal3d_s"] = round(time.time() - t, 1)
        res["peak_vram_mb"] = vp.peak
        res["ok"] = True
    except (SystemExit, Exception) as e:   # a flag that crashes ComfyUI is a result, not a reason to stop
        res["ok"], res["error"] = False, str(e)[:500]
    for key in [k for k in res if k.endswith("_s") and isinstance(res[k], float)]:
        res[key] = round(res[key], 2)
    return res


def main(args) -> dict | None:
    if args.golden:
        from . import golden
        return golden.run(args)
    # Flag A/B restarts ComfyUI per set: never while another session's jobs run on it.
    if (base := comfy.find()) and any(comfy.jobs(base)):
        raise RefkitError("refkit: ComfyUI has jobs running or queued (another session?); bench restarts the "
                          "server, so run it when `refkit status` shows 0 jobs")
    sets = [tuple(s.split("=", 1)) for s in args.set] if args.set else DEFAULT_SETS
    if sets[0][0] != "baseline":
        sets = [("baseline", ""), *sets]
    cutout = Path(args.cutout) if args.cutout else None
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for label, flags in sets:
        log(f"bench: {label} [{flags or 'no extra flags'}]")
        r = bench_set(label, flags, args.full, cutout)
        base = OUT / "baseline"
        r["drift_vs_baseline"] = {n: diff(base / f"{n}.png", OUT / label / f"{n}.png")
                                  for n in ("zimage-101", "klein-7")} if label != "baseline" else {}
        results.append(r)
        log(json.dumps(r))
        (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    comfy.stop()
    cols = ["startup_s", "zimage_cold_s", "zimage_warm_s", "klein_s", "zimage_after_switch_s", "pixal3d_s", "peak_vram_mb"]
    say("\n" + f"{'set':10s} " + " ".join(f"{c.removesuffix('_s'):>14s}" for c in cols) + "   drift(z/klein)")
    for r in results:
        cells = " ".join(f"{r.get(c, '-')!s:>14s}" for c in cols)
        d = r.get("drift_vs_baseline") or {}
        say(f"{r['label']:10s} {cells}   {d.get('zimage-101', '-')}/{d.get('klein-7', '-')}" +
              ("" if r.get("ok") else f"   FAILED: {r.get('error', '')[:80]}"))
    log(f"results: {OUT / 'results.json'}")
