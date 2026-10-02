"""`--auto` loops: generate -> score -> local critic -> checks, repeated until the checks pass or the round limit,
then a report (report.md + report.json) for the art director to read before looking at the top picks.

  refkit gen "…" --auto [-n 4] [--rounds 2] [-m qwen] [-i ref.png]
  refkit to3d cutout.png --auto [-n 3]

What it does NOT do: decide for you. The report ranks and explains; Claude still views the top 2-3 and chooses.
"""
from __future__ import annotations

import json
from pathlib import Path

from .common import log


def _critic(paths: list[Path], brief: str, ref: Path | None, kind: str) -> list[dict] | None:
    try:
        from . import critique, vlm
        ranked = critique.rank(paths, brief, ref, kind)
        vlm.unload()
        return ranked
    except (SystemExit, Exception) as e:   # not installed, import/driver error, OOM: scores only
        log(f"critic unavailable ({str(e)[:160]}); ranking by score only")
        return None


def _label(p) -> str:
    """to3d outputs are all model.glb: name them by their run folder (pixal3d-12/model.glb)."""
    p = Path(p)
    return f"{p.parent.name}/{p.name}" if p.name == "model.glb" else p.name


def write_report(dest: Path, title: str, rounds: list[dict], pick: dict) -> Path:
    lines = [f"# {title}", "", f"**Pick:** `{pick['path']}`" + (f" — {pick['why']}" if pick.get("why") else ""), ""]
    for i, r in enumerate(rounds, 1):
        score_col = r.get("score_name", "score")
        lines += [f"## Round {i}", "", f"| # | candidate | {score_col} | critic | notes |", "|---|---|---|---|---|"]
        critic = {c["path"]: c for c in r.get("critic") or []}
        for j, (p, s) in enumerate(r["ranked"], 1):
            c = critic.get(str(p), {})
            note = "; ".join(c.get("notes", []))[:160]
            lines.append(f"| {j} | `{_label(p)}` | {s} | {c.get('score', '-')} | {note} |")
        if r.get("text"):
            lines += ["", "Text check: " + ", ".join(
                f"{Path(p).name}: " + ("ok" if all(x['found'] for x in rows) else
                                       "missing " + ", ".join(x['text'] for x in rows if not x['found']))
                for p, rows in r["text"].items())]
        if r.get("contact"):
            lines += ["", f"![contact sheet]({Path(r['contact']).as_posix()})"]
        lines.append("")
    md = dest / "report.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    (dest / "report.json").write_text(json.dumps({"pick": pick, "rounds": rounds}, indent=2, default=str),
                                      encoding="utf-8")
    log(f"report: {md}")
    return md


def gen_loop(args, generate) -> dict:
    """`generate(seed_offset)` runs one batch and returns gen's result dict (with ranked/contact from --pick)."""
    from .qa import wanted_text
    rounds, pick = [], None
    ref = Path(args.image.split(",")[0]).resolve() if args.image else None
    for r in range(max(1, args.rounds)):
        res = generate(r * 1000)
        ranked = [(Path(x["path"]), x["score"]) for x in res.get("ranked", [])] or [(Path(o), 0) for o in res["outputs"]]
        top = [p for p, _ in ranked[:3]]
        # The reward-model ranking stays the order; the critic's pairwise verdicts are notes for the report. (First
        # check, 2026-10-01: HPSv3++ ranked a 3-image set as Claude did, the critic put the one that missed the
        # brief second.)
        critic = _critic(top, args.prompt, ref, "image") if len(top) > 1 else None
        order = top
        # gen already read the text of every candidate (res["text_check"]); check all of them, best score first.
        # Only a Qwen3-VL reading can veto a candidate: tesseract misreads stylised type (advisory, as in qa).
        everyone = [p for p, _ in ranked]
        texts = {str(p): res.get("text_check", {}).get(str(p), []) for p in everyone} if wanted_text(args.prompt) else {}
        good = [p for p in everyone
                if all(x["found"] or x.get("reader") != "qwen3-vl" for x in texts.get(str(p), []))]
        rounds.append({"ranked": [(str(p), s) for p, s in ranked], "critic": critic, "text": texts,
                       "contact": res.get("contact")})
        if good:
            pick = {"path": str(good[0]), "why": "best reward-model score"}
            if texts:
                pick["why"] += ", quoted text reads correctly"
            break
        log(f"round {r + 1}: no candidate passes the text check" + (", trying new seeds" if r + 1 < args.rounds else ""))
    if pick is None:
        pick = {"path": str(order[0]), "why": "best available; text check failed in every round — look closely"}
    dest = Path(args.out)
    report = write_report(dest, f"gen --auto: {args.prompt[:80]}", rounds, pick)
    return {"pick": pick["path"], "report": str(report), "rounds": len(rounds),
            "outputs": [p for r in rounds for p, _ in r["ranked"]]}


def to3d_loop(src: Path, runs: list[dict], base: Path) -> dict:
    """Rank finished to3d runs (their inspect sheets) with the critic against the input cutout."""
    sheets = [Path(r["sheet"]) for r in runs if r.get("sheet")]
    critic = _critic(sheets, "match the reference object", src, "3d") if len(sheets) > 1 else None
    by_sheet = {r["sheet"]: r for r in runs if r.get("sheet")}
    order = [by_sheet[c["path"]] for c in critic] if critic else runs
    if not critic:
        why = "only/first run"
    elif len({c["score"] for c in critic}) == 1:
        why = "no consistent critic preference (all tied) — choose from compare.png"
    else:
        why = "best by critic"
    pick = {"path": order[0]["glb"], "why": why}
    # The "score" column for 3D: open + non-manifold edges from inspect (lower is cleaner).
    rounds = [{"score_name": "open/non-manifold edges",
               "ranked": [(r["glb"], f"{r.get('stats', {}).get('boundary_edges', '-')}/"
                                     f"{r.get('stats', {}).get('non_manifold_edges', '-')}") for r in order],
               "critic": [{**c, "path": by_sheet[c["path"]]["glb"]} for c in critic] if critic else None,
               "contact": str(base / "compare.png") if (base / "compare.png").exists() else None}]
    report = write_report(base, f"to3d --auto: {src.name}", rounds, pick)
    return {"pick": pick["path"], "report": str(report)}
