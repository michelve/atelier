"""refkit to3d: image -> textured GLB, cleaned and web-optimised, with a thumbnail.

  pixal3d     Pixal3D (TRELLIS.2 family) textured PBR mesh, best image alignment   [default]
  trellis2    TRELLIS.2 textured PBR mesh
  hunyuan3d   Hunyuan3D 2.1, geometry only (no texture); lightest on VRAM

Input with a real alpha channel (e.g. a `refkit cutout` result) is used as-is: the workflow's own background
removal is switched off, so `cutout --prompt "the left cup"` -> to3d builds that cup, not the most salient object.

Textured models are decimated to --tris inside the graph *before* UV unwrap and baking, so the Blender pass only
welds/cleans and keeps the baked shading (re-decimating after the bake distorts UVs and breaks the normal map).
Then: gltf-transform optimize (meshopt + webp textures) -> f3d thumbnail.
"""
from __future__ import annotations

import random
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import comfy, gpu
from .common import RefkitError, log, open_image, out_dir, run
from .render import blender

MODELS = {
    "pixal3d": {"workflow": "3d_pixal3d_trellis2_image_to_model", "trellis2": False},
    "trellis2": {"workflow": "3d_pixal3d_trellis2_image_to_model", "trellis2": True},
    "hunyuan3d": {"workflow": "3d_hunyuan3d-v2.1", "trellis2": None},
}


def has_alpha(path: Path) -> bool:
    im = Image.open(path)
    if im.mode not in ("RGBA", "LA", "PA") and not (im.mode == "P" and "transparency" in im.info):
        return False
    a = np.array(im.convert("RGBA"))[..., 3]
    return bool((a < 250).mean() > 0.01)   # at least 1% (semi-)transparent pixels = a real cutout


def title(n: dict) -> str:
    return n.get("_meta", {}).get("title", "")


def build(model: str, image: str, seed: int, texture: int, upsample: int, tris: int, prefix: str,
          use_alpha: bool) -> dict:
    spec = MODELS[model]
    wf = comfy.load_workflow(spec["workflow"] + ".api")
    comfy.patch(wf, "LoadImage", "image", image)
    comfy.patch(wf, "KSampler", "seed", seed, expect=None)
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", prefix, expect=None)
    if spec["trellis2"] is not None:
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "Trellis2" in title(n), "value",
                    bool(spec["trellis2"]))
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveInt" and title(n) == "Texture Resolution", "value", texture)
        # 1536 is the template default and peaks above 16 GB; 1024 fits the 4080 SUPER.
        comfy.patch(wf, "Trellis2UpsampleStage", "target_resolution", str(upsample))
        # Final budget before unwrap + bake (see module docstring).
        comfy.patch(wf, "DecimateMesh", "target_face_count", tris)
        if use_alpha:
            sw = next(k for k, n in wf.items() if n["class_type"] == "ComfySwitchNode" and "background" in title(n).lower())
            load = next(k for k, n in wf.items() if n["class_type"] == "LoadImage")
            # LoadImage's MASK output is 1 - alpha; the crop node wants subject = 1.
            wf["refkit_invert"] = {"class_type": "InvertMask", "inputs": {"mask": [load, 1]}}
            wf[sw]["inputs"]["switch"] = False
            wf[sw]["inputs"]["on_false"] = ["refkit_invert", 0]
    else:
        # Hunyuan's SaveGLB lost its `image` input in ComfyUI 0.38.
        for n in wf.values():
            if n["class_type"] == "SaveGLB":
                n["inputs"].pop("image", None)
    # Preview sinks only feed the UI; drop them to save work, but never one another node takes input from.
    referenced = {v[0] for n in wf.values() for v in n["inputs"].values() if isinstance(v, list) and len(v) == 2}
    for nid in [k for k, n in wf.items()
                if n["class_type"] in ("Preview3DAdvanced", "PreviewImage", "MaskPreview") and k not in referenced]:
        del wf[nid]
    return wf


VIEWS = ("front", "left", "back", "right")


def build_views(views: list[Path], seed: int, texture: int, upsample: int, tris: int, prefix: str) -> dict:
    """Pixal3D multi-view: 1-4 separate views (front, left, back, right order) instead of the template's single
    turnaround sheet. Each crop node becomes a LoadImage of that view; views with alpha skip re-segmentation."""
    wf = comfy.load_workflow("3d_pixal3d_multi_views.api")
    cond = next(k for k, n in wf.items() if n["class_type"] == "Pixal3DMultiViewConditioning")

    def upstream(k: str, cls: str) -> str:
        """Walk back from node k to the first node of class cls."""
        seen, stack = set(), [k]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if wf[cur]["class_type"] == cls:
                return cur
            stack += [v[0] for v in wf[cur]["inputs"].values() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)]
        raise RefkitError(f"refkit: multi-view workflow changed (no {cls} upstream of {k}) — re-export it")

    for i, view in enumerate(VIEWS):
        link = wf[cond]["inputs"].get(view)
        if not link:
            continue
        crop = upstream(link[0], "ImageCropV2")
        to_mask = upstream(link[0], "ImageCropToMask")
        if i >= len(views):
            del wf[cond]["inputs"][view]   # unused view: its chain becomes unreferenced and is pruned below
            continue
        wf[crop] = {"class_type": "LoadImage", "inputs": {"image": comfy.upload(views[i])}}
        if has_alpha(views[i]):
            wf[f"inv_{view}"] = {"class_type": "InvertMask", "inputs": {"mask": [crop, 1]}}
            wf[to_mask]["inputs"]["masks"] = [f"inv_{view}", 0]
    comfy.patch(wf, "KSampler", "seed", seed, expect=None)
    comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveInt" and title(n) == "Texture Resolution", "value", texture)
    comfy.patch(wf, "Trellis2UpsampleStage", "target_resolution", str(upsample))
    comfy.patch(wf, "DecimateMesh", "target_face_count", tris)
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", prefix, expect=None)
    # Prune everything no output depends on (the sheet loader, unused views, UI previews).
    outputs = [k for k, n in wf.items() if n["class_type"] in ("Save3DAdvanced", "SaveGLB")]
    keep, stack = set(), list(outputs)
    while stack:
        cur = stack.pop()
        if cur in keep:
            continue
        keep.add(cur)
        stack += [v[0] for v in wf[cur]["inputs"].values() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)]
    return {k: n for k, n in wf.items() if k in keep}


def main(args) -> Path:
    if args.views:
        return main_views(args)
    if not args.image:
        raise RefkitError("refkit: to3d needs an image (or --views front,left,back,right)")
    src = Path(args.image).resolve()
    dest = out_dir(src, args.out)
    model = args.model or "pixal3d"
    seed = args.seed if args.seed is not None else random.randrange(2**31)
    alpha = has_alpha(src)
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    t = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        upload_src = src
        if model == "hunyuan3d" and alpha:
            # Hunyuan reads RGB only; flatten the cutout onto white (its training background).
            im = open_image(src).convert("RGBA")
            flat = Image.new("RGBA", im.size, "white")
            flat.alpha_composite(im)
            upload_src = Path(tmp) / f"{src.stem}-white.png"
            flat.convert("RGB").save(upload_src)
        wf = build(model, comfy.upload(upload_src), seed, texture=args.texture, upsample=1024, tris=args.tris,
                   prefix=f"refkit/{src.stem}", use_alpha=alpha)
    if alpha:
        log("input has alpha: using it as the subject mask (no background re-segmentation)")
    items = [i for i in comfy.queue(wf, timeout=3600) if str(i.get("filename", "")).lower().endswith((".glb", ".gltf"))]
    if not items:
        raise RefkitError("refkit: the 3D workflow produced no GLB")
    raw = comfy.fetch(items[-1], dest)
    raw = raw.replace(dest / f"{model}-raw.glb")
    log(f"{model} mesh in {time.time() - t:.0f}s (seed {seed}) -> {raw.name}")
    gpu.free_vram()   # release VRAM before Blender/Cycles needs it

    return finish_mesh(raw, dest, model, MODELS[model]["trellis2"] is not None, args)


def main_views(args) -> Path:
    views = [Path(v.strip()).resolve() for v in args.views.split(",") if v.strip()]
    if not 1 <= len(views) <= 4:
        raise RefkitError("refkit: --views takes 1-4 images in front,left,back,right order")
    dest = out_dir(views[0], args.out)
    seed = args.seed if args.seed is not None else random.randrange(2**31)
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    t = time.time()
    wf = build_views(views, seed, texture=args.texture, upsample=1024, tris=args.tris, prefix=f"refkit/{views[0].stem}-mv")
    items = [i for i in comfy.queue(wf, timeout=3600) if str(i.get("filename", "")).lower().endswith((".glb", ".gltf"))]
    if not items:
        raise RefkitError("refkit: the multi-view 3D workflow produced no GLB")
    raw = comfy.fetch(items[-1], dest).replace(dest / "pixal3d-mv-raw.glb")
    log(f"pixal3d multi-view ({len(views)} views) mesh in {time.time() - t:.0f}s (seed {seed}) -> {raw.name}")
    gpu.free_vram()
    return finish_mesh(raw, dest, "pixal3d-mv", True, args)


def finish_mesh(raw: Path, dest: Path, model: str, textured: bool, args) -> Path:
    """Blender cleanup -> gltf-transform (meshopt + WebP, or KTX2 for GPU-compressed textures) -> f3d thumbnail."""
    clean = dest / f"{model}-clean.glb"
    extra = ["--keep-shading"] if textured and args.material == "keep" else []
    out = blender("cleanup.py", "--input", raw, "--output", clean, "--tris", args.tris, "--material", args.material, *extra)
    log(next((ln for ln in out.splitlines() if ln.startswith("CLEANUP-DONE")), "cleanup done"))

    final = dest / "model.glb"
    # KTX2 keeps textures compressed on the GPU (less VRAM in three.js); WebP is smaller to download.
    tex = "ktx2" if getattr(args, "ktx2", False) else "webp"
    run(["gltf-transform", "optimize", clean, final, "--compress", "meshopt", "--texture-compress", tex,
         "--texture-size", str(min(args.texture, 4096)), "--simplify", "false"])
    thumb = dest / "model.png"
    # f3d can't read meshopt-compressed GLBs; the pre-compression mesh is the same geometry.
    run(["f3d", clean, "--output", thumb, "--resolution", "1024,1024", "--no-background",
         "--filename=false", "--grid=false", "--axis=false"], check=False)
    if not thumb.exists():
        log("thumbnail failed (f3d); use `refkit render model.glb --frames 1` instead")
    log(f"final {final} ({final.stat().st_size / 1024:.0f} KB, {tex} textures), thumbnail {thumb.name}")
    return final
