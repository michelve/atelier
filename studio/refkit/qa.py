"""refkit qa: the small things that separate "generated" from "production".

Checks by type (all read-only). PASS / WARN / FAIL per check; exit code 1 if anything FAILs.
  raster (png/jpg/webp/avif): size budget, alpha halo, stray pixels; palette + colour rules only from --tokens
  svg:  path/node count, embedded rasters, tiny specks, viewBox, size budget, SSIM vs --ref
  glb:  FAIL on broken assets (no mesh, NaN vertices, textured without UVs, >1% degenerate faces, >3% non-manifold
        edges, texture size not what to3d was asked for — read from the model.json sidecar); WARN on budgets
        (triangles, texture px, file size) and open edges; sharp-edge ratio only when the tokens set
        "rounded_edges" (a project art rule, not a default)
  video (mp4/webm/gif): codec, fps, resolution, duration, size budget, faststart, loop seam
  raster also: embedded prompt/workflow metadata, local (per-region) alpha-halo check, and — when the sidecar's
        prompt quotes exact text ("CAP BLANC") — the local Qwen3-VL reads it back; FAIL if missing or misspelt
        (tesseract fallback: warning only)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

from .common import delta_e, hex_to_rgb, is_teal, load_tokens, log, rgb_to_lab, run, say

RASTER = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
VIDEO = {".mp4", ".webm", ".gif", ".mov"}


class Report:
    def __init__(self, target: Path):
        self.target, self.rows = target, []

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.rows.append({"check": name, "status": status, "detail": detail})

    def check(self, name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
        self.add(name, "PASS" if ok else ("WARN" if warn_only else "FAIL"), detail)

    @property
    def failed(self) -> bool:
        return any(r["status"] == "FAIL" for r in self.rows)


def _kb(p: Path) -> float:
    return round(p.stat().st_size / 1024, 1)


QUOTED = re.compile(r'["\u201c\u201d]([^"\u201c\u201d]{2,80})["\u201c\u201d]')


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", text.casefold()).strip()


READ_PROMPT = ("Transcribe all text visible in this image exactly as written, one line per text element. "
               "Output only the text.")


def read_text(images: list[Path]) -> dict[str, tuple[str, str]]:
    """{path: (text, reader)}. The local Qwen3-VL reads stylised poster type reliably (2026-10-01: 18/18 strings
    on 9 posters, and it transcribed a misspelt "CAP BLANK" / "since 1920" as written); tesseract read 3/12 of the
    same strings, so it is only the fallback when the VLM isn't installed."""
    from . import vlm
    try:
        out = {str(p): (vlm.ask([p], READ_PROMPT, max_new_tokens=120), "qwen3-vl") for p in images}
        vlm.unload()
        return out
    except SystemExit:
        from .analyze import ocr
        return {str(p): (ocr(p, min_conf=40), "tesseract") for p in images}


def text_check(image: Path, prompt: str, read: tuple[str, str] | None = None) -> list[dict]:
    """Every "quoted" string in the prompt vs the text read in the image. Qwen3-VL: exact match after normalising
    case/punctuation/spacing (catches misspellings). Tesseract fallback: fuzzy (>= 0.8), and only advisory."""
    from difflib import SequenceMatcher
    wanted = [w for w in QUOTED.findall(prompt or "") if _norm(w)]
    if not wanted:
        return []
    text, reader = read or read_text([image])[str(image)]
    seen = " ".join(_norm(text).split())
    words = seen.split()
    rows = []
    for w in wanted:
        target = " ".join(_norm(w).split())
        if reader == "qwen3-vl":
            rows.append({"text": w, "found": target in seen, "reader": reader})
            continue
        n, best = len(target.split()), 0.0
        for size in {max(1, n - 1), n, n + 1}:
            for i in range(max(1, len(words) - size + 1)):
                best = max(best, SequenceMatcher(None, target, " ".join(words[i:i + size])).ratio())
        rows.append({"text": w, "found": best >= 0.8, "reader": reader, "similarity": round(best, 2)})
    return rows


def check_raster(p: Path, rep: Report, tokens: dict) -> None:
    budgets = tokens.get("budgets", {})
    im = Image.open(p)
    im.load()
    rep.add("dimensions", "PASS", f"{im.width}x{im.height} {im.mode}")
    budget = budgets.get(f"{p.suffix.lstrip('.').replace('jpeg', 'jpg')}_kb") or budgets.get("png_kb")
    if budget:
        rep.check("file size", _kb(p) <= budget, f"{_kb(p)} KB (budget {budget} KB)", warn_only=True)
    # ComfyUI/other tools embed the full prompt + workflow in PNG text chunks; strip before publishing.
    meta = [k for k in (im.info or {}) if isinstance(k, str) and k.lower() in ("prompt", "workflow", "parameters", "comment")]
    rep.check("no embedded prompt/workflow", not meta, f"PNG text chunks: {', '.join(meta)} (strip with oxipng --strip safe)"
              if meta else "", warn_only=True)
    if "icc_profile" in im.info:
        rep.add("colour profile", "PASS", "embedded ICC profile")
    side = _sidecar(p)
    wants = side.get("command") in ("gen", "fix") and QUOTED.search(side.get("prompt", "") or "")
    for row in text_check(p, side["prompt"], _READ.get(str(p))) if wants else []:
        rep.check(f'text "{row["text"][:24]}"', row["found"], f"read by {row['reader']}"
                  + ("" if row["reader"] == "qwen3-vl" else " (advisory: tesseract misreads stylised type)"),
                  warn_only=row["reader"] != "qwen3-vl")
    rgba = np.array(im.convert("RGBA"))
    rgb, a = rgba[..., :3], rgba[..., 3]
    opaque = rgb[a > 200]
    if len(opaque) > 50000:
        opaque = opaque[np.random.default_rng(0).choice(len(opaque), 50000, replace=False)]

    # Teal: share of visible pixels in the forbidden hue band.
    if tokens.get("forbid_teal", False) and len(opaque):
        sample = opaque[:: max(1, len(opaque) // 5000)]
        teal = np.mean([is_teal(px) for px in sample])
        rep.check("no teal/cyan", bool(teal < 0.01), f"{teal:.1%} of pixels", warn_only=True)

    # Palette conformity: saturated pixels should sit near a token colour (neutrals are always allowed).
    pal = tokens.get("palette")
    if pal and len(opaque):
        lab = rgb_to_lab(opaque)
        chroma = np.hypot(lab[:, 1], lab[:, 2])
        colourful = lab[chroma > 15]
        if len(colourful):
            tok = rgb_to_lab(np.array([hex_to_rgb(h) for h in pal.values()], dtype=float))
            nearest = delta_e(colourful[:, None, :], tok[None, :, :]).min(axis=1)
            limit = tokens.get("max_delta_e", 12)
            off = float(np.mean(nearest > limit))
            rep.check("palette vs tokens", off < 0.15, f"{off:.0%} of coloured pixels are > dE {limit} from every token",
                      warn_only=True)

    if (a < 255).any():
        # Halo: the colour of partly transparent edge pixels should match the solid interior next to them.
        # Light fringes on a cutout (from a white background) show up as edge pixels much brighter than the subject.
        edge = (a > 20) & (a < 235)
        solid = a >= 250
        if edge.sum() > 50 and solid.sum() > 50:
            # Compare each edge pixel with the solid subject *next to it* (not the whole-subject mean, which
            # false-alarms on multi-coloured subjects).
            import cv2
            lum = rgb_to_lab(rgb.reshape(-1, 3))[:, 0].reshape(a.shape).astype(np.float32)
            s = solid.astype(np.float32)
            k = (9, 9)
            near = cv2.boxFilter(lum * s, -1, k, normalize=False) / np.maximum(cv2.boxFilter(s, -1, k, normalize=False), 1e-3)
            has_near = cv2.boxFilter(s, -1, k, normalize=False)[edge] > 0
            diff = np.abs(lum[edge] - near[edge])[has_near]
            if len(diff):
                bad = float(np.mean(diff > 18))
                rep.check("alpha halo", bad < 0.25, f"{bad:.0%} of edge pixels differ > 18 L from the adjacent subject "
                          "(defringe if high)", warn_only=True)
        stray = int(((a > 0) & (a < 20)).sum())
        rep.check("stray near-transparent pixels", stray < 0.002 * a.size, f"{stray} px", warn_only=True)


def check_svg(p: Path, rep: Report, tokens: dict, ref: Path | None) -> None:
    text = p.read_text(encoding="utf-8")
    paths = re.findall(r'\bd="([^"]*)"', text)
    nodes = sum(len(re.findall(r"[MLHVCSQTAZmlhvcsqtaz]", d)) for d in paths)
    rep.add("paths / nodes", "PASS", f"{len(paths)} paths, {nodes} nodes")
    rep.check("path count", len(paths) <= 1500, f"{len(paths)} (over 1500 usually means traced noise)", warn_only=True)
    rep.check("no embedded raster", "<image" not in text, "" if "<image" not in text else "SVG contains <image>")
    rep.check("has viewBox", "viewBox" in text, "needed for responsive scaling", warn_only=True)
    specks = sum(1 for d in paths if len(d) < 40)
    rep.check("tiny specks", specks <= max(5, len(paths) // 20), f"{specks} very short paths", warn_only=True)
    budget = tokens.get("budgets", {}).get("svg_kb")
    if budget:
        rep.check("file size", _kb(p) <= budget, f"{_kb(p)} KB (budget {budget} KB)", warn_only=True)
    if ref:
        import tempfile

        from .common import open_image
        from .vectorize import render, score
        refim = open_image(ref).convert("RGBA")
        with tempfile.TemporaryDirectory() as tmp:   # qa stays read-only next to the deliverable
            s = score(refim, render(p, Path(tmp) / "qa.png", refim.size))
        rep.check("SSIM vs reference", s["ssim"] >= 0.85, f"ssim {s['ssim']}, mean dE {s['mean_delta_e']}")


def check_glb(p: Path, rep: Report, tokens: dict) -> None:
    import struct
    import tempfile

    b = tokens.get("budgets", {})
    raw = p.read_bytes()
    used = []
    if raw[:4] == b"glTF":
        n = struct.unpack("<I", raw[12:16])[0]
        used = json.loads(raw[20:20 + n]).get("extensionsUsed", [])
    rep.add("extensions", "PASS", ", ".join(used) or "none")
    with tempfile.TemporaryDirectory() as tmp:
        readable = p
        if {"EXT_meshopt_compression", "KHR_mesh_quantization"} & set(used):
            # trimesh can't decode meshopt/quantized buffers; inspect a dequantized temp copy (same geometry).
            readable = Path(tmp) / p.name
            run(["gltf-transform", "dequantize", p, readable])
        _check_glb_geometry(readable, p, rep, b, tokens)


def _sidecar(p: Path) -> dict:
    """The run record next to a deliverable (meta.record), if refkit made it."""
    side = p.with_suffix(".json")
    try:
        return json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    except ValueError:
        return {}


def _check_glb_geometry(readable: Path, p: Path, rep: Report, b: dict, tokens: dict) -> None:
    import trimesh
    scene = trimesh.load(readable, force="scene")
    meshes = [g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh)]
    if not meshes or not sum(len(m.faces) for m in meshes):
        rep.add("geometry", "FAIL", "no triangle mesh in the file")
        return
    finite = all(np.isfinite(m.vertices).all() for m in meshes)
    rep.check("finite vertices", finite, "" if finite else "NaN/inf vertex positions")
    tris = sum(len(m.faces) for m in meshes)
    rep.check("triangles", tris <= b.get("glb_triangles", 150000), f"{tris:,} (budget {b.get('glb_triangles', 150000):,})",
              warn_only=True)
    rep.check("file size", _kb(p) <= b.get("glb_kb", 3000), f"{_kb(p)} KB", warn_only=True)
    ext = scene.extents
    rep.add("bounds", "PASS", "x".join(f"{e:.3f}" for e in ext) if ext is not None else "empty")
    # glTF splits vertices along UV/normal seams; weld a copy so seams don't count as holes.
    welded = [m.copy() for m in meshes]
    for m in welded:
        m.merge_vertices(merge_tex=True, merge_norm=True)
    open_edges = sum(len(trimesh.grouping.group_rows(m.edges_sorted, require_count=1)) for m in welded)
    rep.check("watertight", open_edges == 0, f"{open_edges} open edges", warn_only=True)
    # Broken geometry: edges shared by 3+ faces, zero-area faces. A few are normal in generated meshes. Calibrated
    # 2026-10-01: clean Pixal3D/TRELLIS.2 meshes 0-1.3%, a visibly shredded TRELLIS.2 mesh 7.8% -> FAIL above 3%.
    edges = sum(len(m.edges_unique) for m in welded)
    bad_edges = sum(int((np.bincount(m.edges_unique_inverse) > 2).sum()) for m in welded)
    share = bad_edges / max(edges, 1)
    rep.add("non-manifold edges", "FAIL" if share > 0.03 else ("WARN" if bad_edges else "PASS"),
            f"{bad_edges} ({share:.2%} of edges)")
    scale = float(max(scene.extents)) if scene.extents is not None else 1.0
    degenerate = sum(int((m.area_faces <= 1e-12 * scale * scale).sum()) for m in meshes)
    share = degenerate / max(tris, 1)
    rep.add("degenerate faces", "FAIL" if share > 0.01 else ("WARN" if degenerate else "PASS"),
            f"{degenerate} zero-area ({share:.2%})")
    textured = [m for m in meshes if getattr(m.visual, "kind", None) == "texture"]
    missing_uv = [m for m in textured if getattr(m.visual, "uv", None) is None or not len(m.visual.uv)]
    rep.check("UVs on textured meshes", not missing_uv,
              f"{len(missing_uv)} of {len(textured)} textured meshes have no UVs" if missing_uv
              else ("all textured meshes have UVs" if textured else "untextured"))
    # Art rule, not a default: only when the project tokens ask for rounded forms (e.g. Orbitra).
    if tokens.get("rounded_edges"):
        sharp = total = 0
        for m in meshes:
            if len(m.face_adjacency):
                ang = np.degrees(m.face_adjacency_angles)
                sharp += int((ang > 60).sum())
                total += len(ang)
        if total:
            rep.check("sharp edges", sharp / total < 0.02, f"{sharp / total:.1%} of edges > 60 deg (bevel/smooth if high)",
                      warn_only=True)
    try:
        from pygltflib import GLTF2
        g = GLTF2().load(str(readable))
        blob = g.binary_blob() or b""
        limit = b.get("texture_px", 2048)
        # to3d writes the requested size into the sidecar; a different baked size means the pipeline misbehaved.
        asked = _sidecar(p).get("texture") if _sidecar(p).get("command") == "to3d" else None
        for i, img in enumerate(g.images):
            if img.bufferView is None:
                continue
            bv = g.bufferViews[img.bufferView]
            import io
            data = blob[bv.byteOffset or 0:(bv.byteOffset or 0) + bv.byteLength]
            try:
                w, h = Image.open(io.BytesIO(data)).size
                rep.check(f"texture {i} size", max(w, h) <= limit, f"{w}x{h} {img.mimeType} (web budget {limit})",
                          warn_only=True)
                if asked:
                    rep.check(f"texture {i} as requested", max(w, h) == min(int(asked), 4096),
                              f"{max(w, h)} px, to3d --texture {asked}")
            except Exception:
                rep.add(f"texture {i}", "PASS", f"{img.mimeType} (KTX2/compressed, not inspected)")
    except Exception as e:
        rep.add("textures", "WARN", f"could not inspect: {e}")


def check_video(p: Path, rep: Report, tokens: dict) -> None:
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "stream=codec_name,width,height,r_frame_rate,pix_fmt:format=duration,size", "-of", "json", p]).stdout
    info = json.loads(out)
    v = next((s for s in info.get("streams", []) if s.get("width")), {})
    num, den = (v.get("r_frame_rate", "0/1").split("/") + ["1"])[:2]
    fps = float(num) / float(den or 1)
    rep.add("stream", "PASS", f"{v.get('codec_name')} {v.get('width')}x{v.get('height')} {fps:.2f} fps {v.get('pix_fmt')}")
    rep.check("even dimensions", v.get("width", 0) % 2 == 0 and v.get("height", 0) % 2 == 0, "", warn_only=True)
    # 10-bit is part of AV1's Main profile, so every AV1 decoder plays it; for H.264/VP9 stick to 8-bit 4:2:0.
    safe = ("yuv420p", "yuva420p", None) + (("yuv420p10le",) if v.get("codec_name") == "av1" else ())
    rep.check("web-safe pixel format", v.get("pix_fmt") in safe, str(v.get("pix_fmt")), warn_only=True)
    dur = float(info["format"].get("duration", 0) or 0)
    rep.add("duration / size", "PASS", f"{dur:.2f}s, {_kb(p)} KB")
    budget_kb = tokens.get("budgets", {}).get("video_kb", 3000)
    if dur <= 15:   # short loops / hero clips carry a size budget; long videos don't
        rep.check("file size", _kb(p) <= budget_kb, f"{_kb(p)} KB (hero-loop budget {budget_kb} KB)", warn_only=True)
    if p.suffix.lower() in (".mp4", ".mov"):
        head = p.read_bytes()[:1 << 16]
        moov, mdat = head.find(b"moov"), head.find(b"mdat")
        fast = moov != -1 and (mdat == -1 or moov < mdat)
        rep.check("faststart (moov first)", fast,
                  "" if fast else "re-mux with -movflags +faststart so it starts playing before fully downloaded", warn_only=True)
    if 0 < dur <= 30:
        # Loop seam: the last frame should lead into the first (turntables render frame N+1 == frame 1).
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            first, last = Path(tmp) / "first.png", Path(tmp) / "last.png"
            run(["ffmpeg", "-v", "error", "-y", "-i", p, "-frames:v", "1", first], check=False)
            run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.2", "-i", p, "-update", "1", last], check=False)
            if first.exists() and last.exists():
                fa = np.asarray(Image.open(first).convert("L"), dtype=np.float32)
                fb = np.asarray(Image.open(last).convert("L").resize((fa.shape[1], fa.shape[0])), dtype=np.float32)
                jump = float(np.mean(np.abs(fa - fb)))
                rep.check("loop seam", jump < 12, f"mean jump {jump:.1f}/255 between last and first frame" +
                          ("" if jump < 12 else " (fine if the clip isn't meant to loop)"), warn_only=True)


_READ: dict[str, tuple[str, str]] = {}   # text read in one VLM session for every raster that needs a text check


def main(args) -> bool:
    tokens = load_tokens(args.tokens)
    ok = True
    texty = [Path(f).resolve() for f in args.files if Path(f).suffix.lower() in RASTER
             and _sidecar(Path(f).resolve()).get("command") in ("gen", "fix")
             and QUOTED.search(_sidecar(Path(f).resolve()).get("prompt", "") or "")]
    if texty:
        _READ.update(read_text(texty))
    for f in args.files:
        p = Path(f).resolve()
        rep = Report(p)
        suffix = p.suffix.lower()
        if suffix in RASTER:
            check_raster(p, rep, tokens)
        elif suffix == ".svg":
            check_svg(p, rep, tokens, Path(args.ref) if args.ref else None)
        elif suffix in (".glb", ".gltf"):
            check_glb(p, rep, tokens)
        elif suffix in VIDEO:
            check_video(p, rep, tokens)
        else:
            log(f"{p.name}: no checks for {suffix}")
            continue
        say(f"\n{p.name}")
        for r in rep.rows:
            say(f"  {r['status']:4s}  {r['check']:<30s} {r['detail']}")
        if args.json:
            (p.parent / f"{p.name}.qa.json").write_text(json.dumps(rep.rows, indent=2), encoding="utf-8")
        ok &= not rep.failed
    return ok
