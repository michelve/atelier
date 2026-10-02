# Atelier setup

`Setup.cmd` (Windows) or `Setup.command` (macOS) in the repo root opens the setup screen, `install.ps1`, which runs
everything below in order and shows each step's live status. The scripts are PowerShell 7 on both OSes, so you can
also run them one by one. Each one is idempotent and logs to `logs/` (git-ignored).

## Layout

```
setup/
  install.ps1  update.ps1  check.ps1   entry points (the setup screen, the weekly update, the check)
  lib.ps1                              shared helpers; loads atelier.jsonc and this OS's platform.ps1
  atelier.jsonc                        what gets installed, per OS ({all, windows, macos} lists)
  shared/    visual-tools.ps1, local-ai.ps1, link-skills.ps1, extra_model_paths.yaml
             py/  fetch-comfy-models.py, export-comfy-workflows.py, export-requirements.py
  windows/   platform.ps1 (winget/scoop, registry env + PATH, Task Scheduler, ComfyUI portable), schedule.ps1,
             comfy.cmd + refkit.cmd shim templates, sync-comfy-desktop.py
  macos/     platform.ps1 (Homebrew, ~/.config/atelier/env, Keychain, launchd, optional ComfyUI on Metal),
             schedule.ps1 + com.atelier.update.plist, comfy.sh + refkit.sh shim templates
```

Both `platform.ps1` files define the same functions (`Get-UserEnv`, `Set-Secret`, `Install-VisualPackages`,
`Install-Engine`, `Update-OsTools`, `Get-ScheduledUpdate`, ...); the shared scripts call those and never branch on
the OS themselves. Change one adapter, change the other.

## Scripts

| Script | Shell | What it does |
|---|---|---|
| `install.ps1` | normal | The setup screen: 10 steps, status probed from the machine. `-Status`, `-All`, `-Step N`, `-Engine DIR`, `-SkipModels` |
| `shared/visual-tools.ps1` | normal | Vector/raster/3D CLIs (Windows: scoop + the vtracer binary + KTX-Software; macOS: Homebrew + Inkscape cask), `svgo`, `gltf-transform`, `gltfpack`, the `blender` shim, `rembg`; official **Blender MCP** add-on (Blender Lab, enabled + online access) and the `blender-mcp` server (uv tool) |
| `shared/local-ai.ps1` | normal | The engine folder (`ATELIER_ENGINE`): the `refkit` venv and shim, the Claude Code skill links, the models, and ComfyUI (Windows: portable NVIDIA build, ~130 GB of models from the templates in `atelier.jsonc`, API-format workflows; macOS: optional `-WithEngine`, experimental, single files from `comfyPick`). Saves `ATELIER_ENGINE` and `ATELIER_ROOT`. `-SkipModels` to skip downloads |
| `shared/link-skills.ps1` | normal | Links `<repo>/claude/skills/*` into `~/.claude/skills` (junctions on Windows, symlinks on macOS; a real folder of the same name is left alone) |
| `check.ps1 [-Deep]` | normal, new terminal | Checks tools, engine, venv, weights, workflows, models, Blender MCP and the weekly task; `-Deep` adds refkit round trips and `refkit smoke` |
| `update.ps1 [-Check]` | normal | Weekly refresh: Atelier's OS tools (scoop / Homebrew), uv/npm tools, the refkit venv, ComfyUI (latest stable; Windows also syncs Comfy Desktop's record), `refkit smoke`, the requirements manifest; on Windows the winget prerequisites are only reported (they need elevation). `-Check` lists what is behind and installs nothing |
| `windows/schedule.ps1` | **elevated** | Registers `\Atelier\Weekly update` (Sundays 12:30, runs `update.ps1` unelevated); `-Unregister` removes it |
| `macos/schedule.ps1` | normal | Loads the launchd agent `com.atelier.update` (Sundays 12:30); `-Unregister` removes it |

The shim templates and `extra_model_paths.yaml` carry `{{REPO}}`/`{{ENGINE}}` instead of machine paths; local-ai
renders them into `~/.local/bin` and the engine folder. ComfyUI launch flags (from `refkit bench`) live in
`windows/comfy.cmd`: edit them there and re-run step 5, not in the rendered shim.

Gotchas: the embedded ComfyUI Python must run with `PYTHONNOUSERSITE=1` (a user site-packages with a CPU torch would
shadow the bundled CUDA one; the shims set it), but the workflow exporter needs the system Python's user site for
Playwright (local-ai and smoke clear the variable for it). Torch in ComfyUI is upgraded by hand only. On a Mac,
keep the clone and the engine out of `~/Documents`, `~/Desktop` and iCloud (launchd can't prompt for access).

A personal workstation bootstrap (PowerShell profile, starship, fonts, document and web CLIs, editor settings) used
to live here as `00`–`07`; it is its own repo now (devenv). Atelier needs none of it.
