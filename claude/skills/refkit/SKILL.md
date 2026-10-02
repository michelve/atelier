---
name: refkit
description: Atelier, the local-first visual production pipeline — use in ANY project or folder for any image, logo, icon, illustration, SVG, UI graphic, texture, 3D model, render, turntable, video clip, animation/motion or visual asset, and whenever the user pastes or points to a reference/inspiration image ("make this", "match this", "recreate", "trace/vectorize", "turn into 3D", "cut out", "upscale", "animate", "render", "make a video", "polish", "production-ready"). Covers the whole chain analyze → cutout → vectorize → gen/edit → upscale → to3d → render → video → qa, model choice per job (local Qwen-Image 2.1 / Krea 2 / Z-Image / SeedVR2 vs paid Google Nano Banana / Omni / Veo), per-model prompting, best-of-N picking, detail checklists and recipes. Runs locally (everything on the Windows NVIDIA PC; on a Mac: analyze, vectorize, render, QA and the Google models - `refkit status` says what runs); Claude is the eyes and art director; Google (own key) is the one approved cloud exception.
---

# refkit — reference in, polished deliverable out

You (Claude) are the art director and the vision model: look at every reference and every output yourself.
`refkit` does the mechanical work locally. Nothing new may depend on subscriptions or cloud services, except
**Google Gemini (Nano Banana, Gemini Omni, Veo) with the user's own key**, which is approved but **paid** — see
"Cost rules". Don't use Ollama unless asked.

`refkit` is on PATH everywhere (`~/.local/bin/refkit`, `refkit.cmd` on Windows); `refkit <cmd> -h` for options,
`refkit status` for what's installed/running (incl. how many ComfyUI jobs are running/queued) and, under
"capabilities", what this machine can run: a Mac has no CUDA, so to3d, upscale, fix, critique, bench and the local
gen/video models stop at once and name the alternative (Google models with --yes, or the Windows PC). Source `<repo>\studio\refkit` (the
Atelier git repo — fix bugs there, commit, keep it working for all sessions). After a ComfyUI update:
`refkit smoke` (it restarts our server onto the new version when no jobs run). To re-tune speed flags:
`refkit bench` (restarts ComfyUI; refuses while jobs run).
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
   (the Windows .cmd shim re-splits quoted arguments).
5. **Explore → pick → finish.** Drafts: `-n 4 --pick` (HPSv3++ ranks text→image, EditScore ranks edits against the
   source, PickScore if those aren't installed; writes `contact.png` best-first) or `--auto` (adds the local critic,
   a text check and a second round; writes `report.md`) → VIEW the contact sheet / report picks, choose yourself
   (scores and critic are a pre-sort, not the decision) → fix what's wrong with an edit (`qwen-edit`, `--consistent`
   to keep the frame) or a region fix (`refkit fix --region "hand"`) → `refkit upscale` for the final size.
6. **QA.** `refkit qa <every deliverable> [--ref <reference>] [--tokens <project tokens.json>]`. Fix FAILs; fix
   WARNs or say why not. 3D: look at every `inspect/views.png` (textured row + clay row) — holes, lumps, melted or
   lost edges, texture seams. Walk the matching checklist in `reference/checklists.md`.
7. **Look again.** Side by side with the reference at 100% and at display size
   (`magick ref.png out.png +append cmp.png`, view it). Iterate until it holds up. Report paths, qa summary,
   seeds (every gen writes a `.json` sidecar), cost of any paid calls, and anything still imperfect.

## Working well with refkit — what we've learned (measured 2026-09/10)

- **Read results, don't scrape logs.** Add `--json` to any command (one JSON line on stdout). Every output has a
  `<file>.json` sidecar: model, licence, seed, prompt (and the enhancer's rewrite), input hashes, scores, 3D
  fidelity. `refkit runs --last 10` lists recent runs. To vary or redo a result, start from its sidecar's seed.
- **Scores pre-sort; you decide.** HPSv3++ picked what Claude picked on 3 of 3 sets (PickScore 2 of 3). But
  when all four candidates missed "lying open", both scorers called it a tie. The critic also once called a set
  of wrong-angle views "consistent". So view the contact sheet, `compare.png` or `report.md` picks yourself,
  every time.
- **Text in images:** quote every visible word, after a cue: the word "OPEN", headline text "…", a sign that
  reads "…". `gen` and `qa` read it back with Qwen3-VL: 18/18 exact on stylised posters, and it catches
  misspellings. The tesseract fallback is advisory only. Ming renders quoted text exactly but fills unquoted text
  with gibberish, so quote all the copy or ask for none.
- **Fix, don't re-roll.** If an image is 80% right, edit it: `gen "change only X" -i best.png` (`--consistent`
  keeps the frame), or `fix --region "hand"`. A re-roll loses what was right.
- **Batch, don't loop.** `-n 4` queues every seed back to back with the model loaded; four separate calls reload
  it. `to3d -n 3` likewise generates all seeds before Blender runs.
- **The input decides 3D quality:**
  - One object, centred, on a plain light background, with soft even light and no cast shadow.
  - A 3/4 or front view, given as a cutout with alpha. Generate a clean one when the photo is busy.
  - For glossy or strongly lit photos, use `--delight`.
- **The defaults are tuned.** The current `to3d` beat the original pipeline on 4 of 4 golden objects (silhouette
  up on all; upright; crisper). `--quality high` and `--hard-edges` are trade-offs, not upgrades: compare them
  with a default run before keeping them.
- **3D judging:**
  - Fidelity compares the photo-side render with the cutout: silhouette ≥0.97 means a sound front; a broken
    mesh scored 0.69.
  - It cannot see the back. Check the backs and sides in the clay row of `inspect/views.png`.
- **The GPU is shared.** The user may run other Claude sessions on the same ComfyUI; `refkit status` shows
  `jobs: N running, M queued`.
  - Their jobs and yours wait in one queue, so don't start long batches without need: `--refine-views` (~10 min),
    `to3d -n 5`, several Wan clips.
  - Never kill or restart ComfyUI, and never run `refkit bench`, while jobs are running.
  - A timing taken while another session worked is skewed; compare ComfyUI's own execution times instead.
- **Paid calls are never tests.** Gemini Banana/Omni/Veo are only for deliverables the user asked for, with the
  estimate shown. Never use them to try something out or to compare models.
- **Measure, don't assume.** Before changing a default, run both versions with the same seed and look at both.
  An unmeasured "follow --texture" AO bake once cost ~50 s per 3D run for nothing. Put the numbers in a code
  comment and in `reference/tools.md`.

**Time budget** (RTX 4080 SUPER, models warm; the first job after another model adds loading time):

| Step | Time |
|---|---|
| `gen -m z-image` 1024² · `-m ming` · `qwen-edit` | ~3-8 s · ~6 s (18 s cold) · ~9-15 s |
| `cutout` (BiRefNet) · `--engine qwen` | ~1-2 s · ~18 s |
| `upscale` 2048→4096 (SeedVR2 3B) | ~26 s |
| `--pick` ranking 3-4 images (HPSv3++) · EditScore per edit · critic on 3 · VLM load | ~40 s · ~25 s · ~24 s · ~17 s |
| `fix --region` | ~40 s |
| `to3d` one seed (mesh ~75 s + cleanup, inspect, fidelity) · `--refine-views` | ~2 min · ~10 min |
| `video -m wan-fast` 5 s 480p · `-m wan` 5 s 720p | ~75 s · ~3.5 min |

## Which model / route

| Need | Default (local, free) | Pay for Google when |
|---|---|---|
| Drafts, variations, iteration | `gen -m z-image` (~3 s, 8 steps) `-n 4 --pick` | never |
| Photoreal / product hero | `gen -m krea` (most photographic) or `-m qwen` (best adherence, 2K) → `upscale` | 4K straight out, tiny legible print → `-m banana --yes` (NB2 4K $0.15) |
| Text, typography, posters, infographics, UI art | `gen -m ming` (UI screens, posters, infographics; ~6 s) or `-m qwen` — quote every visible word | lots of exact text / factual data → `-m banana` (NB2; `nanobanana.py --ground` for real facts) |
| Edit / restyle / composite from references | `gen "…" -i a.png,b.png` (qwen-edit: `<image1>`, `<image2>`…; keeps ref size) · `-m klein-edit` for quick ones | > 3 refs, product placement across many refs, relighting → `-m banana` (≤ 14 refs) |
| Transparent asset | `gen -m qwen "… This is an RGBA image with transparency."` | — |
| Cut out a subject | `cutout` (BiRefNet) · `--prompt "the cup"` (SAM 3.1, pick objects) · `--engine qwen` (hair, fur, glass) | — |
| Bigger / sharper | `upscale` (SeedVR2 3B; `--model 7b` heroes; `--refine "prompt"` cleans generator artifacts first) | — (Google has no upscale API) |
| Logo, icon, flat art, must scale | `cutout` → `vectorize` → hand-finish SVG | — |
| 3D object for render / WebGL | `cutout` → `to3d` (Pixal3D; levelled on its base; inspect sheet) · `--hard-edges` for hard-surface · `-n 3` / `--auto` to pick a seed · `--refine-views` for better backs/sides · `--delight` for glossy/lit photos · `--views f,l,b,r` for turnarounds · `--ktx2` for GPU textures | — |
| Product 360° spin | `render model.glb` (Blender turntable: exact geometry) | — |
| Video clip from a still / keyframes | keyframes with `gen`, then `video "motion" -m wan --from a.png` (Wan 2.2 5B, 720p, ~3.5 min per 5 s) · `-m wan-fast` (14B 4-step, 480p, ~75 s; drafts) | hero clips, first+last frame (`--to`), extension → `video "motion" --from a.png [--to b.png] --yes` (Omni default; `-m veo-fast` for first+last/extension) |
| Text-to-video | `video "…" -m wan` (720p) | `video "…" --yes` (Omni 720p ≈ $0.10/s) |
| Existing Blender scene | `render FILE.blend --as-is` (keeps its camera, frames, colour), or Blender MCP | — |

Local model licences (each output's `.json` sidecar names its model's licence): Qwen-Image 2.1 and its LoRAs are
non-commercial (research licence), Krea 2 is free under $1M revenue, Hunyuan3D 2.1 excludes the EU/UK/South Korea —
the user's work is personal and US-based, so all are fine; for client/commercial work use z-image, klein-edit,
hidream (MIT), Pixal3D/TRELLIS.2 (MIT), or Nano Banana.

## Commands

| Command | What it does | Key options |
|---|---|---|
| `refkit analyze IMG` | palette, edges, subject mask, depth, OCR, route hint, contact sheet | `--colors 8` `--fast` `--describe gemini` |
| `refkit gen "PROMPT"` | local text→image (z-image default) | `-m z-image\|qwen\|krea\|hidream\|ming` `--size 1344x768` `-n 4 --pick` `--auto [--rounds 2]` `--seed` `--enhance` (template prompt enhancer) `--prompt-file` `--recipe MODEL` `--out DIR` |
| `refkit gen "EDIT" -i a.png[,b.png]` | edit/composite from references (qwen-edit default) | `--consistent` (edit stays on the source's frame; not for pose/move edits) `-m klein-edit` (fast) `-m hidream-edit` `-m krea-style -i style.png` (new content in that look) `--size` (else keeps ref size) |
| `refkit fix IMG --region "hand" --prompt "…"` | redraw one region (SAM finds every instance), blend it back | `--mask FILE` `--engine qwen\|zimage` `--denoise` |
| `refkit gen … -m banana[-pro] --yes` | Nano Banana 2 / Pro (cloud, paid) | `--size` → nearest aspect + 2K/4K |
| `refkit upscale IMG` | SeedVR2 detail-restoring upscale (keeps alpha) | `--scale 2` `--long 4096` `--model 7b` `--refine "prompt" --denoise 0.3` |
| `refkit cutout IMG` | RGBA subject, decontaminated edges | `--prompt "cube, sphere:2"` (SAM 3.1) `--engine qwen\|rembg` `--feather 0.8` |
| `refkit vectorize IMG` | trace → exact-palette SVG, best of presets by SSIM | `--palette "#hex,…"` `--preset clean\|balanced\|detailed\|flat` `--mono` (auto light/dark ink) |
| `refkit to3d IMG` | textured PBR GLB (Pixal3D) → cleanup (levels it on its base) → meshopt → inspect sheet + fidelity score vs the photo; one folder per seed, `-n` runs sorted by fidelity | `-m pixal3d\|trellis2\|hunyuan3d` `--quality standard\|high` `--hard-edges` `-n N` `--auto` `--refine-views` `--delight` `--views f,l,b,r` `--tris 60000` `--texture 2048` `--ktx2` `--no-level` `--seed` |
| `refkit inspect MODEL.glb` | QA views: textured + clay rows from N angles → `views.png`, mesh facts → `stats.json` | `--views 8` `--res 640` |
| `refkit critique A B …` | local VLM (Qwen3-VL-8B) ranks candidates pairwise, both orders | `--brief "…"` `--ref IMG` `--kind image\|3d` `--consistency` (front/left/back/right views agree?) |
| `refkit runs` | recent runs from the index (model, seed, output); every output has a `.json` sidecar with licence + lineage | `--last 20` `--command to3d` |
| `refkit render FILE` | Cycles OptiX turntable/still → MP4 + WebM + AVIF/WebP | `--frames 96` (1 = still) `--res` `--samples` `--look neutral\|orbitra` `--ground` (contact shadow) `--transparent` `--av1` `--as-is` |
| `refkit video "MOTION" --yes` | local Wan 2.2 clip (free, `-m wan\|wan-fast`) or Gemini Omni / Veo (paid, default omni) + optional local finish | `-m wan\|wan-fast\|omni\|veo-fast\|veo\|veo-lite` `--from IMG` `--to IMG` `--ref IMG` `--seconds` `--aspect 9:16` `--continue ID` `--upscale` `--interp 2` · `--finish-only` on an existing clip |
| `refkit qa FILES` | raster/svg/glb/video checks (metadata, halo, budgets, faststart, loop seam…) | `--ref IMG` `--tokens FILE` `--json` |
| `refkit status` / `smoke` / `bench` | health, incl. ComfyUI jobs running/queued · post-update test (restarts our server onto a newer installed ComfyUI when no jobs run; incl. 3D, render, critic; `--quick` skips those) · speed-flag A/B (restarts ComfyUI per flag set; refuses while jobs run) | `bench --golden --label NAME [--compare OLD]` = the fixed-seed regression set (no restart) |

Every command takes `--json`: its result (paths, seeds, scores, warnings) as one JSON line on stdout, logs on
stderr — parse that instead of reading log text.

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
