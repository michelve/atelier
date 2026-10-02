"""refkit gen: image generation. Local through ComfyUI by default; Nano Banana is the approved cloud option.

  z-image      text -> image, Z-Image-Turbo int8: 8 steps, ~3 s, drafts and variations  [default without -i]
  qwen         text -> image, Qwen-Image 2.1 int8: best open model, typography/layout, native 2K, RGBA
  krea         text -> image, Krea 2 Turbo int8: most photographic look (product/catalogue realism)
  qwen-edit    reference image(s) + instruction, Qwen-Image 2.1: best open editor, multi-reference
               (<image1>, <image2>… in the prompt); output keeps the first reference's size unless --size  [default with -i]
               --consistent: Consistency LoRA (ausboss, qwen-research licence) keeps the edit on the source's
               frame (no drift, less repainting); its author notes it resists edits that move things (pose, head
               turn), so it is opt-in
  klein-edit   reference image(s) + instruction, FLUX.2 klein 4B: fast edits (~6 s)
  hidream      text -> image, HiDream-O1 Dev (MIT, pixel-space, native 2K): photoreal alternative to krea/qwen
  hidream-edit reference image + instruction, HiDream-O1 Dev edit mode (keeps the reference's size, /32)
  ming         text -> image, Ming-Image-0.1-Design (MIT): posters, UI screens, infographics, ~6 s warm; renders the
               text you quote exactly, invents gibberish for text you don't — spell out every visible word
  krea-style   text -> image in the look of a style reference (-i style.png), Krea 2 Turbo + its style-reference
               LoRA: the reference's medium/palette/brushwork, not its content
  banana       Google Nano Banana 2 (cloud, own key, paid; --yes) - 4K, up to 14 refs, dense exact text
  banana-pro   Google Nano Banana Pro (cloud, ~2x NB2's price, ranks below it) - only if NB2 fails a layout
Every -i image (comma-separated) is a reference, in order. --enhance turns on the template's own prompt enhancer
(Qwen/Krea; loads an extra 9B/4B model). `--recipe MODEL` prints how to prompt it. Qwen-Image 2.1 and Krea 2 are
licensed for personal / non-commercial use (Krea: < $1M revenue).
"""
from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

from . import comfy, gpu, meta, prompting
from .common import REPO, RefkitError, log, say

NANOBANANA = REPO / "nanobanana.py"
CONSISTENCY_LORA = "qwen-image-2.1-consistency.safetensors"

MODELS = {
    "z-image": {"workflow": "image_z_image_turbo_int8", "needs_image": False, "multiple": 16},
    "qwen": {"workflow": "image_qwen_image_2_1_t2i", "needs_image": False, "multiple": 32},
    "krea": {"workflow": "image_krea2_turbo_t2i_int8", "needs_image": False, "multiple": 16},
    "qwen-edit": {"workflow": "image_qwen_image_2_1_image_edit", "needs_image": True, "multiple": 32},
    "klein-edit": {"workflow": "image_flux2_klein_image_edit_4b_distilled", "needs_image": True, "multiple": 16},
    "krea-style": {"workflow": "image_krea2_turbo_int8_image_style_reference", "needs_image": True, "multiple": 16},
    "hidream": {"workflow": "image_hidream_o1_dev", "needs_image": False, "multiple": 32},
    "ming": {"workflow": "image_ming_image_01_design_t2i", "needs_image": False, "multiple": 16},
    "hidream-edit": {"workflow": "image_hidream_o1_dev", "needs_image": True, "multiple": 32},
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
        meta.record(out, "gen", model=model, prompt=args.prompt, aspect=aspect, paid=True,
                    refs=args.image.split(",") if args.image else None,
                    inputs=[Path(i) for i in args.image.split(",")] if args.image else None)
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


def img2img(wf: dict, image: str, denoise: float) -> dict:
    """Z-Image text->image graph -> img2img: the empty latent becomes the encoded (uploaded) `image`."""
    latent = next(k for k, n in wf.items() if n["class_type"] == "EmptySD3LatentImage")
    vae = next(n["inputs"]["vae"] for n in wf.values() if n["class_type"] == "VAEDecode")
    wf["img2img_load"] = {"class_type": "LoadImage", "inputs": {"image": image}}
    wf[latent] = {"class_type": "VAEEncode", "inputs": {"pixels": ["img2img_load", 0], "vae": vae}}
    comfy.patch(wf, "KSampler", "denoise", denoise)
    return wf


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


def hidream(wf: dict, prompt: str, images: list[str], w: int, h: int, enhance: bool, edit: bool) -> None:
    """HiDream-O1 Dev: one graph, a 'Switch to Image Edit' boolean picks text->image (empty latent at w x h) or edit
    (reference image, latent at its size). For text->image the edit branch is cut out entirely, so its sample
    LoadImage never has to exist on the server."""
    comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveStringMultiline" and comfy.title(n) == "User Prompt", "value", prompt)
    comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "Prompt Refine" in comfy.title(n), "value", enhance)
    comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "Image Edit" in comfy.title(n), "value", edit)
    if not enhance:   # cut the Gemma rewriter branch out (ComfyUI validates both sides of a switch)
        for n in wf.values():
            if n["class_type"] == "ComfySwitchNode" and isinstance(n["inputs"].get("switch"), list) \
                    and "Prompt Refine" in comfy.title(wf[n["inputs"]["switch"][0]]):
                n["inputs"]["on_true"] = n["inputs"]["on_false"]
    if edit:
        comfy.patch(wf, "LoadImage", "image", images[0])
        comfy.prune(wf)
        return
    for n in wf.values():   # the rewriter also looks at the reference image in edit mode
        if n["class_type"] == "TextGenerate":
            n["inputs"].pop("image", None)
    empty = [k for k, n in wf.items() if n["class_type"] == "EmptyHiDreamO1LatentImage"
             and not isinstance(n["inputs"].get("width"), list)]
    if len(empty) != 1:
        raise RefkitError("refkit: HiDream workflow changed (text->image latent not found) — re-export it")
    wf[empty[0]]["inputs"].update(width=w, height=h)
    for n in wf.values():   # every edit/t2i switch now takes its text->image input
        if n["class_type"] == "ComfySwitchNode" and isinstance(n["inputs"].get("switch"), list) \
                and wf[n["inputs"]["switch"][0]]["class_type"] == "PrimitiveBoolean" \
                and "Image Edit" in comfy.title(wf[n["inputs"]["switch"][0]]):
            n["inputs"]["on_true"] = n["inputs"]["on_false"]
    comfy.prune(wf)


def build(model: str, prompt: str, images: list[str], size: str | None, seed: int, prefix: str,
          enhance: bool = False, consistent: bool = False) -> dict:
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
        comfy.drop_ui(wf, "ResolutionSelector")
    elif model == "qwen-edit":
        _prompt_switch(wf, prompt, enhance)
        qwen_refs(wf, images)
        # Output size: the first reference's own size, unless --size was given.
        size_switch = next(n for n in wf.values() if n["class_type"] == "ComfySwitchNode"
                           and isinstance(n["inputs"].get("on_true"), list)
                           and wf[n["inputs"]["on_true"][0]]["class_type"] == "EmptyLatentImage")
        size_switch["inputs"]["switch"] = size is not None
        _latent_size(wf, w, h)
        if consistent:
            comfy.add_lora(wf, CONSISTENCY_LORA)
    elif model == "krea":
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveStringMultiline" and "User Prompt" in comfy.title(n), "value", prompt)
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "Refine Prompt" in comfy.title(n), "value", enhance)
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "LoRA" in comfy.title(n), "value", False)
        _latent_size(wf, w, h)
        comfy.drop_ui(wf, "ResolutionSelector")
    elif model == "ming":
        if enhance:
            log("ming: --enhance needs the template's 27B rewriter (not installed); using the prompt as written")
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveStringMultiline" and comfy.title(n) == "Text (User Input)",
                    "value", prompt)
        sw = next(n for n in wf.values() if n["class_type"] == "ComfySwitchNode")
        sw["inputs"]["switch"], sw["inputs"]["on_true"] = False, sw["inputs"]["on_false"]   # cut the rewriter branch
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveInt" and comfy.title(n) == "width", "value", w)
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveInt" and comfy.title(n) == "height", "value", h)
        comfy.prune(wf)
    elif model in ("hidream", "hidream-edit"):
        hidream(wf, prompt, images, w, h, enhance, edit=model == "hidream-edit")
    elif model == "krea-style":
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveStringMultiline" and "User Prompt" in comfy.title(n), "value", prompt)
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "Refine Prompt" in comfy.title(n), "value", enhance)
        comfy.patch(wf, "LoadImage", "image", images[0])
        # The size comes from a ResolutionSelector feeding both latents and ModelSamplingFlux: set the numbers.
        comfy.patch(wf, "EmptyLatentImage", "width", w, expect=None)
        comfy.patch(wf, "EmptyLatentImage", "height", h, expect=None)
        comfy.patch(wf, "ModelSamplingFlux", "width", w)
        comfy.patch(wf, "ModelSamplingFlux", "height", h)
        comfy.drop_ui(wf, "ResolutionSelector")
    seed_all(wf, seed)
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", prefix, expect=None)
    # Comfy Kitchen attention: 14-18% faster for qwen/krea/klein/qwen-edit (warm, same seeds, 2026-10-01); no gain
    # for Z-Image's 8 steps and the largest picture change, so Z-Image stays on PyTorch attention.
    if model != "z-image":
        comfy.kitchen_attention(wf)
    return wf


def main(args) -> dict | list:
    if args.list:
        for name, m in MODELS.items():
            where = f"cloud: Nano Banana {m['cloud']}" if m.get("cloud") else m["workflow"]
            say(f"{name:12s} {where}{'  (needs -i)' if m['needs_image'] else ''}")
        return []
    if args.recipe:
        say(prompting.recipe(args.recipe))
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
    if args.auto:
        from . import auto
        args.count, args.pick = max(args.count, 4), True
        return auto.gen_loop(args, lambda offset: batch(args, model, images, refs, dest, offset))
    return batch(args, model, images, refs, dest)


def batch(args, model: str, images: list[str], refs: list[str], dest: Path, offset: int = 0) -> dict:
    """One batch of args.count variations (seed, seed+1, …; offset shifts them for another round)."""
    seeds = [(args.seed + offset + i) if args.seed is not None else random.randrange(2**48) for i in range(args.count)]
    # Queue every variation first so ComfyUI keeps the model loaded and runs them back to back.
    jobs = [comfy.submit(build(model, args.prompt, images, args.size, s, f"refkit/{model}", args.enhance,
                               args.consistent)) for s in seeds]
    outs = []
    for seed, job in zip(seeds, jobs):
        items = comfy.wait(job)
        # The templates show the prompt actually used in a preview node: the enhancer's rewrite with --enhance.
        used = next((t for t in comfy.TEXTS.get(job, []) if t.strip()), None)
        enhanced = used if args.enhance and used and used.strip() != args.prompt.strip() else None
        for item in items:
            if item.get("type") == "output":
                p = comfy.fetch(item, dest)
                final = p.with_name(f"{model}-{seed}{p.suffix}")
                p.replace(final)
                meta.record(final, "gen", model=model, prompt=args.prompt, seed=seed, size=args.size,
                            enhance=args.enhance or None, enhanced_prompt=enhanced, workflow=MODELS[model]["workflow"],
                            consistent=args.consistent or None,
                            refs=refs or None, inputs=[Path(r) for r in refs])
                outs.append(final)
                log(f"{final}  (seed {seed})")
    result = {"outputs": [str(o) for o in outs], "model": model, "licence": meta.LICENCES.get(model), "seeds": seeds}
    from .qa import read_text, text_check, wanted_text
    if wanted_text(args.prompt):
        read = read_text(outs)
        checks = {str(o): text_check(o, args.prompt, read[str(o)]) for o in outs}
        for o, rows in checks.items():
            missing = [r["text"] for r in rows if not r["found"]]
            if missing:
                log(f"text check: {Path(o).name} is missing/misspelling {missing} ({rows[0]['reader']})")
        result["text_check"] = checks
    if args.pick and len(outs) > 1:
        from . import score
        name = f"contact-{offset // 1000 + 1}.png" if offset else "contact.png"
        is_edit = model in ("qwen-edit", "klein-edit", "hidream-edit")
        ranked = score.rank(args.prompt, outs, dest, source=Path(refs[0]) if refs and is_edit else None, name=name)
        result["ranked"] = [{"path": str(p), "score": s} for p, s in ranked]
        result["contact"] = str(dest / name)
    return result
