# Installed tools (Sept 30 2026) — use directly when simpler than refkit

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
| ComfyUI 0.38 portable | `<engine>\ComfyUI`, `comfy` shim, http://127.0.0.1:8188 | torch 2.14.1+cu130; localhost only, `--disable-api-nodes`; speed flags from `refkit bench` (`--use-ck-attention --fast fp16_accumulation cublas_ops --high-ram --reserve-vram 1`). refkit finds/starts it on 8188-8195 and shares Comfy Desktop's server |
| Comfy Desktop | Start menu "Comfy Desktop" | UI only; tracks the same portable install ("AIStudio (portable)"). Don't use its Update button — `<repo>\setup\update-tools.ps1` updates + syncs the version |
| Models | `<engine>\models` (~130 GB) | images: Z-Image-Turbo, Qwen-Image 2.1 (+edit, RGBA, 9B prompt enhancers), Krea 2 Turbo (+style LoRA), FLUX.2 klein 4B · upscale: SeedVR2 3B/7B, 4x-UltraSharp, RealESRGAN · segment: SAM 3.1, BiRefNet · depth/geometry: Depth Anything 3, MoGe 2 · 3D: Pixal3D (+multi-view), TRELLIS.2, Hunyuan3D 2.1 · video finish: FILM · scoring: PickScore (`models\scoring`) |
| API workflows | `<repo>\studio\workflows\*.api.json` | exported from the core templates (`.templates-version` stamp); `refkit smoke` re-exports + validates after updates |
| refkit venv | `<engine>\venvs\refkit` (py 3.12, torch 2.14.1+cu130) | opencv, scikit-image, vtracer, trimesh, pygltflib, spandrel, open3d, transformers, google-genai<3 |

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
