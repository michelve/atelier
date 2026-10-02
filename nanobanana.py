"""Generate images (Nano Banana) or videos (Gemini Omni / Veo) with the Google Gemini API (own key).

Needs GEMINI_API_KEY (environment variable). Output goes to images/ next to this script unless -o is given.
Every call is paid (no free tier for image/video): the estimated cost is printed first and the call only runs with
--yes (or after answering y in an interactive terminal). Each call is appended to gemini-spend.csv next to this script.

  python nanobanana.py "a lavender glass orb on satin black" --yes
  python nanobanana.py "make it dusk" -i photo.png --aspect 16:9 -m pro --size 2K --yes
  python nanobanana.py "infographic of the water cycle, labelled" --ground --thinking high --yes
  python nanobanana.py "slow orbit around the orb" --video -i orb.png --yes                 (Omni, first frame)
  python nanobanana.py "dawn turns to night" --video -i first.png --to last.png --yes       (first + last frame)
  python nanobanana.py "make the violin invisible" --video --continue <interaction id> --yes (Omni edit)
  python nanobanana.py "the cat chases the yarn" --video -m veo-fast --ref cat.png --ref yarn.png --yes
  python nanobanana.py --list

Image aliases: 2 (Nano Banana 2, default), pro, lite.  Video aliases: omni (default), veo, veo-fast, veo-lite.
Any full model id also works.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

ALIASES = {
    "2": "gemini-3.1-flash-image",  # Nano Banana 2 (ranks above Pro on Artificial Analysis, ~half the price)
    "pro": "gemini-3-pro-image",  # Nano Banana Pro
    "lite": "gemini-3.1-flash-lite-image",  # Nano Banana 2 Lite (1K only)
    # "1" (gemini-2.5-flash-image) was removed: Google shuts it down on 2026-10-02.
    "omni": "gemini-omni-1.1-flash",  # Gemini Omni Flash video (Interactions API)
    "veo": "veo-3.1-generate-preview",
    "veo-fast": "veo-3.1-fast-generate-preview",
    "veo-lite": "veo-3.1-lite-generate-preview",
}
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "images"
SPEND_LOG = HERE / "gemini-spend.csv"

# USD, Gemini Developer API paid tier, checked 2026-09-30 (ai.google.dev/gemini-api/docs/pricing).
IMAGE_PRICE = {  # per image by size
    "gemini-3.1-flash-image": {"512": 0.045, "1K": 0.067, "2K": 0.101, "4K": 0.151},
    "gemini-3-pro-image": {"1K": 0.134, "2K": 0.134, "4K": 0.24},
    "gemini-3.1-flash-lite-image": {"1K": 0.0336},
}
VIDEO_PRICE = {  # per second by resolution
    "veo-3.1-generate-preview": {"720p": 0.40, "1080p": 0.40, "4k": 0.60},
    "veo-3.1-fast-generate-preview": {"720p": 0.10, "1080p": 0.12, "4k": 0.30},
    "veo-3.1-lite-generate-preview": {"720p": 0.05, "1080p": 0.08},
    "gemini-omni-1.1-flash": {"360p": 0.10, "720p": 0.10},   # token-priced; ~$0.10/s at 720p. 1080p/4k are upscales
}


def load_key() -> None:
    # A terminal opened before the key was saved won't have it: fall back to where the setup saved it
    # (the user environment in the Windows registry; the login Keychain on macOS).
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return
    sys.path.insert(0, str(HERE / "studio"))
    from refkit import host

    key = host.secret("GEMINI_API_KEY")
    if key:
        os.environ["GEMINI_API_KEY"] = key
        return
    sys.exit("GEMINI_API_KEY is not set. Get one at https://aistudio.google.com/apikey")


def mime(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")


def b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


# --- cost -------------------------------------------------------------------------------------------

def estimate(args) -> tuple[float, str]:
    if args.video:
        res = (args.size or "720p").lower()
        secs = args.seconds or (6 if args.model.startswith("gemini-omni") else 8)
        if args.model.startswith("veo") and (res in ("1080p", "4k") or args.ref or args.to):
            secs = 8   # forced by Veo, see gen_veo
        rate = VIDEO_PRICE.get(args.model, {}).get(res) or max(VIDEO_PRICE.get(args.model, {"?": 0.40}).values())
        note = " (1080p/4k on Omni are upscales; price not published — estimate)" if args.model.startswith("gemini-omni") and res not in ("360p", "720p") else ""
        return rate * secs, f"{args.model} {res} ~{secs}s @ ${rate:.2f}/s{note}"
    size = args.size or "1K"
    table = IMAGE_PRICE.get(args.model, {})
    price = table.get(size) or (max(table.values()) if table else 0.15)
    return price, f"{args.model} {size} image"


def confirm(args) -> tuple[float, str]:
    usd, what = estimate(args)
    print(f"cost estimate: ${usd:.3f}  ({what})", file=sys.stderr)
    if not args.yes:
        try:
            answer = input("proceed? [y/N] ").strip().lower() if sys.stdin.isatty() else ""
        except EOFError:   # e.g. Git Bash reports a tty with no input attached
            answer = ""
        if answer != "y":
            sys.exit("paid call not run: re-run with --yes to confirm the cost above")
    return usd, what


def log_spend(model: str, what: str, usd: float, out: Path, status: str) -> None:
    """status: ok | failed (a rejected request is not billed; a failure after generation may be)."""
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not SPEND_LOG.exists()
    with SPEND_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "model", "what", "est_usd", "status", "output"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), model, what,
                    f"{usd:.3f}" if status == "ok" else "0", status, str(out)])


# --- images -------------------------------------------------------------------------------------------

def gen_image(client: genai.Client, args, out: Path) -> None:
    if len(args.image) > 14:
        sys.exit("Nano Banana takes at most 14 input images")
    contents: list = [types.Part.from_bytes(data=Path(p).read_bytes(), mime_type=mime(p)) for p in args.image]
    contents.append(args.prompt)
    image_config = types.ImageConfig(aspect_ratio=args.aspect, image_size=args.size) if (args.aspect or args.size) else None
    thinking = (types.ThinkingConfig(thinking_level=args.thinking.capitalize())
                if args.thinking and "flash" in args.model else None)
    resp = client.models.generate_content(
        model=args.model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=image_config,
            thinking_config=thinking,
            tools=[types.Tool(google_search=types.GoogleSearch())] if args.ground else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    content = resp.candidates[0].content if resp.candidates else None
    saved = 0
    for part in (content.parts if content and content.parts else []):
        if getattr(part, "thought", False):
            continue   # Pro/thinking interim images are drafts, not the answer
        if part.text:
            print(part.text)
        elif part.inline_data and part.inline_data.data:
            path = out if saved == 0 else out.with_stem(f"{out.stem}-{saved}")
            path.write_bytes(part.inline_data.data)
            print(path)
            saved += 1
    if not saved:
        sys.exit(f"No image returned: {resp.prompt_feedback or resp.candidates}")


# --- video: Gemini Omni (Interactions API) -----------------------------------------------------------

def gen_omni(client: genai.Client, args, out: Path) -> None:
    items: list[dict] = []
    if args.extend:
        up = client.files.upload(file=args.extend)
        items.append({"type": "video", "uri": up.uri})
    frames = args.image + ([args.to] if args.to else []) + args.ref   # first, last, then subject refs
    items += [{"type": "image", "data": b64(p), "mime_type": mime(p)} for p in frames]
    text = args.prompt
    items.append({"type": "text", "text": text})
    # duration "Ns" works (verified 2026-09-30: "3s" -> 3.0 s). Without it Omni picked 10 s, so always send it.
    fmt: dict = {"type": "video", "delivery": "uri", "resolution": (args.size or "720p").lower(),
                 "duration": f"{args.seconds or 6}s"}
    if args.aspect:
        fmt["aspect_ratio"] = args.aspect
    kw = {"previous_interaction_id": args.cont} if args.cont else {}
    # Run as a background interaction and poll: a synchronous request can outlive the HTTP connection
    # (seen as an empty response / JSONDecodeError on 2026-09-30).
    inter = client.interactions.create(model=args.model, input=items if len(items) > 1 else text,
                                       response_format=fmt, background=True, timeout=120, **kw)  # type: ignore[call-overload]
    iid = getattr(inter, "id", None)
    for _ in range(240):   # up to 20 min
        status = getattr(inter, "status", "completed")
        if status in ("completed", "failed", "cancelled", "incomplete", "budget_exceeded"):
            break
        time.sleep(5)
        inter = client.interactions.get(iid, timeout=60)  # type: ignore[arg-type]
    out.with_suffix(".json").write_text(json.dumps({"model": args.model, "interaction_id": iid, "prompt": args.prompt,
                                                    "inputs": frames}, indent=2), encoding="utf-8")
    if getattr(inter, "status", "completed") != "completed":
        sys.exit(f"Omni interaction {iid} ended with status {getattr(inter, 'status', '?')}: {getattr(inter, 'error', '')}")
    video = getattr(inter, "output_video", None)
    if video is None:
        sys.exit(f"No video returned: {inter}")
    if video.data:
        data = video.data
        out.write_bytes(base64.b64decode(data) if isinstance(data, str) else data)
    elif video.uri:
        # The URI can carry a suffix (".../files/<id>:download?alt=media"); take just the id.
        m = re.search(r"files/([A-Za-z0-9_-]+)", video.uri)
        if not m:
            sys.exit(f"unexpected Omni video URI: {video.uri} (interaction {iid})")
        name = f"files/{m.group(1)}"
        for _ in range(360):
            state = client.files.get(name=name).state
            if state and state.name == "ACTIVE":
                break
            if state and state.name == "FAILED":
                sys.exit("Omni video processing failed")
            time.sleep(5)
        client.files.download(file=name, destination=str(out))
    else:
        sys.exit(f"Omni returned neither data nor a URI: {video}")
    out.with_suffix(".json").write_text(json.dumps({"model": args.model, "interaction_id": iid,
                                                    "prompt": args.prompt, "inputs": frames}, indent=2), encoding="utf-8")
    print(out)
    print(f"interaction id (for --continue edits): {iid}")


# --- video: Veo 3.1 -----------------------------------------------------------------------------------

def gen_veo(client: genai.Client, args, out: Path) -> None:
    if args.ref and len(args.ref) > 3:
        sys.exit("Veo takes at most 3 reference images")
    res = (args.size or "720p").lower()
    secs = args.seconds or 8
    # Docs list 8 s for 1080p/4k/references; in practice first+last frame (--to) needs it too (4 s -> 400
    # "use case not supported", checked 2026-09-30).
    if (res in ("1080p", "4k") or args.ref or args.to) and secs != 8:
        print("note: Veo needs 8 s for 1080p/4k, reference images or a last frame; using 8 s", file=sys.stderr)
        secs = 8
    has_images = bool(args.image or args.to or args.ref)
    cfg = types.GenerateVideosConfig(
        aspect_ratio=args.aspect, resolution=res, duration_seconds=secs,
        negative_prompt=args.negative,
        last_frame=types.Image.from_file(location=args.to) if args.to else None,
        reference_images=[types.VideoGenerationReferenceImage(image=types.Image.from_file(location=p),
                                                              reference_type=types.VideoGenerationReferenceType.ASSET)
                          for p in args.ref] or None,
        # EU/UK/CH only allow adults; image->video and references always require it there.
        person_generation="allow_adult" if has_images else None,
    )
    op = client.models.generate_videos(
        model=args.model, prompt=args.prompt,
        image=types.Image.from_file(location=args.image[0]) if args.image else None, config=cfg)
    while not op.done:
        time.sleep(10)
        op = client.operations.get(op)
    videos = op.response.generated_videos if op.response else None
    if not videos or not videos[0].video:
        sys.exit(f"No video returned: {op.error or op.response}")
    client.files.download(file=videos[0].video)
    videos[0].video.save(str(out))
    print(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("-i", "--image", action="append", default=[],
                    help="input/reference image (repeatable, up to 14 for images); for video: the first frame")
    ap.add_argument("-o", "--out", help="output file (default: images/nb-<timestamp>.png/.mp4 next to this script)")
    ap.add_argument("-m", "--model", help="alias or full model id")
    ap.add_argument("--video", action="store_true", help="generate a video (default model: Gemini Omni)")
    ap.add_argument("--aspect", help="images: 1:1 2:3 3:2 3:4 4:3 4:5 5:4 9:16 16:9 21:9; video: 16:9 or 9:16")
    ap.add_argument("--size", help="image: 512 (NB2), 1K, 2K, 4K; video: 360p (Omni), 720p, 1080p, 4k")
    ap.add_argument("--seconds", type=int, help="video length (Veo 4/6/8; Omni 3-10)")
    ap.add_argument("--to", help="video: last frame image")
    ap.add_argument("--ref", action="append", default=[], help="video: subject/reference image (Veo <=3, repeatable)")
    ap.add_argument("--negative", help="Veo: what to avoid (Omni has no negative field; say it in the prompt)")
    ap.add_argument("--continue", dest="cont", help="Omni: edit/continue a previous interaction id")
    ap.add_argument("--extend", help="Omni: video file (<=10 s) to continue")
    ap.add_argument("--ground", action="store_true", help="images: ground with Google Search (factual visuals)")
    ap.add_argument("--thinking", choices=["minimal", "high"], help="Nano Banana 2 thinking level")
    ap.add_argument("--yes", action="store_true", help="confirm the paid call (shows the estimate either way)")
    ap.add_argument("--list", action="store_true", help="list image/video models and exit")
    args = ap.parse_args()

    load_key()
    client = genai.Client()

    if args.list:
        for m in client.models.list():
            name = (m.name or "").removeprefix("models/")
            if "image" in name or "veo" in name or "omni" in name:
                print(name, "-", m.display_name)
        return 0
    if not args.prompt:
        ap.error("prompt is required")

    default = "omni" if args.video else os.environ.get("NANO_BANANA_MODEL", "2")
    args.model = ALIASES.get(args.model or default, args.model or default)
    ext = ".mp4" if args.video else ".png"
    out = Path(args.out) if args.out else OUT_DIR / f"nb-{datetime.now():%Y%m%d-%H%M%S}{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    usd, what = confirm(args)
    try:
        if not args.video:
            gen_image(client, args, out)
        elif args.model.startswith("gemini-omni"):
            gen_omni(client, args, out)
        else:
            gen_veo(client, args, out)
    except BaseException:
        log_spend(args.model, what, usd, out, "failed")
        raise
    log_spend(args.model, what, usd, out, "ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
