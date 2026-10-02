"""Multi-view refinement for `to3d --refine-views`: better backs and sides from a single image.

  1. single-view Pixal3D mesh (the usual to3d run)
  2. Blender renders it from the front/left/back/right on the Pixal3D multi-view rig (azimuth 0/90/180/270 = camera
     at -Y/+X/+Y/-X, 0 deg elevation, 20 deg fov, unit cube spanning 1/1.1 of the frame: the node needs the same
     framing and scale in every view, so the photo itself can't be the front view)
  3. Qwen-Image 2.1 edit + the AnyAngle LoRA (lilylilith/QI_2.1_AnyAngle, Apache-2.0) redraws each rough render in
     the original's look: "Change the camera angle from <image2> to <image1>." with <image1> = the ORIGINAL and
     <image2> = the rough render (tested 2026-10-01: this order follows the rough's angle, silhouette IoU 0.96-0.97;
     the other order copies the original's angle, IoU 0.59-0.65). LoRA strength 1, CFG 3, the template's 25 steps.
  4. each redraw is cut out and must match its rough render's silhouette (IoU >= MIN_IOU, one retry with another
     seed); a view that still doesn't falls back to the rough render itself (right geometry, plainer look). The
     local critic then checks the four views show one consistent object.
  5. each accepted view is re-framed onto its rig render's bounding box (exact rig scale), composed on black, and
     Pixal3D multi-view runs on the four uncropped views
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import comfy, gen
from .common import RefkitError, log, open_image

ANYANGLE_LORA = "QI2.1_AnyAngle.safetensors"
SIDES = {"front": 0, "left": 90, "back": 180, "right": 270}
PROMPT = "Change the camera angle from <image2> to <image1>."
MIN_IOU = 0.8


def silhouette_iou(a: Path, b: Path) -> float:
    """Overlap of two cutouts' alpha masks after fitting each mask's bounding box to the same square."""
    import numpy as np

    def norm(path):
        m = np.array(open_image(path).convert("RGBA"))[..., 3] > 128
        ys, xs = np.nonzero(m)
        if not len(xs):
            return np.zeros((256, 256), bool)
        crop = Image.fromarray((m[ys.min():ys.max() + 1, xs.min():xs.max() + 1] * 255).astype(np.uint8))
        return np.array(crop.resize((256, 256))) > 127
    x, y = norm(a), norm(b)
    return float((x & y).sum() / max((x | y).sum(), 1))


def flatten(src: Path, dest: Path, bg: str = "#808080") -> Path:
    """RGBA -> RGB on mid grey (edit models read transparency as black)."""
    im = open_image(src).convert("RGBA")
    flat = Image.new("RGBA", im.size, bg)
    flat.alpha_composite(im)
    out = dest / f"{src.stem}-flat.png"
    flat.convert("RGB").save(out)
    return out


def anyangle(original: Path, rough: Path, seed: int, dest: Path, name: str) -> Path:
    wf = gen.build("qwen-edit", PROMPT, [comfy.upload(original), comfy.upload(rough)], None, seed, "refkit/anyangle")
    comfy.add_lora(wf, ANYANGLE_LORA)
    comfy.patch(wf, "KSampler", "cfg", 3.0)
    items = [i for i in comfy.queue(wf) if i.get("type") == "output"]
    if not items:
        raise RefkitError(f"refkit: AnyAngle redraw of the {name} view produced nothing")
    return comfy.fetch(items[0], dest).replace(dest / f"{name}-redrawn.png")


def reframe(cut: Path, rig: Path, out: Path) -> Path:
    """Scale/move the redrawn cutout so its alpha bounding box lands exactly on the rig render's, on black."""
    import numpy as np
    a = open_image(cut).convert("RGBA")
    r = open_image(rig).convert("RGBA")
    box = lambda im: Image.fromarray((np.array(im)[..., 3] > 128).astype(np.uint8) * 255).getbbox()  # noqa: E731
    ab, rb = box(a), box(r)
    canvas = Image.new("RGBA", r.size, (0, 0, 0, 255))
    if ab and rb:
        piece = a.crop(ab).resize((rb[2] - rb[0], rb[3] - rb[1]), Image.LANCZOS)
        canvas.alpha_composite(piece, (rb[0], rb[1]))
    canvas.convert("RGB").save(out)
    return out


def side_views(src: Path, first_glb: Path, dest: Path, seed: int) -> list[Path]:
    """Steps 2-5: returns [front, left, back, right] rig-framed views on black, ready for build_views(framed=True)."""
    from . import cutout, inspect3d
    dest.mkdir(parents=True, exist_ok=True)
    inspect3d.render_views(first_glb, dest / "rough", azimuths=",".join(str(a) for a in SIDES.values()), elev=0,
                           fov=20, rig=True, modes="beauty", res=1024)
    comfy.ensure_running()
    original = flatten(src, dest)
    views = []
    for i, (name, az) in enumerate(SIDES.items()):
        rough_rgba = dest / "rough" / "views" / f"beauty_{az:03d}.png"
        rough = flatten(rough_rgba, dest)
        view = None
        for attempt in range(2):
            redrawn = anyangle(original, rough, seed + i + 100 * attempt, dest, name)
            cut = cutout.cut(redrawn, dest).replace(dest / f"{name}.png")
            iou = silhouette_iou(cut, rough_rgba)
            if iou >= MIN_IOU:
                view = cut
                log(f"{name} view redrawn (silhouette IoU {iou:.2f}) -> {cut.name}")
                break
            log(f"{name} redraw ignored the angle (silhouette IoU {iou:.2f} < {MIN_IOU})"
                + (", retrying with another seed" if attempt == 0 else ""))
        if view is None:
            view = rough_rgba
            log(f"{name}: using the rough render itself")
        views.append(reframe(view, rough_rgba, dest / f"{name}-rig.png"))
    try:
        from . import critique, vlm
        check = critique.consistency(views)
        vlm.unload()
        log("views look consistent" if check["consistent"] else f"views may disagree: {check['problems']} "
            "(look at them before trusting the multi-view mesh)")
    except SystemExit as e:   # critic not installed: Claude looks instead
        log(f"no consistency check ({e})")
    return views
