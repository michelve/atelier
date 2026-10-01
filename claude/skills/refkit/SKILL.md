---
name: refkit
description: Atelier, the local-first visual production pipeline — use in ANY project or folder for any image, logo, icon, illustration, SVG, UI graphic, texture, 3D model, render, turntable, video clip, animation/motion or visual asset, and whenever the user pastes or points to a reference/inspiration image ("make this", "match this", "recreate", "trace/vectorize", "turn into 3D", "cut out", "upscale", "animate", "render", "make a video", "polish", "production-ready"). Covers the whole chain analyze → cutout → vectorize → gen/edit → upscale → to3d → render → video → qa, model choice per job (local Qwen-Image 2.1 / Krea 2 / Z-Image / SeedVR2 vs paid Google Nano Banana / Omni / Veo), per-model prompting, best-of-N picking, detail checklists and recipes. Runs locally on the NVIDIA GPU; Claude is the eyes and art director; Google (own key) is the one approved cloud exception.
---

# refkit — reference in, polished deliverable out

You (Claude) are the art director and the vision model: look at every reference and every output yourself.
`refkit` does the mechanical work locally. Nothing new may depend on subscriptions or cloud services, except
**Google Gemini (Nano Banana, Gemini Omni, Veo) with the user's own key**, which is approved but **paid** — see
"Cost rules". Don't use Ollama unless asked.

`refkit` is on PATH everywhere (`~\.local\bin\refkit.cmd`); `refkit <cmd> -h` for options, `refkit status` for
what's installed/running. Source `<repo>\studio\refkit` (the Atelier git repo — fix bugs there, commit, keep it working
for all sessions). After a ComfyUI update: `refkit smoke`. To re-tune speed flags: `refkit bench`.
Paths below: `<repo>` = the Atelier clone, `<engine>` = `ATELIER_ENGINE` (ComfyUI, models, venvs; default
`<repo>\engine`); outputs default to `<repo>\images`. `refkit status` prints all three.

## The loop — every job, every time

1. **Brief.** Restate what's being made, for where (web page, app, print, deck, social), at what size/format,
   and what "done" means. Style comes from the prompt and the pasted inspiration (see "Style comes from the
   user"). Ask only if the target or medium is genuinely unclear.
2. **Analyze.** `refkit analyze <ref>` → read `<ref>.refkit/analysis.json` and VIEW `sheet.png`. Write down:
   subject, style, composition & camera, shapes and corner radii, materials & lighting, palette (hex),
   typography, and the small details that are easy to miss.
3. **Route** — pick the tool/model with the tables below (details in `reference/recipes.md`).
4. **Write the prompt for that model** (`refkit gen --recipe MODEL` prints its recipe; refkit also prints
   "prompt tip" warnings). Prompts containing `"` quotes → put them in a UTF-8 file and use `--prompt-file`
   (the .cmd shim re-splits quoted arguments).
5. **Explore → pick → finish.** Drafts: `-n 4 --pick` (PickScore ranks them, writes `contact.png` best-first) →
   VIEW the contact sheet, choose yourself (the score is a pre-sort, not the decision) → refine the prompt or fix
   with an edit (`qwen-edit` / `klein-edit`) → `refkit upscale` for the final size.
6. **QA.** `refkit qa <every deliverable> [--ref <reference>] [--tokens <project tokens.json>]`. Fix FAILs; fix
   WARNs or say why not. Walk the matching checklist in `reference/checklists.md`.
7. **Look again.** Side by side with the reference at 100% and at display size
   (`magick ref.png out.png +append cmp.png`, view it). Iterate until it holds up. Report paths, qa summary,
   seeds (every gen writes a `.json` sidecar), cost of any paid calls, and anything still imperfect.

## Which model / route

| Need | Default (local, free) | Pay for Google when |
|---|---|---|
| Drafts, variations, iteration | `gen -m z-image` (~3 s, 8 steps) `-n 4 --pick` | never |
| Photoreal / product hero | `gen -m krea` (most photographic) or `-m qwen` (best adherence, 2K) → `upscale` | 4K straight out, tiny legible print → `-m banana --yes` (NB2 4K $0.15) |
| Text, typography, posters, infographics, UI art | `gen -m qwen` (quote the exact text) | lots of exact text / factual data → `-m banana` (NB2; `nanobanana.py --ground` for real facts) |
| Edit / restyle / composite from references | `gen "…" -i a.png,b.png` (qwen-edit: `<image1>`, `<image2>`…; keeps ref size) · `-m klein-edit` for quick ones | > 3 refs, product placement across many refs, relighting → `-m banana` (≤ 14 refs) |
| Transparent asset | `gen -m qwen "… This is an RGBA image with transparency."` | — |
| Cut out a subject | `cutout` (BiRefNet) · `--prompt "the cup"` (SAM 3.1, pick objects) · `--engine qwen` (hair, fur, glass) | — |
| Bigger / sharper | `upscale` (SeedVR2 3B; `--model 7b` heroes; `--refine "prompt"` cleans generator artifacts first) | — (Google has no upscale API) |
| Logo, icon, flat art, must scale | `cutout` → `vectorize` → hand-finish SVG | — |
| 3D object for render / WebGL | `cutout` → `to3d` (Pixal3D) · `--views f,l,b,r` for turnarounds · `--ktx2` for GPU textures | — |
| Product 360° spin | `render model.glb` (Blender turntable: exact geometry) | — |
| Video clip from a still / keyframes | make keyframes locally with `gen` | `video "motion" --from a.png [--to b.png] --yes` (Omni default; `-m veo-fast` for first+last/extension) |
| Text-to-video | — | `video "…" --yes` (Omni 720p ≈ $0.10/s) |
| Existing Blender scene | `render FILE.blend --as-is` (keeps its camera, frames, colour), or Blender MCP | — |

Local model licences: Qwen-Image 2.1 is non-commercial (research licence), Krea 2 is free under $1M revenue — the
user's work is personal, so both are fine; for client/commercial work use z-image, klein-edit, or Nano Banana.

## Commands

| Command | What it does | Key options |
|---|---|---|
| `refkit analyze IMG` | palette, edges, subject mask, depth, OCR, route hint, contact sheet | `--colors 8` `--fast` `--describe gemini` |
| `refkit gen "PROMPT"` | local text→image (z-image default) | `-m z-image\|qwen\|krea` `--size 1344x768` `-n 4 --pick` `--seed` `--enhance` (template prompt enhancer) `--prompt-file` `--recipe MODEL` `--out DIR` |
| `refkit gen "EDIT" -i a.png[,b.png]` | edit/composite from references (qwen-edit default) | `-m klein-edit` (fast) `--size` (else keeps ref size) |
| `refkit gen … -m banana[-pro] --yes` | Nano Banana 2 / Pro (cloud, paid) | `--size` → nearest aspect + 2K/4K |
| `refkit upscale IMG` | SeedVR2 detail-restoring upscale (keeps alpha) | `--scale 2` `--long 4096` `--model 7b` `--refine "prompt" --denoise 0.3` |
| `refkit cutout IMG` | RGBA subject, decontaminated edges | `--prompt "cube, sphere:2"` (SAM 3.1) `--engine qwen\|rembg` `--feather 0.8` |
| `refkit vectorize IMG` | trace → exact-palette SVG, best of presets by SSIM | `--palette "#hex,…"` `--preset clean\|balanced\|detailed\|flat` `--mono` (auto light/dark ink) |
| `refkit to3d IMG` | textured PBR GLB (Pixal3D) → cleanup → meshopt | `-m pixal3d\|trellis2\|hunyuan3d` `--views f,l,b,r` `--tris 60000` `--texture 2048` `--ktx2` `--seed` |
| `refkit render FILE` | Cycles OptiX turntable/still → MP4 + WebM + AVIF/WebP | `--frames 96` (1 = still) `--res` `--samples` `--look neutral\|orbitra` `--transparent` `--av1` `--as-is` |
| `refkit video "MOTION" --yes` | Gemini Omni / Veo clip (paid) + optional local finish | `-m omni\|veo-fast\|veo\|veo-lite` `--from IMG` `--to IMG` `--ref IMG` `--seconds` `--aspect 9:16` `--continue ID` `--upscale` `--interp 2` · `--finish-only` on an existing clip |
| `refkit qa FILES` | raster/svg/glb/video checks (metadata, halo, budgets, faststart, loop seam…) | `--ref IMG` `--tokens FILE` `--json` |
| `refkit status` / `smoke` / `bench` | health · post-update test · speed-flag A/B | |

Direct Google access (more options): `python <repo>\nanobanana.py -h` (refs up to 14, `--ground`,
`--thinking high`, Omni `--continue`/`--extend`, Veo `--ref`/`--negative`).

## Prompting (details: `refkit gen --recipe MODEL`)

- **z-image**: 80–250-word natural paragraph (shot, subject, materials, setting, light, mood, lens). No negatives.
- **qwen**: natural sentences, exact text in `"double quotes"` first, layout top-to-bottom for posters; add
  "This is an RGBA image with transparency." for cut-outs. **qwen-edit**: instruction + `<image1>`/`<image2>` +
  "Keep everything else the same."
- **krea**: 30–150 words of prose, like describing a real photograph (light, lens, film/colour character).
- **klein-edit**: subject → action → style → context, short; earlier words weigh more.
- **Nano Banana**: sentences, exact text first, say each reference's role; if a result is 80% right, fix it
  with a follow-up edit (`-i result.png "change only X"`) instead of re-rolling.
- **Video** (Omni/Veo): describe only the motion when keyframes are given; one camera move relative to the
  subject; Omni: "single unbroken scene, no scene cuts", exclusions in prose (no negative field); Veo: quoted
  dialogue, `SFX:`/`Ambient:` labels, `[00:00-00:02]` shot timestamps.

## Cost rules (Google, own key — every image/video call is paid, no free tier)

- Every paid command prints `cost estimate: $…` and **does nothing without `--yes`**. Show the estimate to the
  user and get a yes for anything over ~$1, for batches, or when they didn't ask for cloud output.
- Prices (Sept 2026): NB2 $0.067 (1K) / $0.101 (2K) / $0.151 (4K); Pro $0.134 / $0.24 (4K); NB2 Lite $0.034;
  Omni ≈ $0.10/s at 720p (default 6 s; 1080p/4K are only upscales — use `--upscale` locally); Veo 3.1 Fast
  $0.10/s 720p, $0.12 1080p (first+last frame, refs, 1080p all force 8 s); Veo 3.1 $0.40/s; Lite $0.05/s.
- Every call is logged in `<repo>\gemini-spend.csv`; report the total you spent in the handoff.
- NB2 ranks above Pro at ~half the price — use Pro only when NB2 fails a dense layout.
- EU/UK rules: no minors in uploaded images; Omni can't edit/extend *uploaded* videos (its own are fine).

## References (read when relevant)

- `reference/checklists.md` — small-detail checklist per deliverable. **Read before declaring anything done.**
- `reference/recipes.md` — step-by-step recipes and troubleshooting.
- `reference/tools.md` — every installed tool, model and path.

## Style comes from the user, never from defaults

There is **no house style**. The look (palette, borders, corner radius, glow/shadows, lighting, materials,
motion) comes only from, in priority order: (1) what the user writes in the prompt, (2) the inspiration /
reference they paste, (3) the project's own design system or art direction **when the user is working on that
project and hasn't pasted something else**. Never add your own taste on top; if the reference has sharp corners,
teal, glow or heavy shadows, reproduce them. If the prompt and the reference disagree, the prompt wins; if it's
ambiguous, ask one short question.

- `refkit` defaults are style-neutral: `render --look neutral` (AgX base contrast, true-to-photo colour, studio reflections),
  `to3d --material keep`, `qa` checks only technical budgets. Colour rules apply only when passed explicitly:
  `--tokens <project tokens.json>` (example: `<repo>\studio\tokens\orbitra.json`), or
  `vectorize --palette` from the reference's own analyzed palette.
- Match the reference's perspective, placement and proportions exactly — that's fidelity, not style.
