"""refkit critique: a local first-pass judge, so Claude only has to look closely at the top 2-3 candidates.

  refkit critique a.png b.png c.png --brief "what was asked"      rank images against the brief
  refkit critique a.png b.png --ref ref.png --brief "…"           …and against a reference image
  refkit critique run1/inspect/views.png run2/… --ref cutout.png --kind 3d     rank 3D view sheets
  refkit critique front.png left.png back.png right.png --consistency          same object in every view?

Pairwise and order-swapped (A vs B, then B vs A): a verdict only counts when both orders agree, which removes the
position bias single-shot VLM judging has; ties and flips score half. Runs Qwen3-VL-8B locally (vlm.py).
The critic pre-sorts; the decision stays with the art director (Claude), who looks at the top picks.
"""
from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

from . import vlm
from .common import RefkitError, log

PAIR_PROMPT = {
    "image": (
        "You are a strict art director comparing two candidate images (Image A, then Image B){ref}.\n"
        "Brief: {brief}\n"
        "Judge: faithfulness to the brief{ref_short}, composition, correct anatomy/objects, legible and correct text "
        "if any, and visible generation artifacts (warped details, extra fingers, smeared textures, garbled text).\n"
        'Answer with JSON only: {{"winner": "A" or "B", "reason": "<one short sentence>"}}'),
    "3d": (
        "You are a 3D art director comparing two generated 3D models. Each candidate is a contact sheet: top row "
        "textured renders, bottom row grey clay renders of the same views (Candidate A, then Candidate B){ref}.\n"
        "Brief: {brief}\n"
        "Judge: shape and proportions{ref_short}, clean surfaces in the clay row (no holes, lumps, melted or "
        "staircase areas, keeps the edges it should), texture quality and seams, plausible back and sides.\n"
        'Answer with JSON only: {{"winner": "A" or "B", "reason": "<one short sentence>"}}'),
}
CONSISTENCY_PROMPT = (
    "These images are meant to be the same single object seen from the front, left, back and right (in that order), "
    "for 3D reconstruction. Check: same object identity, same proportions and colours, details that agree between "
    "views, nothing invented or missing.\n"
    'Answer with JSON only: {"consistent": true or false, "problems": ["<short>", ...]}')


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def compare(a: Path, b: Path, brief: str, ref: Path | None, kind: str) -> tuple[str, str]:
    """One ordered comparison -> ('A'|'B'|'?', reason)."""
    prompt = PAIR_PROMPT[kind].format(
        brief=brief or "(none given: judge overall quality)",
        ref=", plus a reference image shown first" if ref else "",
        ref_short=" and to the reference" if ref else "")
    images = ([ref] if ref else []) + [a, b]
    out = _json(vlm.ask(images, prompt, max_new_tokens=120))
    w = str(out.get("winner", "?")).strip().upper()[:1]
    return (w if w in ("A", "B") else "?"), str(out.get("reason", ""))


def rank(items: list[Path], brief: str = "", ref: Path | None = None, kind: str = "image") -> list[dict]:
    """Round-robin of order-swapped pairs. Score: 1 per consistent win, 0.5 each for a tie/flip."""
    score = {p: 0.0 for p in items}
    notes: dict[Path, list[str]] = {p: [] for p in items}
    for x, y in itertools.combinations(items, 2):
        w1, r1 = compare(x, y, brief, ref, kind)   # x is A
        w2, r2 = compare(y, x, brief, ref, kind)   # y is A
        first = {"A": x, "B": y}.get(w1)
        second = {"A": y, "B": x}.get(w2)
        if first is not None and first == second:
            score[first] += 1
            notes[first].append(f"beat {Path(y if first == x else x).parent.name or 'other'}: {r1 or r2}")
        else:
            score[x] += 0.5
            score[y] += 0.5
    ranked = sorted(items, key=lambda p: -score[p])
    return [{"path": str(p), "score": score[p], "notes": notes[p][:3]} for p in ranked]


def consistency(views: list[Path]) -> dict:
    out = _json(vlm.ask(views, CONSISTENCY_PROMPT, max_new_tokens=200))
    return {"consistent": bool(out.get("consistent", False)), "problems": out.get("problems", [])}


def main(args) -> dict:
    items = [Path(p).resolve() for p in args.images]
    for p in items:
        if not p.exists():
            raise RefkitError(f"refkit: no such file: {p}")
    if args.consistency:
        res = consistency(items)
        log(("consistent" if res["consistent"] else "NOT consistent") +
            (": " + "; ".join(map(str, res["problems"])) if res["problems"] else ""))
        return res
    if len(items) < 2:
        raise RefkitError("refkit: critique needs at least two candidates (or --consistency)")
    ref = Path(args.ref).resolve() if args.ref else None
    ranked = rank(items, args.brief or "", ref, args.kind)
    for i, r in enumerate(ranked, 1):
        log(f"#{i} {r['score']:.1f}  {r['path']}" + (f"  — {r['notes'][0]}" if r["notes"] else ""))
    log("pre-sorted by the local critic; look at the top 2-3 yourself before choosing")
    return {"ranked": ranked}
