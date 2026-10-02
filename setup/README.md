# Atelier setup

`Setup.cmd` (repo root) opens the setup screen, `install.ps1`, which runs everything below in order and shows each
step's live status. These scripts are what it runs, so you can also run them one by one. Each one is idempotent and
logs to `logs\` (git-ignored).

| Script | Shell | What it does |
|---|---|---|
| `install.ps1` | normal | The setup screen: 10 steps, status probed from the machine. `-Status`, `-All`, `-Step N`, `-Engine DIR`, `-SkipModels` |
| `08-visual-tools.ps1` | normal | Vector/raster/3D CLIs: `inkscape`, `f3d`, `potrace`, `resvg`, `pngquant`, `cwebp`, `avifenc` (scoop, extras bucket), `vtracer` (release binary), `svgo`, `gltf-transform`, `gltfpack`, KTX-Software, the `blender` shim, `rembg`; official **Blender MCP** add-on (Blender Lab, enabled + online access) and the `blender-mcp` server (uv tool) |
| `09-local-ai.ps1` | normal | The local GPU stack in the engine folder (`ATELIER_ENGINE`, default `<repo>\engine`): ComfyUI portable (localhost, `--disable-api-nodes`), ~130 GB of ungated models read from the core templates listed in `lib.ps1`, the `refkit` venv, the `comfy`/`refkit` shims, API-format workflows, the Claude Code skill links. Saves `ATELIER_ENGINE` and `ATELIER_ROOT`. `-SkipModels` to skip downloads |
| `link-skills.ps1` | normal | Links `<repo>\claude\skills\*` into `~\.claude\skills` (junctions; a real folder of the same name is left alone) |
| `check.ps1 [-Deep]` | normal, new terminal | Checks tools, engine, venv, weights, workflows, models, Blender MCP and the weekly task; `-Deep` adds refkit round trips and `refkit smoke` |
| `update.ps1 [-Check]` | normal | Weekly refresh: Atelier's scoop/npm/uv tools, the refkit venv, ComfyUI (latest stable) + Comfy Desktop's record, `refkit smoke`, the requirements manifest; reports winget prerequisites that are behind. `-Check` lists what is behind and installs nothing |
| `windows\schedule.ps1` | **elevated** | Registers `\Atelier\Weekly update` (Sundays 12:30, runs `update.ps1` unelevated); `-Unregister` removes it |
| `lib.ps1` | — | Shared paths and data: `$ComfyTemplates`, `$ComfyExtraModels`, `$ComfySkipModels`, `$RefkitHfModels`, `$RefkitHfCache`, `$RefkitPackages`, `$TorchBackend`, `$VisualScoop`, `$AtelierWinget`, `$BlenderMcpVersion`, `$HpsCommit` |

Templates (`templates\`): the `comfy`/`refkit` shims and `extra_model_paths.yaml` (rendered with this clone's and the
engine's paths), the model fetcher (`fetch-comfy-models.py`), the workflow exporter (`export-comfy-workflows.py`,
UI templates to API format through the real ComfyUI frontend), the requirements manifest (`export-requirements.py`)
and Comfy Desktop's version sync (`sync-comfy-desktop.py`).

Gotchas: the embedded ComfyUI Python must run with `PYTHONNOUSERSITE=1` (a user site-packages with a CPU torch would
shadow the bundled CUDA one; the `comfy` shim sets it). Torch in ComfyUI is upgraded by hand only.

A personal Windows shell/workstation bootstrap (PowerShell profile, starship, fonts, document and web CLIs, editor
settings) used to live here as `00`–`07`; it is its own repo now (devenv). Atelier needs none of it.
