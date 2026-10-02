# Installed tools (checked 2026-10-01) — use directly when simpler than refkit

Needs Windows 11 + an NVIDIA GPU with 16 GB (reference build: RTX 4080 SUPER, 64 GB RAM). Shims in `~\.local\bin`.
Versions below are the reference build's; `REQUIREMENTS.md` in the repo lists what this machine actually has.
From Git Bash, `.cmd` shims need the extension (`blender.cmd`); pwsh/cmd/Python resolve them normally.

## Brains
| Tool | Use |
|---|---|
| Claude (this session / `claude` CLI) | art direction, looking at references and outputs, writing prompts, final pick, code, SVG by hand |
| Gemini via own key (`GEMINI_API_KEY`, paid) | Nano Banana 2 / Pro / Lite images, Gemini Omni 1.1 Flash + Veo 3.1 video — through `refkit gen -m banana`, `refkit video`, or `python <repo>\nanobanana.py` (cost estimate + `--yes`, spend log `<repo>\gemini-spend.csv`); `gemini-3.8-flash` text for bulk prompt writing/judging |
| Ollama | only if the user asks for fully offline text/vision |

## Local generation engine
| Tool | Where | Notes |
|---|---|---|
| ComfyUI 0.38 portable | `<engine>\ComfyUI`, `comfy` shim, http://127.0.0.1:8188 | torch 2.14.1+cu130; localhost only, `--disable-api-nodes`; speed flags from `refkit bench` (`--fast fp16_accumulation cublas_ops --high-ram --reserve-vram 1`); Comfy Kitchen INT8 attention is set per workflow by refkit (`ModelAttentionBackend` node; `REFKIT_ATTENTION="pytorch attention"` turns it off). refkit finds/starts it on 8188-8195 and shares Comfy Desktop's server |
| Comfy Desktop | Start menu "Comfy Desktop" | UI only; tracks the same portable install ("AIStudio (portable)"). Don't use its Update button — `<repo>\setup\update-tools.ps1` updates + syncs the version |
| Models | `<engine>\models` | images: Z-Image-Turbo, Qwen-Image 2.1 (+edit, RGBA, 9B prompt enhancers; LoRAs: AnyAngle, Consistency), Krea 2 Turbo (+style LoRA), FLUX.2 klein 4B, HiDream-O1 Dev · albedo: Marigold V2 (Qwen-Image-Edit 2509 + LoRA) · upscale: SeedVR2 3B/7B, 4x-UltraSharp, RealESRGAN · segment: SAM 3.1, BiRefNet · depth/geometry: Depth Anything 3, MoGe 2 · 3D: Pixal3D (+multi-view), TRELLIS.2, Hunyuan3D 2.1 · video: Wan 2.2 TI2V 5B + I2V 14B (lightx2v 4-step LoRA), FILM · downloaded, not wired yet: MoGe 3, TripoSplat · judging: Qwen3-VL-8B (`models\vlm`, 4-bit), EditScore LoRA, HPSv3++ NF4, PickScore (`models\scoring`) |
| API workflows | `<repo>\studio\workflows\*.api.json` | exported from the core templates (`.templates-version` stamp); `refkit smoke` re-exports + validates after updates |
| refkit venv | `<engine>\venvs\refkit` (py 3.12, torch 2.14.1+cu130) | opencv, scikit-image, vtracer, trimesh, pygltflib, spandrel, open3d, transformers 5.18, bitsandbytes 0.50, accelerate, peft, editscore, qwen-vl-utils, google-genai<3 |
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
`<repo>\setup\08-visual-tools.ps1`, `09-local-ai.ps1 [-SkipModels]` (template list + `$TorchBackend` in `lib.ps1`),
`update-tools.ps1` (weekly: ComfyUI latest stable + `refkit smoke` + Desktop version sync + refkit venv on
cu130), `90-check.ps1` (the `visual` area), `99-revert.ps1`. Torch in ComfyUI is upgraded by hand only (pip -s,
cu130 index), then `refkit smoke` + `refkit bench`.

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

## Judges — how far to trust them (first checks, 2026-10-01)
- HPSv3++ (text→image ranking): on a 3-image teapot brief it ranked as Claude did (the one that missed "TEA on the
  side" last). ~40 s for 3 images incl. load; the first run fetches its verified source once, then runs offline.
- EditScore (edit ranking vs the source): 9.59 vs 9.60 for two good recolour edits — it separates bad edits from
  good ones, not two good ones. ~25 s per edit, ~9 GB.
- Local critic (Qwen3-VL-8B pairwise): caught a genuinely inconsistent 4-view set; on the teapot set it put the
  brief-missing image second. Used to rank 3D view sheets and check view consistency; for images its verdicts are
  notes in `report.md`, not the order. ~24 s for 3 candidates, ~11.5 GB.
- Text read-back (qa, `gen` with quoted text): Qwen3-VL read 18/18 strings on 9 stylised posters and transcribed a
  misspelt "CAP BLANK" as written; tesseract read 3/12 of the same strings (so it is only an advisory fallback).
  ~17 s to load the VLM once, then <1 s per image.

## Version check (2026-10-02, primary sources)
ComfyUI v0.38.0 = latest release (pins templates 0.11.70 and comfy-kitchen 0.2.36, both installed; templates
0.11.74 exists on PyPI but follows the next ComfyUI pin) · torch 2.14.1, transformers 5.18.0, bitsandbytes 0.50.2 =
latest on PyPI · hpsv3-4bit a4c8dc5 = repo head · Qwen3-VL-8B-Instruct, AnyAngle LoRA, Consistency LoRA (updated
2026-10-01), HPSv3++ NF4 = current on Hugging Face · ComfyUI issue #16027 still open (refkit's per-workflow
attention, see above) · ComfyUI-Trellis2 last commit 2026-09-25, still no torch 2.14 wheels · LTX-2.5 still gated.
