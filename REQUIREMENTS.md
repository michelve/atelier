# Requirements

Generated 2026-09-30 by `setup/templates/export-requirements.py` from the live machine - re-run it after
installing or updating anything (`python setup\templates\export-requirements.py`).

## Platform
- **Windows 11 + NVIDIA GPU only** as built (Windows-11-10.0.26200-SP0). GPU: NVIDIA GeForce RTX 4080 SUPER, 616.92, 16376 MiB.
  The local models are int8/fp8 files with CUDA-only kernels (comfy-kitchen); Pixal3D/TRELLIS and SeedVR2 need
  CUDA. `nanobanana.py`, Blender, ffmpeg and the vector/QA tools are cross-platform; `setup/` is PowerShell + winget/scoop.
- Disk: models ~128 GB in `<engine>\models`; ComfyUI portable + venvs ~15 GB. `<engine>` =
  `ATELIER_ENGINE` (default `<repo>\engine`).
- Accounts/keys: `GEMINI_API_KEY` (user env var, paid Google calls). GitHub CLI login for the repo.

## Python
- `requirements.txt` - refkit venv + nanobanana deps (torch **2.14.1+cu130**, index **cu130**).
- `requirements-lock.txt` - exact versions in `<engine>\venvs\refkit`.
- System Python 3.14 libs (docs skills, workflow exporter): `python-docx`, `python-pptx`, `openpyxl`, `pypdf`, `pdfplumber`, `pymupdf`, `reportlab`, `playwright`, `google-genai<3`.

## ComfyUI (engine)
- ComfyUI **v0.38.0** portable in `<engine>\ComfyUI` - embedded torch 2.14.1+cu130 python 3.13.14.
- Launch flags (from `refkit bench`): see `setup/templates/comfy.cmd`. Model folders: `setup/templates/extra_model_paths.yaml`.
- Key packages in the embedded Python:
  - `comfy-aimdo==0.5.5`
  - `comfy-angle==0.1.1`
  - `comfy-kitchen==0.2.36`
  - `comfyui-embedded-docs==0.5.12`
  - `comfyui_frontend_package==1.53.6`
  - `comfyui_workflow_templates==0.11.70`
  - `comfyui-workflow-templates-core==0.3.361`
  - `comfyui-workflow-templates-json==0.1.96`
  - `comfyui-workflow-templates-media-api==0.3.84`
  - `comfyui-workflow-templates-media-assets-01==0.1.48`
  - `comfyui-workflow-templates-media-assets-02==0.1.6`
  - `comfyui-workflow-templates-media-image==0.3.160`
  - `comfyui-workflow-templates-media-other==0.3.229`
  - `comfyui-workflow-templates-media-video==0.3.101`
  - `kornia==0.8.3`
  - `kornia_rs==0.1.14`
  - `spandrel==0.4.2`
  - `torch==2.14.1+cu130`
  - `torchaudio==2.11.0+cu130`
  - `torchsde==0.2.6`
  - `torchvision==0.29.1+cu130`
  - `transformers==5.15.1`
- Core templates driven by refkit (models are downloaded from their embedded lists by `setup/09-local-ai.ps1`):
  - `image_z_image_turbo_int8`
  - `image_flux2_klein_image_edit_4b_distilled`
  - `utility_image_segment_sam3`
  - `utility_depth_anything3_image_depth_estimation`
  - `utility-gan_upscaler`
  - `3d_pixal3d_trellis2_image_to_model`
  - `3d_hunyuan3d-v2.1`
  - `image_qwen_image_2_1_t2i`
  - `image_qwen_image_2_1_image_edit`
  - `image_qwen_image_2_1_background_removal`
  - `image_krea2_turbo_t2i_int8`
  - `image_krea2_turbo_int8_image_style_reference`
  - `utility_seedvr2_3b_int8_upscale_image`
  - `utility_seedvr2_7b_int8_upscale_image`
  - `utility_seedvr2_3b_int8_upscale_video`
  - `utility_video_frame_interpolation`
  - `3d_pixal3d_multi_views`

## CLI tools
| Tool | Version | Install source |
|---|---|---|
| `python` | 3.14.7 | python.org / winget (3.12+) |
| `uv` | 0.12.19 | winget/astral |
| `node` | 24.21.0 | fnm (Node 24 LTS) |
| `git` | 2.55.0.windows.3 | winget |
| `gh` | 2.102.0 | winget |
| `blender` | 5.2.2 | winget BlenderFoundation.Blender |
| `ffmpeg` | 9.0.2-full_build | winget Gyan.FFmpeg |
| `magick` | 7.1.2-31 | winget ImageMagick |
| `exiftool` | 13.59 | winget |
| `oxipng` | 10.2.1 | winget |
| `tesseract` | 5.4.0.20240606 | winget UB-Mannheim |
| `inkscape` | 1.4.4 | scoop extras |
| `potrace` | 1.16 | scoop |
| `vtracer` | 1.0.0-alpha.4 | release exe ~\.local\bin |
| `resvg` | 0.47.0 | scoop |
| `svgo` | 4.1.0 | npm -g |
| `pngquant` | 2.17.0 | scoop |
| `cwebp` | 1.6.0 | scoop libwebp |
| `avifenc` | 1.4.2 | scoop libavif |
| `f3d` | 3.5.0 | scoop extras |
| `gltf-transform` | 4.5.0 | npm -g @gltf-transform/cli |
| `gltfpack` | 1.3 | npm -g |
| `ktx` | 4.4.2 | scoop ktx-software |
| `rembg` | 2.0.85 | uv tool (py3.12) |
| `blender-mcp` | 1.0.3 | uv tool (Blender Lab) |
| `claude` | 2.1.286 | npm/official installer |

Also installed by `setup/` (winget): `sharkdp.fd`, `junegunn.fzf`, `sharkdp.bat`, `ajeetdsouza.zoxide`, `ast-grep.ast-grep`, `dandavison.delta`, `jqlang.jq`, `MikeFarah.yq`, `chmln.sd`, `DuckDB.cli`, `charmbracelet.glow`, `dbrgn.tealdeer`, `ducaale.xh`, `JesseDuffield.lazygit`, `TheDocumentFoundation.LibreOffice`, `oschwartz10612.Poppler`, `QPDF.QPDF`, `UB-Mannheim.TesseractOCR`, `Typst.Typst`, `ImageMagick.ImageMagick`, `OliverBetz.ExifTool`, `Shssoichiro.Oxipng`, `yt-dlp.yt-dlp`, `Starship.Starship`, `chrisant996.Clink`, `Schniz.fnm`, `DEVCOM.JetBrainsMonoNerdFont`.
Scoop (visual): `potrace`, `resvg`, `pngquant`, `libwebp`, `libavif`, `inkscape`, `f3d`.

## Models (`<engine>\models`, 34 files, 128.4 GB)
| Folder | File | Size |
|---|---|---|
| `background_removal` | `birefnet.safetensors` | 0.44 GB |
| `checkpoints` | `hunyuan_3d_v2.1.safetensors` | 7.37 GB |
| `checkpoints` | `sam3.1_multiplex_fp16.safetensors` | 1.75 GB |
| `clip_vision` | `dino_v3_L_naf_fp32.safetensors` | 1.22 GB |
| `diffusion_models` | `flux-2-klein-4b-fp8.safetensors` | 4.07 GB |
| `diffusion_models` | `krea2_turbo_int8_convrot.safetensors` | 13.49 GB |
| `diffusion_models` | `pixal3d_int8_convrot.safetensors` | 5.58 GB |
| `diffusion_models` | `pixal3d_multiview_int8_convrot.safetensors` | 5.58 GB |
| `diffusion_models` | `qwen_image_2.1_int8_convrot.safetensors` | 7.26 GB |
| `diffusion_models` | `seedvr2_3b_int8_convrot.safetensors` | 3.46 GB |
| `diffusion_models` | `seedvr2_7b_int8_convrot.safetensors` | 8.33 GB |
| `diffusion_models` | `trellis_2_int8_convrot.safetensors` | 5.25 GB |
| `diffusion_models` | `z_image_turbo_int8_convrot.safetensors` | 6.20 GB |
| `frame_interpolation` | `film_net_fp16.safetensors` | 0.07 GB |
| `geometry_estimation` | `depth_anything_3_mono_large.safetensors` | 1.34 GB |
| `geometry_estimation` | `moge_2_vitl_normal_fp16.safetensors` | 0.66 GB |
| `loras` | `krea2_darkbrush.safetensors` | 0.47 GB |
| `loras` | `krea2_style_reference.safetensors` | 0.46 GB |
| `a4e4367c6dfa7288a00c550414478f865b875800` | `model.safetensors` | 3.94 GB |
| `text_encoders` | `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | 9.47 GB |
| `text_encoders` | `qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors` | 9.47 GB |
| `text_encoders` | `qwen3vl_4b_fp8_scaled.safetensors` | 5.24 GB |
| `text_encoders` | `qwen3vl_8b_int8_convrot.safetensors` | 9.35 GB |
| `text_encoders` | `qwen_3_4b.safetensors` | 8.04 GB |
| `text_encoders` | `qwen_3_4b_fp8_mixed.safetensors` | 5.63 GB |
| `upscale_models` | `4x-UltraSharp.safetensors` | 0.07 GB |
| `upscale_models` | `RealESRGAN_x4plus.safetensors` | 0.07 GB |
| `vae` | `ae.safetensors` | 0.34 GB |
| `vae` | `flux2-vae.safetensors` | 0.34 GB |
| `vae` | `qwen_image_2.1_vae_bf16.safetensors` | 0.68 GB |
| `vae` | `qwen_image_vae.safetensors` | 0.25 GB |
| `vae` | `seedvr2_ema_vae_fp16.safetensors` | 0.50 GB |
| `vae` | `trellis_2_shape_vae_bf16.safetensors` | 1.10 GB |
| `vae` | `trellis_2_texture_vae_bf16.safetensors` | 0.95 GB |

## Claude Code
- Skills in `claude/skills/` (junctioned into `~\.claude\skills`): `motion`, `refkit`.
- MCP: Blender MCP (`claude mcp add --scope user blender -- blender-mcp`).
