"""How well a 3D result matches its input image, seen from the input's own camera.

Pixal3D builds the mesh in the photo's camera frame, so the raw graph mesh rendered from azimuth 0 / elevation 0 on
the Pixal3D rig is the photo's viewpoint. Two scores against the input cutout:
  silhouette  IoU of the two alpha masks after fitting both to the same box (shape and proportions)
  dino        cosine similarity of DINOv2-base embeddings, both on mid grey (appearance: colour, parts, texture)
`to3d -n` sorts its runs by these (silhouette first) and prints them on compare.png. Scores rank seeds of the same
input; they are not comparable across different inputs. CLIP is deliberately not used (chance-level for 3D in a
2026 study); a DINO score is a visual proxy, so the art director still looks at the sheets.
Weights: facebook/dinov2-base (Apache-2.0, ~350 MB) in <engine>\\models\\scoring.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from .common import MODELS, log
from .multiview import silhouette_iou

DINO = "facebook/dinov2-base"
_dino = None


def _on_grey(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (128, 128, 128, 255))
    bg.alpha_composite(im)
    box = im.getchannel("A").point(lambda a: 255 if a > 128 else 0).getbbox()
    return bg.convert("RGB").crop(box) if box else bg.convert("RGB")


def dino_similarity(a: Path, b: Path) -> float | None:
    """Cosine similarity of DINOv2 CLS embeddings of the two subjects (cropped to their alpha, on grey)."""
    global _dino
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModel
        if _dino is None:
            cache = MODELS / "scoring"
            _dino = (AutoImageProcessor.from_pretrained(DINO, cache_dir=cache),
                     AutoModel.from_pretrained(DINO, cache_dir=cache).eval())
        proc, model = _dino
        with torch.no_grad():
            emb = model(**proc(images=[_on_grey(a), _on_grey(b)], return_tensors="pt")).last_hidden_state[:, 0]
        emb = torch.nn.functional.normalize(emb, dim=-1)
        return round(float(emb[0] @ emb[1]), 4)
    except (SystemExit, Exception) as e:   # no network on first use, missing weights: silhouette still works
        log(f"DINO similarity unavailable ({str(e)[:120]})")
        return None


def score(raw_glb: Path, cutout: Path, dest: Path) -> dict:
    """Render the raw (camera-frame) mesh from the photo's viewpoint and compare it with the cutout."""
    from .inspect3d import render_views
    dest = Path(dest).resolve()
    render_views(raw_glb, dest, azimuths="0", elev=0, fov=20, rig=True, modes="beauty", res=768)
    front = dest / "views" / "beauty_000.png"
    out = {"front": str(front), "silhouette": round(silhouette_iou(front, cutout), 4),
           "dino": dino_similarity(front, cutout)}
    log(f"fidelity vs input: silhouette {out['silhouette']}" + (f", DINO {out['dino']}" if out["dino"] is not None else ""))
    return out
