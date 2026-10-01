"""Per-model prompting recipes (Sept 2026 model guides) + a light lint that `refkit gen` runs before queueing.

The art director (Claude in the session) writes the final prompt; these recipes say what each model wants, and the
lint catches the usual mismatches (tag soup for a prose model, negatives a model ignores, unquoted text to render).
`refkit gen --recipe MODEL` prints a recipe.
"""
from __future__ import annotations

import re

RECIPES: dict[str, dict] = {
    "z-image": {
        "words": (80, 250), "negatives": False,
        "shape": "Long natural-language paragraph: shot type, subject, clothing/materials, setting, lighting, mood, "
                 "style, camera/lens. Put any text to render in double quotes.",
        "notes": "Turbo ignores negative prompts (cfg 1): describe what you want instead. 8 steps. Sizes: multiples "
                 "of 16, ~1-2 MP. Fast drafts and variations; use Qwen/Krea for finals.",
    },
    "qwen": {
        "words": (30, 200), "negatives": False,
        "shape": "Natural sentences. Exact text in double quotes, placed first when it matters. Describe layout "
                 "top-to-bottom for posters/infographics. For a transparent asset add: 'This is an RGBA image with "
                 "transparency.'",
        "notes": "Best open model (typography, layout, 2K native). cfg 1 (negatives only work above cfg 1 and double "
                 "the time). Up to ~4 MP; don't push to 4K. Non-commercial licence (research use).",
    },
    "qwen-edit": {
        "words": (8, 120), "negatives": False,
        "shape": "Instruction style. Refer to inputs as <image1>, <image2>… in order. Say what changes and what "
                 "stays: '… Keep everything else the same.'",
        "notes": "Best open editor; multi-reference compositing. Non-commercial licence.",
    },
    "krea": {
        "words": (30, 150), "negatives": False,
        "shape": "Prose, like describing a real photograph: subject, setting, light, lens, film/colour character. "
                 "Comma tag lists work but waste the model.",
        "notes": "Most photographic open model (catalogue/product realism). Turbo: 8 steps, cfg 1. 1-2 MP.",
    },
    "klein-edit": {
        "words": (8, 80), "negatives": False,
        "shape": "Subject -> action -> style -> context; earlier words weigh more. Instruction + 'Keep everything "
                 "else the same.' for edits. Every -i image is a reference, in order.",
        "notes": "FLUX.2 klein 4B distilled, 4 steps: fast edits and restyles (Apache 2.0).",
    },
    "banana": {
        "words": (15, 250), "negatives": False,
        "shape": "Sentences, not keywords: subject, composition, action, location, style + camera/lens/lighting. "
                 "Write the exact text first, then ask for the image that contains it. Say each reference's role "
                 "('use image 1 for the product, image 2 for the lighting'). Phrase positively.",
        "notes": "Nano Banana 2 (cloud, paid ~$0.07-0.15). Up to 14 refs, 4K, Search grounding (--ground in "
                 "nanobanana.py). When a result is 80% right, fix it with a follow-up edit instead of rerolling.",
    },
    "veo": {
        "words": (20, 200), "negatives": True,
        "shape": "Camera work -> subject -> action -> context -> style/mood. Dialogue in quotes; label sounds "
                 "'SFX:' / 'Ambient:'. Multi-shot in one clip with timestamps '[00:00-00:02] …'.",
        "notes": "Veo 3.1 (cloud). With --from/--to keyframes, describe only the motion, not what the frames show.",
    },
    "omni": {
        "words": (15, 200), "negatives": False,
        "shape": "Describe the scene and motion; add 'single unbroken scene, no scene cuts' unless you want cuts. "
                 "No negative field: put exclusions in prose ('No dialogue'). Timecodes '[0-3s]' work. Edits: short "
                 "instruction + 'Keep everything else the same.'",
        "notes": "Gemini Omni Flash (cloud, best Google video model, ~$0.10/s at 720p; 1080p/4K are upscales).",
    },
}
RECIPES["banana-pro"] = {**RECIPES["banana"], "notes": "Nano Banana Pro (cloud): ~2x NB2's price and ranks below it; "
                                                        "try only when NB2 fails a dense layout."}

_TAGGY = re.compile(r"^(?:[\w\s\-]{1,24},\s*){6,}")          # "a, b, c, d, e, f, …" keyword soup
_NEG = re.compile(r"\b(no|without|avoid|don't|do not)\b", re.I)


def lint(model: str, prompt: str) -> list[str]:
    r = RECIPES.get(model)
    if not r:
        return []
    tips = []
    words = len(prompt.split())
    lo, hi = r["words"]
    if words < lo:
        tips.append(f"{model} works best with {lo}-{hi} words; this prompt has {words}. {r['shape']}")
    elif words > hi * 1.5:
        tips.append(f"{words} words is long for {model} (sweet spot {lo}-{hi}); trim repetition.")
    if _TAGGY.match(prompt) and model not in ("veo", "omni"):
        tips.append(f"{model} is a prose model: write sentences instead of a comma tag list.")
    if not r["negatives"] and len(_NEG.findall(prompt)) >= 2:
        tips.append(f"{model} has no negative prompt; several 'no/without' phrases can pull those things in. "
                    "Describe what should be there instead.")
    wants_text = re.search(r"\b(text|words?|title|label|says|reading)\b", prompt, re.I)
    no_text = re.search(r"\b(no|without)\s+(text|words|lettering)\b", prompt, re.I)
    if wants_text and not no_text and '"' not in prompt:
        tips.append("Text to render should be in double quotes, e.g. a label that reads \"TEA\".")
    return tips


def recipe(model: str) -> str:
    r = RECIPES.get(model)
    if not r:
        return f"no recipe for {model!r}; known: {', '.join(RECIPES)}"
    lo, hi = r["words"]
    return f"{model}  ({lo}-{hi} words, negatives: {'yes' if r['negatives'] else 'no'})\n  prompt: {r['shape']}\n  notes:  {r['notes']}"
