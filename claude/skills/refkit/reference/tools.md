# Installed tools (checked 2026-10-02) — use directly when simpler than refkit

Full set: Windows 11 + an NVIDIA GPU with 16 GB (reference build: RTX 4080 SUPER, 64 GB RAM). macOS (Apple
Silicon) runs the CPU/Metal part (analyze, vectorize, render, inspect, qa, Google models; optional experimental
engine for SAM/BiRefNet/depth/FILM) - `refkit status` lists it. Shims in `~/.local/bin`.
Versions below are the reference build's; `REQUIREMENTS.md` (Windows) / `REQUIREMENTS-macos.md` list what a machine
actually has. From Git Bash, `.cmd` shims need the extension (`blender.cmd`); pwsh/cmd/Python resolve them normally.

## Brains
| Tool | Use |
|---|---|
| Claude (this session / `claude` CLI) | art direction, looking at references and outputs, writing prompts, final pick, code, SVG by hand |
| Gemini via own key (`GEMINI_API_KEY`, paid) | Nano Banana 2 / Pro / Lite images, Gemini Omni 1.1 Flash + Veo 3.1 video — through `refkit gen -m banana`, `refkit video`, or `python <repo>\nanobanana.py` (cost estimate + `--yes`, spend log `<repo>\gemini-spend.csv`); `gemini-3.8-flash` text for bulk prompt writing/judging |
| Ollama | only if the user asks for fully offline text/vision |

## Local generation engine
| Tool | Where | Notes |
|---|---|---|
| ComfyUI 0.38.2 portable | `<engine>\ComfyUI`, `comfy` shim, http://127.0.0.1:8188 | torch 2.14.1+cu130; localhost only, `--disable-api-nodes`; speed flags from `refkit bench` (`--fast fp16_accumulation cublas_ops --high-ram --reserve-vram 1`); Comfy Kitchen INT8 attention is set per workflow by refkit (`ModelAttentionBackend` node; `REFKIT_ATTENTION="pytorch attention"` turns it off). refkit finds/starts it on 8188-8195 and shares Comfy Desktop's server |
| Comfy Desktop | Start menu "Comfy Desktop" | UI only; tracks the same portable install ("AIStudio (portable)"). Don't use its Update button — `<repo>\setup\update.ps1` updates + syncs the version |
| Models | `<engine>\models` | images: Z-Image-Turbo, Qwen-Image 2.1 (+edit, RGBA, 9B prompt enhancers; LoRAs: AnyAngle, Consistency), Krea 2 Turbo (+style LoRA), FLUX.2 klein 4B, HiDream-O1 Dev, Ming-Image-0.1-Design (its 27B prompt rewriter is skipped) · albedo: Marigold V2 (Qwen-Image-Edit 2509 + LoRA) · upscale: SeedVR2 3B/7B, 4x-UltraSharp, RealESRGAN · segment: SAM 3.1, BiRefNet · depth/geometry: Depth Anything 3, MoGe 3 (to3d's field-of-view estimate; the template's MoGe 2 is also present) · 3D: Pixal3D (+multi-view), TRELLIS.2, Hunyuan3D 2.1 · video: Wan 2.2 TI2V 5B + I2V 14B (lightx2v 4-step LoRA), FILM · downloaded, not wired: TripoSplat, Qwen-Image-Layered (see below) · judging: Qwen3-VL-8B (`models\vlm`, 4-bit), EditScore LoRA, HPSv3++ NF4, PickScore + DINOv2-base (to3d fidelity; HF cache in `models\scoring`) |
| API workflows | `<repo>\studio\workflows\*.api.json` | exported from the core templates (`.templates-version` stamp); `refkit smoke` re-exports + validates after updates |
| refkit venv | `<engine>\venvs\refkit` (py 3.12, torch 2.14.1+cu130) | opencv, scikit-image, vtracer, trimesh, pygltflib, spandrel, open3d, transformers 5.18, bitsandbytes 0.50, accelerate, peft, editscore (brings qwen-vl-utils), google-genai<3; open3d is for ad-hoc mesh work (refkit doesn't import it) |
| HPSv3++ scorer | `<engine>\tools\hpsv3-4bit` (own uv env, transformers <5.18) | `Stella2211/hpsv3-4bit` @ a4c8dc5 (MIT); `score.py` runs its `hpsv3pp-score` |

## Raster
`magick` (ImageMagick 7), `rembg`, `pngquant`, `oxipng` (`--strip safe` removes the prompt ComfyUI embeds in
PNGs), `cwebp`, `avifenc`, `exiftool`, `tesseract` (OCR), Affinity Photo 2 (GUI).

## Vector
`inkscape` 1.4 CLI, `potrace`, `vtracer`, `svgo`, `resvg`, Affinity Designer 2 and Figma (GUI; Figma MCP).

## 3D
`blender` 5.2 LTS (headless `-b -P script.py -- args`; Cycles OptiX; the shim picks the newest install), official
**Blender MCP** (connected to Claude), `gltf-transform` (optimize, meshopt, `--texture-compress ktx2|webp`,
inspect), `gltfpack`, `ktx`/`toktx`, `f3d` (thumbnails; not meshopt), trimesh/open3d in the refkit venv.

## Video / web
`ffmpeg`/`ffprobe` (libx264, libvpx-vp9, libsvtav1), OBS, Playwright (`python -m playwright`), three.js / R3F /
GSAP skills for code-side motion.

## Setup, update, verify
`<repo>\setup\shared\visual-tools.ps1`, `local-ai.ps1 [-SkipModels] [-WithEngine]` (everything it fetches is listed per
OS in `setup\atelier.jsonc`: `comfyTemplates` (their embedded models), `comfyPick` (single files, macOS engine),
`comfyExtraModels`, `comfySkipModels`, `refkitHfModels` (critic and scorer snapshots), `refkitHfCache` (DINOv2,
PickScore, CLIP processor), `refkitPackages`, `hps`, `torchBackend`), `check.ps1` (checks all of it; `-Deep` adds
refkit round trips + smoke). OS specifics live in `setup\windows\` and `setup\macos\` (`platform.ps1`, shims, scheduler).
`update.ps1` runs weekly (Windows: Task Scheduler `\Atelier\`; macOS: launchd; Sundays 12:30): Atelier's scoop/npm/uv tools, refkit venv on
cu130, then ComfyUI latest stable + Desktop version sync, then `refkit smoke` over both (it restarts our server onto
the new version when no jobs run). If one scoop app fails, it retries and reports what is still behind. The winget
prerequisites (Blender, FFmpeg, ...) need elevation, so it only reports them. `update.ps1 -Check` lists what is
behind without installing anything; run that before an audit. Torch in ComfyUI is upgraded by hand only (pip -s, cu130 index),
then `refkit smoke` + `refkit bench`.

## Looked at, not used (re-check at the next audit)
| Tool | Why not (verified 2026-10-01) |
|---|---|
| ComfyUI-Trellis2 (retexture any mesh) | prebuilt wheels stop at torch 2.10; ours is 2.14 (would need a CUDA-toolkit build) |
| SkinTokens / UniRig (auto-rig) | flash-attn + CUDA-toolkit builds on Windows |
| HADM (hand/anatomy detector) | Python 3.8 + torch 1.12 stack, no licence file |
| Qwen 2.1 "Fun Acc" 4-step | needs its own sampler (not loadable with core nodes) |
| Qwen 2.1 PE "pocket" 0.8B/2B | community-made, not official; the official 9B enhancers are installed |
| Qwen3.5-9B as the critic | needs compiled causal_conv1d on Windows; Qwen3-VL-8B is used instead |
| SAM 3D Objects, AniGen, SegviGen, Lyra 2, Hunyuan3D-Paint | 18-80 GB VRAM and/or Linux-only |
| Threestudio, Unique3D, TripoSR, Step1X-3D, Hi3DGen, TripoSG | older / lower quality than Pixal3D and TRELLIS.2 |
| Hunyuan3D 2.5/3.x, Sparc3D, LATTICE | no open weights |
| MiniMax H3 | licence excludes the US/EU/UK |
| In-graph FillHoles / WeldVertices | current Pixal3D/TRELLIS.2 graph output has 0-10 open edges; not worth a step |
| Quad retopology (`--quads`): AutoRemesher 1.2.0, Blender QuadriFlow | AutoRemesher ignores `--target-quads` on generated meshes (8000 asked -> 91-107k quads, ~6 min); QuadriFlow refuses them (non-manifold), also after a voxel remesh (2026-10-02) |
| Qwen-Image-Layered (`refkit layers`) | the text layer of a poster kept a chunk of sky/sea; 640 px max (72 s); weights kept, revisit with Ming-Design-Layer once ComfyUI has a template |
| UV unwrap `adaptive` segmenter | 4x the charts of `pec` on the camera (8335 vs 2091), 145 s vs 3.6 s, same texture |
| Structure grid 64 (`to3d`) | 636 s, 15.3 GB and a broken fragment of a mesh |
| comfy-mcp (Comfy-Org, AGPL beta) | ~40 extra tools in every session's context; refkit covers production. The user's call: one `claude mcp add` if wanted |

## Judges — how far to trust them (first checks, 2026-10-01)
- HPSv3++ (text→image ranking): on a 3-image teapot brief it ranked as Claude did (the one that missed "TEA on the
  side" last). ~40 s for 3 images incl. load; the first run fetches its verified source once, then runs offline.
- EditScore (edit ranking vs the source): 9.59 vs 9.60 for two good recolour edits — it separates bad edits from
  good ones, not two good ones. ~25 s per edit, ~9 GB.
- Local critic (Qwen3-VL-8B pairwise): caught a genuinely inconsistent 4-view set; on the teapot set it put the
  brief-missing image second. Used to rank 3D view sheets and check view consistency; for images its verdicts are
  notes in `report.md`, not the order. ~24 s for 3 candidates, ~11.5 GB.
  It also called a set of wrong-angle AnyAngle views "consistent" (an image-order bug, now fixed and guarded
  by a silhouette check): never let the critic stand in for looking.
- What counts as text to check: a quoted string right after a cue ("the word", "reads", "headline text",
  "labelled", "titled", …) and the rest of a quoted list after it; quotes for emphasis or inch marks are ignored.
- More scorer evidence (2026-10-02): top pick matched Claude's on 3 of 3 sets for HPSv3++, 2 of 3 for PickScore.
  A wallet set where all four images ignored "lying open" was a tie for both — scorers don't catch a missed detail.
- Text read-back (qa, `gen` with quoted text): Qwen3-VL read 18/18 strings on 9 stylised posters and transcribed a
  misspelt "CAP BLANK" as written; tesseract read 3/12 of the same strings (so it is only an advisory fallback).
  ~17 s to load the VLM once, then <1 s per image.

## 3D defaults — the evidence (2026-10-01/02, same seeds)
- Golden before/after (old d9b54b9 code vs now; mug, camera, fox, teapot; seed 1234): silhouette IoU up on 4/4
  (mug .964->.980, camera .975->.993, fox .958->.977, teapot .977->.981), DINO up on the camera (.915->.940) and
  within 0.02 elsewhere. In the renders the models stand upright (levelled 2-15 deg), with crisper camera dials
  and teapot bamboo handle. Sheets: `<repo>\scratch\c1\compare-*.png` (scratch, not in git).
- Remesh: the template's 20 smoothing passes melt hard edges -> 3 passes + QEF (same time/VRAM). Upsample 1536 =
  `--quality high` (~14 GB, ~15% slower, lumpier smooth surfaces). MoGe 3: silhouette/DINO up on 2/2 objects.
- AO bake: following `--texture` (2048) cost ~50 s per run (teapot 125/129 s vs 72 s) for soft shading that
  doesn't need the resolution -> AO stays at <=1024; the normal map follows `--texture`.
- Comfy Kitchen attention on the 3D graph: no corruption on 0.38 (drift = noise; issue #16027 not reproduced);
  10-16% faster in the clean A/B. A later A/B with another session sharing the GPU showed no difference (too noisy
  to count).

## Not evaluated (stopped 2026-10-02 at the user's request; re-open deliberately)
SeedVR2 base-colour upscale for GLBs (B2; the script is in `<repo>\scratch\b2`), TripoSplat splat preview (B5),
Wan 2.2 first+last frame with the 4-step LoRA (B10), `--refine-views` on a hard-surface object (C4), a
fresh-session end-to-end run (C6), LTX-2.5 vs Wan (B11: gated, needs the user's Hugging Face token and licence
acceptance).

## Version check (2026-10-02, primary sources)
ComfyUI v0.38.2 = latest release (2026-10-02: templates 0.11.74, partner-node additions, a Qwen int8/int4-cache
crash fix), installed 2026-10-02 with comfy-kitchen 0.2.36; `refkit smoke` passed (restart onto 0.38.2, 22
workflows re-exported + validated, gen/cutout/to3d/render/critic). 0.11.74 only changed the Qwen 2.1 prompt
enhancer's settings (thinking off, 4096 tokens, the template's system prompt), which matters for `--enhance` · torch 2.14.1, transformers 5.18.0, bitsandbytes 0.50.2 =
latest on PyPI · hpsv3-4bit a4c8dc5 = repo head · Qwen3-VL-8B-Instruct, AnyAngle LoRA, Consistency LoRA (updated
2026-10-01), HPSv3++ NF4 = current on Hugging Face · ComfyUI issue #16027 still open (refkit's per-workflow
attention, see above) · ComfyUI-Trellis2 last commit 2026-09-25, still no torch 2.14 wheels · LTX-2.5 still gated.
