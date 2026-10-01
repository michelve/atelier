"""refkit gen: image generation. Local through ComfyUI by default; Nano Banana is the approved cloud option.

  z-image      text -> image, Z-Image-Turbo int8: 8 steps, ~3 s, drafts and variations  [default without -i]
  qwen         text -> image, Qwen-Image 2.1 int8: best open model, typography/layout, native 2K, RGBA
  krea         text -> image, Krea 2 Turbo int8: most photographic look (product/catalogue realism)
  qwen-edit    reference image(s) + instruction, Qwen-Image 2.1: best open editor, multi-reference
               (<image1>, <image2>… in the prompt); output keeps the first reference's size unless --size  [default with -i]
  klein-edit   reference image(s) + instruction, FLUX.2 klein 4B: fast edits (~6 s)
  banana       Google Nano Banana 2 (cloud, own key, paid; --yes) - 4K, up to 14 refs, dense exact text
  banana-pro   Google Nano Banana Pro (cloud, ~2x NB2's price, ranks below it) - only if NB2 fails a layout
Every -i image (comma-separated) is a reference, in order. --enhance turns on the template's own prompt enhancer
(Qwen/Krea; loads an extra 9B/4B model). `--recipe MODEL` prints how to prompt it. Qwen-Image 2.1 and Krea 2 are
licensed for personal / non-commercial use (Krea: < $1M revenue).
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

from . import comfy, gpu, prompting
from .common import REPO, RefkitError, log

NANOBANANA = REPO / "nanobanana.py"

MODELS = {
    "z-image": {"workflow": "image_z_image_turbo_int8", "needs_image": False, "multiple": 16},
    "qwen": {"workflow": "image_qwen_image_2_1_t2i", "needs_image": False, "multiple": 32},
    "krea": {"workflow": "image_krea2_turbo_t2i_int8", "needs_image": False, "multiple": 16},
    "qwen-edit": {"workflow": "image_qwen_image_2_1_image_edit", "needs_image": True, "multiple": 32},
    "klein-edit": {"workflow": "image_flux2_klein_image_edit_4b_distilled", "needs_image": True, "multiple": 16},
    "banana": {"workflow": None, "needs_image": False, "cloud": "2"},
    "banana-pro": {"workflow": None, "needs_image": False, "cloud": "pro"},
}
ASPECTS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]


def parse_size(size: str, multiple: int = 16) -> tuple[int, int]:
    """'1920x1080' -> nearest multiples the model's latent grid accepts (1920x1088 for 16)."""
    try:
        w, h = (int(v) for v in size.lower().split("x"))
    except ValueError:
        raise RefkitError(f"refkit: --size must look like 1024x1024, got {size!r}") from None
    snap = lambda v: max(multiple, round(v / multiple) * multiple)  # noqa: E731
    return snap(w), snap(h)


def banana(model: str, args) -> list[Path]:
    """Nano Banana via nanobanana.py (own key). Size maps to the nearest supported aspect + 2K."""
    w, h = parse_size(args.size or "1024x1024", 1)
    aspect = min(ASPECTS, key=lambda a: abs(int(a.split(":")[0]) / int(a.split(":")[1]) - w / h))
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    outs = []
    for _ in range(args.count):
        out = dest / f"{model}-{random.randrange(2**32):08x}.png"
        cmd = [sys.executable, str(NANOBANANA), args.prompt, "-m", MODELS[model]["cloud"], "--aspect", aspect,
               "--size", "2K" if max(w, h) <= 2048 else "4K", "-o", str(out)]
        for img in (args.image.split(",") if args.image else []):
            cmd += ["-i", str(Path(img).resolve())]
        if args.yes:
            cmd.append("--yes")   # paid call: nanobanana prints the estimate and needs explicit consent
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             stdin=subprocess.DEVNULL)
        if res.returncode or not out.exists():
            raise RefkitError(f"refkit: Nano Banana did not run: {(res.stderr or res.stdout)[-1500:]}")
        outs.append(out)
        log(f"{out}  (cloud: Nano Banana {MODELS[model]['cloud']}, {aspect})")
    return outs


def seed_all(wf: dict, seed: int) -> None:
    n = 0
    for node in wf.values():
        for key in ("seed", "noise_seed"):
            if key in node["inputs"] and not isinstance(node["inputs"][key], list):
                node["inputs"][key] = seed
                n += 1
    if not n:
        raise RefkitError("refkit: workflow has no seed input — re-export it")


def klein_refs(wf: dict, images: list[str]) -> None:
    """FLUX.2 klein: one ReferenceLatent per reference image, chained on both guider branches.
    The template ships two LoadImage nodes but only wires the first; build the chain for any count instead."""
    load = [k for k, n in wf.items() if n["class_type"] == "LoadImage"]
    scale = next(k for k, n in wf.items() if n["class_type"] == "ImageScaleToTotalPixels")
    enc = next(k for k, n in wf.items() if n["class_type"] == "VAEEncode")
    guider = next(k for k, n in wf.items() if n["class_type"] == "CFGGuider")
    first = wf[scale]["inputs"]["image"][0]
    for k in load:
        if k != first:
            del wf[k]
    wf[first]["inputs"]["image"] = images[0]
    wf[scale]["inputs"]["upscale_method"] = "lanczos"   # template's nearest-exact aliases the reference
    pos, neg = wf[guider]["inputs"]["positive"], wf[guider]["inputs"]["negative"]
    vae = wf[enc]["inputs"]["vae"]
    for i, img in enumerate(images[1:], 2):
        wf[f"ref{i}_load"] = {"class_type": "LoadImage", "inputs": {"image": img}}
        wf[f"ref{i}_scale"] = {"class_type": "ImageScaleToTotalPixels",
                               "inputs": {**wf[scale]["inputs"], "image": [f"ref{i}_load", 0]}}
        wf[f"ref{i}_enc"] = {"class_type": "VAEEncode", "inputs": {"pixels": [f"ref{i}_scale", 0], "vae": vae}}
        wf[f"ref{i}_pos"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [f"ref{i}_enc", 0]}}
        wf[f"ref{i}_neg"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg, "latent": [f"ref{i}_enc", 0]}}
        pos, neg = [f"ref{i}_pos", 0], [f"ref{i}_neg", 0]
    wf[guider]["inputs"]["positive"], wf[guider]["inputs"]["negative"] = pos, neg


def _title(n: dict) -> str:
    return n.get("_meta", {}).get("title", "")


def _drop(wf: dict, *class_types: str) -> None:
    """Remove UI-only nodes (previews/compares) nothing else reads from."""
    referenced = {v[0] for n in wf.values() for v in n["inputs"].values() if isinstance(v, list) and len(v) == 2}
    for k in [k for k, n in wf.items() if n["class_type"] in class_types and k not in referenced]:
        del wf[k]


def _prompt_switch(wf: dict, prompt: str, enhance: bool) -> None:
    """Qwen templates: a ComfySwitchNode chooses between the literal prompt (on_false) and the in-graph prompt
    enhancer's rewrite (on_true, a TextGenerate node fed the same prompt)."""
    comfy.patch(wf, "TextGenerate", "prompt", prompt)
    sw = [n for n in wf.values() if n["class_type"] == "ComfySwitchNode" and isinstance(n["inputs"].get("on_false"), str)]
    if len(sw) != 1:
        raise RefkitError(f"refkit: expected one prompt switch in the Qwen workflow, found {len(sw)} — re-export it")
    sw[0]["inputs"]["on_false"], sw[0]["inputs"]["switch"] = prompt, enhance


def _latent_size(wf: dict, w: int, h: int) -> None:
    comfy.patch(wf, "EmptyLatentImage", "width", w)
    comfy.patch(wf, "EmptyLatentImage", "height", h)


def qwen_refs(wf: dict, images: list[str]) -> None:
    """Qwen Image 2.1 edit: every reference goes into the encoder's autogrow `images.image_N` inputs (the model
    refers to them as <image1>, <image2>, …) and into the batch the prompt enhancer looks at."""
    enc = next(k for k, n in wf.items() if n["class_type"] == "TextEncodeQwenImage21" and n["inputs"].get("clip"))
    batch = next(k for k, n in wf.items() if n["class_type"] == "BatchImagesNode")
    for k in [k for k, n in wf.items() if n["class_type"] in ("LoadImage", "ImageCompare")]:
        del wf[k]
    for node, prefix in ((enc, "images.image_"), (batch, "images.image")):
        for key in [k for k in wf[node]["inputs"] if k.startswith(prefix)]:
            del wf[node]["inputs"][key]
    for i, img in enumerate(images):
        wf[f"ref{i + 1}"] = {"class_type": "LoadImage", "inputs": {"image": img}}
        wf[enc]["inputs"][f"images.image_{i + 1}"] = [f"ref{i + 1}", 0]
        wf[batch]["inputs"][f"images.image{i}"] = [f"ref{i + 1}", 0]


def build(model: str, prompt: str, images: list[str], size: str | None, seed: int, prefix: str,
          enhance: bool = False) -> dict:
    spec = MODELS[model]
    wf = comfy.load_workflow(spec["workflow"] + ".api")
    w, h = parse_size(size or "1024x1024", spec["multiple"])
    if model == "z-image":
        # The negative branch is ConditioningZeroOut (cfg 1), so the single CLIPTextEncode is the prompt.
        comfy.patch(wf, "CLIPTextEncode", "text", prompt)
        comfy.patch(wf, "EmptySD3LatentImage", "width", w)
        comfy.patch(wf, "EmptySD3LatentImage", "height", h)
    elif model == "klein-edit":
        comfy.patch(wf, "CLIPTextEncode", "text", prompt)
        comfy.patch(wf, "ImageScaleToTotalPixels", "megapixels", round(w * h / 1_000_000, 2))
        klein_refs(wf, images)
    elif model == "qwen":
        _prompt_switch(wf, prompt, enhance)
        _latent_size(wf, w, h)
        _drop(wf, "ResolutionSelector")
    elif model == "qwen-edit":
        _prompt_switch(wf, prompt, enhance)
        qwen_refs(wf, images)
        # Output size: the first reference's own size, unless --size was given.
        size_switch = next(n for n in wf.values() if n["class_type"] == "ComfySwitchNode"
                           and isinstance(n["inputs"].get("on_true"), list)
                           and wf[n["inputs"]["on_true"][0]]["class_type"] == "EmptyLatentImage")
        size_switch["inputs"]["switch"] = size is not None
        _latent_size(wf, w, h)
    elif model == "krea":
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveStringMultiline" and "User Prompt" in _title(n), "value", prompt)
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "Refine Prompt" in _title(n), "value", enhance)
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "LoRA" in _title(n), "value", False)
        _latent_size(wf, w, h)
        _drop(wf, "ResolutionSelector")
    seed_all(wf, seed)
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", prefix, expect=None)
    return wf


def sidecar(path: Path, **meta) -> None:
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def main(args) -> list[Path]:
    if args.list:
        for name, m in MODELS.items():
            where = f"cloud: Nano Banana {m['cloud']}" if m.get("cloud") else m["workflow"]
            print(f"{name:12s} {where}{'  (needs -i)' if m['needs_image'] else ''}")
        return []
    if getattr(args, "recipe", None):
        print(prompting.recipe(args.recipe))
        return []
    if not args.prompt:
        raise RefkitError("refkit: gen needs a prompt (or --list / --recipe MODEL)")
    model = args.model or ("qwen-edit" if args.image else "z-image")
    if model not in MODELS:
        raise RefkitError(f"refkit: unknown model {model!r}; choose from {', '.join(MODELS)}")
    for tip in prompting.lint(model, args.prompt):
        log(f"prompt tip: {tip}")
    if MODELS[model].get("cloud"):
        return banana(model, args)
    if MODELS[model]["needs_image"] and not args.image:
        raise RefkitError(f"refkit: {model} needs -i <reference image>")
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    refs = [str(Path(p.strip()).resolve()) for p in args.image.split(",")] if args.image else []
    images = [comfy.upload(Path(p)) for p in refs]
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    seeds = [(args.seed + i) if args.seed is not None else random.randrange(2**48) for i in range(args.count)]
    # Queue every variation first so ComfyUI keeps the model loaded and runs them back to back.
    jobs = [comfy.submit(build(model, args.prompt, images, args.size, s, f"refkit/{model}", args.enhance)) for s in seeds]
    outs = []
    for seed, job in zip(seeds, jobs):
        for item in comfy.wait(job):
            if item.get("type") == "output":
                p = comfy.fetch(item, dest)
                final = p.with_name(f"{model}-{seed}{p.suffix}")
                p.replace(final)
                sidecar(final, model=model, prompt=args.prompt, seed=seed, size=args.size, refs=refs)
                outs.append(final)
                log(f"{final}  (seed {seed})")
    if getattr(args, "pick", False) and len(outs) > 1:
        from . import score
        score.rank(args.prompt, outs, dest)
    return outs
