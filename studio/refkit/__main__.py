"""refkit CLI. Run `refkit <command> -h` for options."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]   # defaults below are relative to the Atelier clone


def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="refkit", description="Local reference-image pipeline (all on this PC).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    # Every command: --json prints its result as one JSON object on stdout (logs go to stderr).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print the result as one JSON line on stdout")

    def cmd(name: str, **kw) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common], **kw)

    p = cmd("analyze", help="palette, structure, cutout, depth, OCR, local vision description")
    p.add_argument("image")
    p.add_argument("--colors", type=int, default=8)
    p.add_argument("--fast", action="store_true", help="skip depth estimation")
    p.add_argument("--describe", default="none", choices=["none", "gemini", "ollama"],
                   help="optional text description (default none: the Claude session reads sheet.png)")
    p.add_argument("--out")

    p = cmd("cutout", help="subject -> RGBA with clean edges (BiRefNet, or SAM 3 with --prompt)")
    p.add_argument("image")
    p.add_argument("--prompt", help="what to keep, e.g. 'the glass cube' (SAM 3.1)")
    p.add_argument("--engine", default="comfy", choices=["comfy", "qwen", "rembg"],
                   help="comfy = BiRefNet / SAM 3.1 (default); qwen = Qwen-Image 2.1 matting (hair, glass); rembg")
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--max", type=int, default=50, help="max instances per concept (SAM 3)")
    p.add_argument("--feather", type=float, default=0.8, help="edge softening in px (0 = hard)")
    p.add_argument("--out")

    p = cmd("vectorize", help="raster -> tuned, optimised SVG")
    p.add_argument("image")
    p.add_argument("--colors", type=int, default=None, help="k-means colours (default: analysis palette, else 8)")
    p.add_argument("--palette", help="comma-separated hex list to snap to, e.g. '#ece8ff,#8f6bff,#0d0d12'")
    p.add_argument("--preset", choices=["clean", "balanced", "detailed", "flat"])
    p.add_argument("--mono", action="store_true", help="single colour via potrace (logos, icons, line art)")
    p.add_argument("--mono-color", default="#000000")
    p.add_argument("--min-side", type=int, default=1024, help="upscale before tracing if smaller")
    p.add_argument("--target", type=float, default=0.90, help="SSIM target")
    p.add_argument("--out")

    p = cmd("gen", help="local image generation / reference restyle (ComfyUI)")
    p.add_argument("prompt", nargs="?", default="")
    p.add_argument("--recipe", metavar="MODEL", help="print how MODEL wants to be prompted, then exit")
    p.add_argument("--prompt-file", help="read the prompt from a UTF-8 text file (use for prompts containing \" quotes:"
                                         " the .cmd shim re-splits quoted arguments)")
    p.add_argument("-i", "--image", help="reference image to edit/restyle")
    p.add_argument("-m", "--model", default=None,
                   help="z-image, qwen, krea, qwen-edit, klein-edit (local) or banana, banana-pro (cloud); see --list")
    p.add_argument("--size", default=None, help="WxH (default 1024x1024; qwen-edit keeps the reference size)")
    p.add_argument("--enhance", action="store_true", help="use the template's built-in prompt enhancer (qwen/krea)")
    p.add_argument("--consistent", action="store_true",
                   help="qwen-edit: Consistency LoRA, the edit stays on the source's frame (not for pose/move edits)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("-n", "--count", type=int, default=1)
    p.add_argument("--pick", action="store_true",
                   help="with -n > 1: rank (HPSv3++; EditScore for edits; PickScore fallback), write contact.png")
    p.add_argument("--auto", action="store_true",
                   help="generate -n (>= 4) -> score -> local critic -> text check, new seeds if it fails; report.md")
    p.add_argument("--rounds", type=int, default=2, help="--auto: max rounds of new seeds")
    p.add_argument("--list", action="store_true")
    p.add_argument("--yes", action="store_true", help="confirm paid cloud calls (banana models; cost is printed first)")
    p.add_argument("--out", default=str(REPO / "images"))

    p = cmd("video", help="prompt/keyframes -> clip (Gemini Omni / Veo, own key) + local upscale/interpolation")
    p.add_argument("prompt", nargs="?", default="", help="the motion prompt (or a video file with --finish-only)")
    p.add_argument("--prompt-file", help="read the prompt from a UTF-8 text file (for prompts containing \" quotes)")
    p.add_argument("-m", "--model", choices=["omni", "veo", "veo-fast", "veo-lite"], help="default omni")
    p.add_argument("--from", dest="frm", help="first frame image (e.g. from refkit gen)")
    p.add_argument("--to", help="last frame image")
    p.add_argument("--ref", action="append", default=[], help="subject/reference image (repeatable; Veo <= 3)")
    p.add_argument("--aspect", choices=["16:9", "9:16"])
    p.add_argument("--seconds", type=int, help="Omni 3-10 (default ~6); Veo 4/6/8 (default 8)")
    p.add_argument("--res", default="720p", help="generate at 720p and --upscale locally (Omni 1080p/4k are upscales)")
    p.add_argument("--negative", help="Veo only")
    p.add_argument("--continue", dest="cont", help="Omni: edit a previous clip by its interaction id")
    p.add_argument("--upscale", action="store_true", help="local SeedVR2 3B upscale (~2x) after generation")
    p.add_argument("--interp", type=int, default=1, help="local frame interpolation multiplier (2 = 24->48 fps)")
    p.add_argument("--finish-only", action="store_true", help="prompt is an existing video: only run the local finish")
    p.add_argument("--yes", action="store_true", help="confirm the paid call (the cost estimate is printed first)")
    p.add_argument("--out", default=str(REPO / "images" / "video"))

    p = cmd("upscale", help="detail-restoring upscale (SeedVR2), optional Z-Image refine pass first")
    p.add_argument("image")
    p.add_argument("--scale", type=float, default=2.0, help="multiplier on the long side (default 2)")
    p.add_argument("--long", type=int, help="target long side in px (overrides --scale)")
    p.add_argument("--model", default="3b", choices=["3b", "7b"], help="7b for hero images (slower, sharper)")
    p.add_argument("--refine", metavar="PROMPT", help="first re-draw lightly with Z-Image using this prompt")
    p.add_argument("--denoise", type=float, default=0.3, help="refine strength (0.25-0.4)")
    p.add_argument("--seed", type=int)
    p.add_argument("--out")

    p = cmd("to3d", help="image -> cleaned, optimised GLB (+ thumbnail)")
    p.add_argument("image", nargs="?", default="")
    p.add_argument("-m", "--model", default=None, choices=["pixal3d", "trellis2", "hunyuan3d"],
                   help="pixal3d (default, textured), trellis2 (textured), hunyuan3d (shape only)")
    p.add_argument("--tris", type=int, default=60000, help="final triangle budget (textured models: set before baking)")
    p.add_argument("--texture", type=int, default=2048, choices=[1024, 2048, 4096], help="baked texture size")
    p.add_argument("--views", help="multi-view: 1-4 images front,left,back,right (Pixal3D multi-view; image arg ignored)")
    p.add_argument("--ktx2", action="store_true", help="KTX2 GPU-compressed textures instead of WebP (less VRAM in three.js)")
    p.add_argument("--material", default="keep", choices=["keep", "orbitra-metal", "orbitra-glass"])
    p.add_argument("--quality", default="standard", choices=["standard", "high"],
                   help="high: shape cascade 1536 — more fine detail, lumpier smooth surfaces, ~15%% slower")
    p.add_argument("--hard-edges", action="store_true",
                   help="crisp creases for boxy hard-surface objects (QEM decimate, normals split > 45 deg); "
                        "curved parts look faceted")
    p.add_argument("-n", "--count", type=int, default=1, help="run N seeds (--seed, --seed+1, ...) and write compare.png")
    p.add_argument("--auto", action="store_true",
                   help="run -n (>= 3) seeds, rank their inspect sheets with the local critic, write report.md")
    p.add_argument("--delight", action="store_true",
                   help="remove the photo's lighting/highlights first (Marigold albedo), so they aren't baked in")
    p.add_argument("--refine-views", action="store_true",
                   help="Pixal3D: redraw left/back/right views of the first mesh (Qwen + AnyAngle) and rebuild multi-view")
    p.add_argument("--no-level", dest="level", action="store_false",
                   help="keep the camera-frame orientation (default: stand the model on its base; Pixal3D meshes "
                        "lean back by the photo's camera elevation)")
    p.add_argument("--no-inspect", dest="inspect", action="store_false",
                   help="skip the Blender QA views sheet (inspect/views.png) after each run")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out")

    p = cmd("render", help="GLB/.blend -> Cycles turntable MP4/WebM + AVIF/WebP poster")
    p.add_argument("input")
    p.add_argument("--frames", type=int, default=96, help="96 = 4 s at 24 fps; 1 = still")
    p.add_argument("--res", default=None, help="WxH (default 1600x1600; --as-is keeps the scene's own)")
    p.add_argument("--samples", type=int, default=None, help="Cycles samples (default 128; --as-is keeps the scene's own)")
    p.add_argument("--look", default="neutral", choices=["neutral", "orbitra"],
                   help="neutral = AgX base contrast + studio reflections (default); orbitra = project look")
    p.add_argument("--as-is", action="store_true", help=".blend: render its own camera/animation/colour settings")
    p.add_argument("--transparent", action="store_true", help="transparent background (WebM/AVIF/WebP keep alpha)")
    p.add_argument("--ground", action="store_true", help="contact shadow on an invisible floor (shadow catcher)")
    p.add_argument("--av1", action="store_true", help="also write an AV1 MP4 (smaller at the same quality)")
    p.add_argument("--out")

    p = cmd("inspect", help="3D QA views: textured + clay contact sheet and mesh facts (stats.json)")
    p.add_argument("model")
    p.add_argument("--views", type=int, default=8, help="azimuths around the model, starting at the front")
    p.add_argument("--res", type=int, default=640, help="size of each rendered view")
    p.add_argument("--out")

    p = cmd("fix", help="redraw one region (hands, face, text) via SAM + Qwen edit / Z-Image, blend it back")
    p.add_argument("image")
    p.add_argument("--region", help="what to fix, found by SAM 3.1 (every instance), e.g. 'hand'")
    p.add_argument("--mask", help="your own mask instead of --region (white = redraw)")
    p.add_argument("--prompt", required=True, help="qwen: the instruction; zimage: a description of the region")
    p.add_argument("--engine", default="qwen", choices=["qwen", "zimage"])
    p.add_argument("--denoise", type=float, default=0.4, help="zimage strength (0.3-0.45)")
    p.add_argument("--threshold", type=float, default=0.4, help="SAM confidence")
    p.add_argument("--seed", type=int)
    p.add_argument("--out")

    p = cmd("critique", help="local VLM judge: rank candidates pairwise (order-swapped) or check view consistency")
    p.add_argument("images", nargs="+")
    p.add_argument("--brief", help="what was asked for (the prompt or a short brief)")
    p.add_argument("--ref", help="reference image the candidates should match")
    p.add_argument("--kind", default="image", choices=["image", "3d"], help="3d = inspect view sheets")
    p.add_argument("--consistency", action="store_true", help="the images are front/left/back/right views of one object")

    p = cmd("qa", help="production checks for png/webp/avif/svg/glb/mp4")
    p.add_argument("files", nargs="+")
    p.add_argument("--ref", help="reference image for SVG fidelity")
    p.add_argument("--tokens", help="project design tokens json (palette, forbid_teal, budgets); default = budgets only")

    cmd("status", help="what is installed / running")

    p = cmd("runs", help="recent runs from the run index (lineage, seeds, models)")
    p.add_argument("--last", type=int, default=20)
    p.add_argument("--command", help="only this command (gen, to3d, upscale, ...)")

    p = cmd("smoke", help="after a ComfyUI update: re-export + validate workflows, quick end-to-end run")
    p.add_argument("--no-export", action="store_true", help="skip re-exporting workflows")
    p.add_argument("--force-export", action="store_true", help="re-export even if the templates version is unchanged")
    p.add_argument("--quick", action="store_true", help="skip the 3D / render / critic checks (~3 min)")

    p = cmd("bench", help="A/B ComfyUI launch flags on fixed-seed jobs (time, VRAM, output drift)")
    p.add_argument("--set", action="append", default=[], help='label=flags, e.g. "ck=--use-ck-attention" (repeatable)')
    p.add_argument("--full", action="store_true", help="also time a Pixal3D job (needs --cutout)")
    p.add_argument("--cutout", help="RGBA cutout for the --full 3D job")
    p.add_argument("--golden", action="store_true", help="run the fixed-seed regression set (studio/tests/golden)")
    p.add_argument("--label", help="--golden: name of this run (default: date-time)")
    p.add_argument("--compare", help="--golden: earlier label to put side by side with this run")
    p.add_argument("--only", help="--golden: comma-separated job ids")
    return ap


def _result(cmd: str, res, seconds: float) -> dict:
    """A command's return value -> the --json result: a dict is used as is; paths become `outputs`."""
    out = {"command": cmd, "ok": True, "seconds": round(seconds, 1)}
    if isinstance(res, dict):
        out.update(res)
    elif isinstance(res, (list, tuple)):
        out["outputs"] = [str(r) for r in res]
    elif res is not None and not isinstance(res, bool):
        out["outputs"] = [str(res)]
    return out


def main(argv: list[str] | None = None) -> int:
    args = build().parse_args(argv)
    from . import common, meta
    common.JSON_MODE = args.json
    if getattr(args, "prompt_file", None):
        args.prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    t = time.time()
    if args.cmd == "vectorize":
        args.colors_given = args.colors is not None
        args.colors = args.colors or 8
    if args.cmd in ("qa", "smoke"):   # pass/fail commands: the exit code is the result
        from importlib import import_module
        ok = import_module(f".{args.cmd}", __package__).main(args)
        meta.emit(_result(args.cmd, None, time.time() - t) | {"ok": bool(ok)})
        return 0 if ok else 1
    if args.cmd == "status":
        from . import status
        res = status.main()
    elif args.cmd == "runs":
        res = meta.main(args)
    else:
        from importlib import import_module
        module = {"inspect": "inspect3d"}.get(args.cmd, args.cmd)
        res = import_module(f".{module}", __package__).main(args)
    meta.emit(_result(args.cmd, res, time.time() - t))
    print(f"refkit: {args.cmd} done in {time.time() - t:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
