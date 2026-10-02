"""refkit to3d: image -> textured GLB, cleaned and web-optimised, with a thumbnail.

  pixal3d     Pixal3D (TRELLIS.2 family) textured PBR mesh, best image alignment   [default]
  trellis2    TRELLIS.2 textured PBR mesh
  hunyuan3d   Hunyuan3D 2.1, geometry only (no texture); lightest on VRAM

Input with a real alpha channel (e.g. a `refkit cutout` result) is used as-is: the workflow's own background
removal is switched off, so `cutout --prompt "the left cup"` -> to3d builds that cup, not the most salient object.

Textured models are decimated to --tris inside the graph *before* UV unwrap and baking, so the Blender pass only
welds/cleans and keeps the baked shading (re-decimating after the bake distorts UVs and breaks the normal map).
Then: gltf-transform optimize (meshopt + webp textures) -> f3d thumbnail -> `refkit inspect` views sheet.

--quality picks the graph's detail settings (QUALITY below); --hard-edges keeps creases (QEM decimation, normals split
above 45 deg) for boxy hard-surface objects — curved parts then look faceted, so not for round things. Each run goes to its own folder <out>/<model>-<seed>/ with a
model.json sidecar; -n N runs N seeds and stacks their inspect sheets into compare.png, best first by fidelity
(Pixal3D: the photo's viewpoint rendered from the camera-frame mesh vs the cutout, fidelity.py).
--delight: Marigold V2 albedo (ComfyUI core template) takes the photo's lighting and highlights out of the input
first, so they don't get baked into the texture; the cutout's alpha is put back on the albedo.
--refine-views (Pixal3D): redraws the first mesh's left/back/right views in the original's look and rebuilds it
with Pixal3D multi-view — better backs and sides (multiview.py); both meshes land in compare.png.
"""
from __future__ import annotations

import random
import re
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import comfy, gpu, meta
from .common import MODELS as MODELS_DIR
from .common import RefkitError, log, open_image, out_dir, run
from .multiview import flatten
from .render import blender

MOGE3 = "moge_3_vitg_fp16.safetensors"
MODELS = {
    "pixal3d": {"workflow": "3d_pixal3d_trellis2_image_to_model", "trellis2": False},
    "trellis2": {"workflow": "3d_pixal3d_trellis2_image_to_model", "trellis2": True},
    "hunyuan3d": {"workflow": "3d_hunyuan3d-v2.1", "trellis2": None},
}

# Graph detail per --quality (Pixal3D / TRELLIS.2 graphs), chosen by a same-seed sweep on 2026-10-01 (mug, camera,
# fox; RTX 4080 SUPER 16 GB): structure = sparse-structure grid, upsample = shape cascade resolution, smooth = Taubin
# passes after the dual-contouring remesh, qef = QEF vertex placement in that remesh.
#   standard: 3 smoothing passes + QEF instead of the template's 20 passes — crisper dials, lens knurling and body
#             edges on the camera, identical on the smooth mug; same time and VRAM (~12 GB).
#   high:     shape cascade 1536 — more fine detail on detailed objects but lumpier smooth surfaces; ~15% slower,
#             ~14 GB peak. Structure grid 64 was tried and dropped: 636 s, 15.3 GB, a broken fragment of a mesh.
QUALITY = {
    "standard": {"structure": 32, "upsample": 1024, "smooth": 3, "qef": True},
    "high": {"structure": 32, "upsample": 1536, "smooth": 3, "qef": True},
}


def has_alpha(path: Path) -> bool:
    im = Image.open(path)
    if im.mode not in ("RGBA", "LA", "PA") and not (im.mode == "P" and "transparency" in im.info):
        return False
    a = np.array(im.convert("RGBA"))[..., 3]
    return bool((a < 250).mean() > 0.01)   # at least 1% (semi-)transparent pixels = a real cutout


def tune(wf: dict, texture: int, tris: int, quality: str, hard_edges: bool) -> None:
    """Detail settings shared by the single- and multi-view Pixal3D/TRELLIS.2 graphs."""
    # Comfy Kitchen attention on the samplers: ~10-16% faster here, geometry within run-to-run noise in the
    # 2026-10-01 A/B (ComfyUI 0.38 + comfy-kitchen 0.2.36; mean surface drift 0.26-0.29% vs 0.25% between two
    # plain runs). ComfyUI issue #16027 reports corruption on older builds: the golden set re-checks it.
    comfy.kitchen_attention(wf)
    # MoGe 3 instead of the template's MoGe 2 for the field-of-view estimate: better silhouette and DINO match
    # on both test objects (mug 0.968->0.980 / 0.875->0.888, camera 0.972->0.989 / 0.922->0.939; 2026-10-02).
    # (the multi-view graph has no MoGe: its views come with a fixed fov)
    if (MODELS_DIR / "geometry_estimation" / MOGE3).exists() and any(
            n["class_type"] == "LoadMoGeModel" for n in wf.values()):
        comfy.patch(wf, "LoadMoGeModel", "model_name", MOGE3, expect=None)
    q = QUALITY[quality]
    comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveInt" and comfy.title(n) == "Texture Resolution", "value", texture)
    comfy.patch(wf, "VaeDecodeStructureTrellis2", "resolution", str(q["structure"]))
    comfy.patch(wf, "Trellis2UpsampleStage", "target_resolution", str(q["upsample"]))
    comfy.patch(wf, "RemeshMesh", "smooth_iters", q["smooth"])
    comfy.patch(wf, "RemeshMesh", "sign_mode.qef", q["qef"])
    # Final budget before unwrap + bake (see module docstring).
    comfy.patch(wf, "DecimateMesh", "target_face_count", tris)
    # The normal map follows --texture (the template fixes it at 2048). AO is soft, low-frequency shading: it stays
    # at the template's 1024 (smaller for smaller textures): baking it at 2048 made a teapot run 125/129 s instead
    # of 72 s (2026-10-02 A/B, same seed, everything else equal; ComfyUI execution time).
    comfy.patch(wf, "BakeNormalMapFromMesh", "resolution", texture)
    comfy.patch(wf, "BakeAmbientOcclusion", "resolution", min(texture, 1024))
    if hard_edges:   # crisp box edges and creases; curved parts turn visibly faceted (QEM decimation)
        dec = next(n for n in wf.values() if n["class_type"] == "DecimateMesh")
        dec["inputs"].update({"placement_mode": "qem", "placement_mode.line_quadric_weight": 1.0,
                              "placement_mode.feature_edge_quadric_weight": 10.0,
                              "placement_mode.feature_edge_min_dihedral_deg": 30.0,
                              "placement_mode.clamp_v_to_edge": True})
        comfy.patch(wf, "MeshSmoothNormals", "crease_angle", 45, expect=None)


def build(model: str, image: str, seed: int, texture: int, tris: int, prefix: str, use_alpha: bool,
          quality: str = "standard", hard_edges: bool = False) -> dict:
    spec = MODELS[model]
    wf = comfy.load_workflow(spec["workflow"] + ".api")
    comfy.patch(wf, "LoadImage", "image", image)
    comfy.patch(wf, "KSampler", "seed", seed, expect=None)
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", prefix, expect=None)
    if spec["trellis2"] is not None:
        comfy.patch(wf, lambda n: n["class_type"] == "PrimitiveBoolean" and "Trellis2" in comfy.title(n), "value",
                    bool(spec["trellis2"]))
        tune(wf, texture, tris, quality, hard_edges)
        if use_alpha:
            sw = next(k for k, n in wf.items() if n["class_type"] == "ComfySwitchNode" and "background" in comfy.title(n).lower())
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
    comfy.drop_ui(wf, "Preview3DAdvanced", "PreviewImage", "MaskPreview")   # preview sinks only feed the UI
    return wf


VIEWS = ("front", "left", "back", "right")


def build_views(views: list[Path], seed: int, texture: int, tris: int, prefix: str, quality: str = "standard",
                hard_edges: bool = False, framed: bool = False) -> dict:
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
        to_mask = upstream(link[0], "ImageCropToMask") if i < len(views) and not framed and has_alpha(views[i]) else None
        if (i >= len(views) or framed) and wf[link[0]]["class_type"].startswith("Save"):
            del wf[link[0]]   # the template's per-view "save the crop" node; prune() keeps every Save*
        if i >= len(views):
            del wf[cond]["inputs"][view]   # unused view: its chain becomes unreferenced and is pruned below
            continue
        wf[crop] = {"class_type": "LoadImage", "inputs": {"image": comfy.upload(views[i])}}
        if framed:   # already on the rig (same scale in every view, on black): no per-view crop to its silhouette
            wf[cond]["inputs"][view] = [crop, 0]
        elif to_mask:
            wf[f"inv_{view}"] = {"class_type": "InvertMask", "inputs": {"mask": [crop, 1]}}
            wf[to_mask]["inputs"]["masks"] = [f"inv_{view}", 0]
    comfy.patch(wf, "KSampler", "seed", seed, expect=None)
    tune(wf, texture, tris, quality, hard_edges)
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", prefix, expect=None)
    # Prune everything no output depends on (the sheet loader, unused views, UI previews).
    return comfy.prune(wf)


def delight(src: Path, dest: Path) -> Path:
    """Albedo (lighting-free colour) of a cutout, with the cutout's alpha: the to3d input for --delight."""
    wf = comfy.load_workflow("image_marigold_v2_albedo_estimation.api")
    comfy.patch(wf, "LoadImage", "image", comfy.upload(flatten(src, dest)))
    comfy.patch(wf, lambda n: "filename_prefix" in n["inputs"], "filename_prefix", "refkit/albedo", expect=None)
    comfy.prune(wf)   # drops the before/after compare node
    comfy.kitchen_attention(wf)
    albedo = open_image(comfy.first_output(wf, dest, "Marigold albedo produced no image")).convert("RGB")
    im = open_image(src).convert("RGBA")
    out = dest / f"{src.stem}-albedo.png"
    Image.merge("RGBA", (*albedo.resize(im.size, Image.LANCZOS).split(), im.getchannel("A"))).save(out)
    log(f"delit input -> {out.name}")
    return out


def generate(src: Path, base: Path, model: str, seed: int, alpha: bool, args) -> tuple[Path, float]:
    """One seed through the ComfyUI graph -> <base>/<model>-<seed>/<model>-raw.glb. Several seeds run back to back
    before any Blender step, so the models stay loaded (finish() frees VRAM for Cycles)."""
    dest = base / f"{model}-{seed}"
    dest.mkdir(parents=True, exist_ok=True)
    t = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        # Hunyuan reads RGB only; flatten the cutout onto white (its training background).
        upload_src = flatten(src, Path(tmp), bg="white") if model == "hunyuan3d" and alpha else src
        wf = build(model, comfy.upload(upload_src), seed, texture=args.texture, tris=args.tris,
                   prefix=f"refkit/{src.stem}", use_alpha=alpha, quality=args.quality, hard_edges=args.hard_edges)
    raw = _queue_glb(wf, dest / f"{model}-raw.glb", "the 3D workflow")
    gen_s = time.time() - t
    log(f"{model} mesh in {gen_s:.0f}s (seed {seed}) -> {raw.name}")
    return raw, gen_s


def _queue_glb(wf: dict, raw: Path, what: str) -> Path:
    """Run a 3D graph and move its (last) GLB to `raw`."""
    items = [i for i in comfy.queue(wf, timeout=3600) if str(i.get("filename", "")).lower().endswith((".glb", ".gltf"))]
    if not items:
        raise RefkitError(f"refkit: {what} produced no GLB")
    return comfy.fetch(items[-1], raw.parent).replace(raw)


def seeds_for(args) -> list[int]:
    return [args.seed + i if args.seed is not None else random.randrange(2**31) for i in range(args.count)]


def main(args) -> dict:
    if args.views:
        return main_views(args)
    if not args.image:
        raise RefkitError("refkit: to3d needs an image (or --views front,left,back,right)")
    src = Path(args.image).resolve()
    base = out_dir(src, args.out)
    model = args.model or "pixal3d"
    alpha = has_alpha(src)
    if alpha and model != "hunyuan3d":
        log("input has alpha: using it as the subject mask (no background re-segmentation)")
    if args.refine_views and model != "pixal3d":
        raise RefkitError("refkit: --refine-views rebuilds with Pixal3D multi-view; use -m pixal3d")
    if (args.refine_views or args.delight) and not alpha:
        raise RefkitError("refkit: --refine-views / --delight need a cutout (RGBA) as input: run `refkit cutout` first")
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    if args.delight:
        src = delight(src, base)
    if args.auto:
        args.count = max(args.count, 3)
    seeds = seeds_for(args)
    raws = [generate(src, base, model, seed, alpha, args) for seed in seeds]
    textured = MODELS[model]["trellis2"] is not None
    ref = src if alpha and model == "pixal3d" else None   # only Pixal3D is aligned with the photo's camera
    runs = [finish(raw, raw.parent, model, seed, [src], gen_s, textured, args, ref=ref)
            for seed, (raw, gen_s) in zip(seeds, raws)]
    if args.refine_views:
        from . import multiview
        for r in list(runs):
            # The raw graph mesh, not model.glb: the side views must share the photo's camera frame (Pixal3D's
            # multi-view convention); model.glb has been levelled onto its base.
            raw = Path(r["glb"]).parent / f"{model}-raw.glb"
            views = multiview.side_views(src, raw, raw.parent / "views", r["seed"])
            runs.append(run_views(views, base, r["seed"], args, framed=True, ref=src))
    result = summarise(runs, base)
    if args.auto:
        from . import auto
        result |= auto.to3d_loop(src, result["runs"], base)   # the fidelity-sorted order
    return result


def main_views(args) -> dict:
    views = [Path(v.strip()).resolve() for v in args.views.split(",") if v.strip()]
    if not 1 <= len(views) <= 4:
        raise RefkitError("refkit: --views takes 1-4 images in front,left,back,right order")
    base = out_dir(views[0], args.out)
    gpu.free_vram(keep="comfy")
    comfy.ensure_running()
    ref = views[0] if has_alpha(views[0]) else None
    return summarise([run_views(views, base, seed, args, ref=ref) for seed in seeds_for(args)], base)


def run_views(views: list[Path], base: Path, seed: int, args, framed: bool = False, ref: Path | None = None) -> dict:
    """One Pixal3D multi-view run (front, left, back, right order) into <base>/pixal3d-mv-<seed>/."""
    dest = base / f"pixal3d-mv-{seed}"
    dest.mkdir(parents=True, exist_ok=True)
    t = time.time()
    wf = build_views(views, seed, texture=args.texture, tris=args.tris, prefix=f"refkit/{views[0].stem}-mv",
                     quality=args.quality, hard_edges=args.hard_edges, framed=framed)
    raw = _queue_glb(wf, dest / "pixal3d-mv-raw.glb", "the multi-view 3D workflow")
    gen_s = time.time() - t
    log(f"pixal3d multi-view ({len(views)} views) mesh in {gen_s:.0f}s (seed {seed}) -> {raw.name}")
    return finish(raw, dest, "pixal3d-mv", seed, views, gen_s, True, args, ref=ref)


def finish(raw: Path, dest: Path, model: str, seed: int, inputs: list[Path], gen_s: float, textured: bool,
           args, ref: Path | None = None) -> dict:
    """Cleanup/optimise, inspect views, fidelity vs `ref` (the input cutout), sidecar. Returns the run's entry."""
    gpu.free_vram()   # release VRAM before Blender/Cycles needs it
    final, tilt = finish_mesh(raw, dest, model, textured, args)
    run = {"model": model, "seed": seed, "glb": str(final), "thumbnail": str(dest / "model.png"),
           "generate_s": round(gen_s, 1)}
    if args.inspect:
        from . import inspect3d
        stats = inspect3d.inspect(final, dest / "inspect")
        run["sheet"] = stats["sheet"]
        run["stats"] = {k: stats[k] for k in ("tris", "verts", "uv_layers", "boundary_edges", "non_manifold_edges",
                                               "degenerate_faces", "textures")}
    if ref is not None:
        from . import fidelity
        run["fidelity"] = fidelity.score(raw, ref, dest / "fidelity")
    meta.record(final, "to3d", model=model, seed=seed, inputs=inputs, quality=args.quality,
                hard_edges=args.hard_edges or None, texture=args.texture, tris=args.tris,
                levelled_deg=tilt or None,
                files=[raw, dest / "model.png", *([Path(run["sheet"])] if "sheet" in run else [])],
                generate_s=run["generate_s"], stats=run.get("stats"),
                fidelity={k: v for k, v in run.get("fidelity", {}).items() if k != "front"} or None)
    return run


def summarise(runs: list[dict], base: Path) -> dict:
    """-n > 1: stack every run's inspect sheet into compare.png (seed-labelled) to judge side by side."""
    def fid(r):
        # Silhouette to 2 decimals catches gross shape failures (a broken mesh scored 0.69 vs 0.97); between
        # sound meshes its third decimal is noise, so DINO (front appearance) breaks the tie. Both see only the
        # photo's side: backs still need a look at compare.png.
        f = r.get("fidelity") or {}
        return (round(f.get("silhouette") or 0, 2), f.get("dino") or 0)
    if all(r.get("fidelity") for r in runs):
        runs = sorted(runs, key=fid, reverse=True)
    result = {"runs": runs, "outputs": [r["glb"] for r in runs]}
    sheets = [r for r in runs if r.get("sheet")]
    if len(sheets) > 1:
        ims = [Image.open(r["sheet"]).convert("RGB") for r in sheets]
        out = Image.new("RGB", (max(i.width for i in ims), sum(i.height + 26 for i in ims)), "#2a2a2e")
        d, y = ImageDraw.Draw(out), 0
        font = ImageFont.load_default(size=18)
        for r, im in zip(sheets, ims):
            f = r.get("fidelity") or {}
            score = f"   silhouette {f['silhouette']}  DINO {f.get('dino')}" if f else ""
            d.text((8, y + 3), f"{r['model']} seed {r['seed']}{score}", fill="#f2f2f2", font=font)
            out.paste(im, (0, y + 26))
            y += im.height + 26
        compare = base / "compare.png"
        out.save(compare)
        result["compare"] = str(compare)
        log(f"{len(sheets)} runs -> {compare} (look at it and pick)")
    return result


def finish_mesh(raw: Path, dest: Path, model: str, textured: bool, args) -> tuple[Path, float]:
    """Blender cleanup -> gltf-transform (meshopt + WebP, or KTX2 for GPU-compressed textures) -> f3d thumbnail."""
    clean = dest / f"{model}-clean.glb"
    extra = ["--keep-shading"] if textured and args.material == "keep" else []
    extra += [] if args.level else ["--no-level"]
    out = blender("cleanup.py", "--input", raw, "--output", clean, "--tris", args.tris, "--material", args.material, *extra)
    done = next((ln for ln in out.splitlines() if ln.startswith("CLEANUP-DONE")), "cleanup done")
    log(done)
    tilt = re.search(r"levelled=([\d.]+)deg", done)

    final = dest / "model.glb"
    # KTX2 keeps textures compressed on the GPU (less VRAM in three.js); WebP is smaller to download.
    tex = "ktx2" if args.ktx2 else "webp"
    run(["gltf-transform", "optimize", clean, final, "--compress", "meshopt", "--texture-compress", tex,
         "--texture-size", str(min(args.texture, 4096)), "--simplify", "false"])
    thumb = dest / "model.png"
    # f3d can't read meshopt-compressed GLBs; the pre-compression mesh is the same geometry.
    run(["f3d", clean, "--output", thumb, "--resolution", "1024,1024", "--no-background",
         "--filename=false", "--grid=false", "--axis=false"], check=False)
    if not thumb.exists():
        log("thumbnail failed (f3d); use `refkit render model.glb --frames 1` instead")
    log(f"final {final} ({final.stat().st_size / 1024:.0f} KB, {tex} textures), thumbnail {thumb.name}")
    return final, float(tilt.group(1)) if tilt else 0.0
