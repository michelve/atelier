# AISetup — AI-first shell environment

Built 2026-09-27 from an audit of PowerShell, cmd, and the installed tooling. Each phase is idempotent,
logs to `logs\`, and `99-revert.ps1` restores config from the oldest backup.

## Run order

| Phase | Shell | What it does |
|---|---|---|
| `00-backup.ps1` | normal | Snapshots PATH, env, profile, Terminal, git, npm, Claude settings, package lists |
| `01-fix.ps1` | normal | Removes the git `insteadOf` loop (HTTPS via `gh`), cleans user PATH, updates uv |
| `02-admin.ps1` | **elevated** | Machine PATH cleanup, Developer Mode, sudo, all winget installs, removes Node 25 and choco jq. `-UpgradeAll` also runs `winget upgrade --all` |
| `03-user-tools.ps1` | normal, **new terminal** | Node 24 via fnm, npm prefix, Ghostscript, uv tools, Python doc libraries + Playwright, PowerShell modules |
| `04-shell.ps1` | normal | Profile, `PYTHONUTF8`, starship, clink, Windows Terminal, delta |
| `05-ai.ps1` | normal | `<repo>\{images,docs,web,scratch}` (git-ignored), `OLLAMA_MODELS` |
| `06-schedule.ps1` | **elevated** (02 calls it) | Weekly Task Scheduler jobs under `\AISetup\` that run `update-tools.ps1`: Sun 11:00 winget (admin), Sun 11:30 scoop/uv/Node 24.x/npm/pip/modules + fetch-only repo report (user). `-FastForwardRepos` to also fast-forward clean repos; `-Unregister` to remove. `update-tools.ps1 -Part User|Admin -Check` lists what is behind and installs nothing (report in `logs\last-check-<part>.txt`) |
| `07-web3d.ps1` | normal | 3D/WebGL toolchain: `gltf-transform`, `gltfpack`, KTX2 `toktx`/`ktx` (scoop), `blender` shim, TypeScript 6 + `typescript-language-server` + `pyright` (for Claude's LSP plugins), Ollama 32k context + q8 KV cache, VS Code glTF/GLSL/WGSL extensions, and moves PHP/WP/Angular/Vue/RN/MySQL extensions into a `PHP-Legacy` VS Code profile (`code --profile PHP-Legacy`) |
| `08-visual-tools.ps1` | normal | Vector/raster/3D CLIs: `inkscape`, `f3d`, `potrace`, `resvg`, `pngquant`, `cwebp`, `avifenc` (scoop, extras bucket), `vtracer` (release binary), `svgo`; official **Blender MCP** add-on (Blender Lab, enabled + online access) and the `blender-mcp` server (uv tool) |
| `09-local-ai.ps1` | normal | Atelier's local GPU stack in the engine folder (`ATELIER_ENGINE`, default `<repo>\engine`): ComfyUI portable (localhost, `--disable-api-nodes`), ~130 GB of ungated models read from the core templates listed in `lib.ps1`, the `refkit` venv, `comfy`/`refkit` shims, API-format workflows. `-SkipModels` to skip downloads |
| manual | — | Claude Code steps below |
| `90-check.ps1 -Deep` | normal, new terminal | Checks everything and runs end-to-end tests |

Elevated launch from Claude Code (`!` runs bash):
`! powershell.exe -NoProfile -Command "Start-Process pwsh -Verb RunAs -ArgumentList '-NoExit','-File','<repo>\setup\02-admin.ps1'"`

## Visual studio (refkit)

`refkit` (source `<repo>\studio\refkit`) turns a reference image into a polished deliverable, all locally:
`analyze` → `cutout` → `vectorize` / `gen` / `to3d` → `render` → `qa`. `refkit status` shows tools, models, servers
and VRAM. The `refkit` skill in `~\.claude\skills\refkit` teaches every Claude session the loop, so it works from any
project folder. Gotchas: the embedded ComfyUI Python must run with `PYTHONNOUSERSITE=1` (the legacy Python 3.13
user site has a CPU torch that shadows the bundled CUDA one; the `comfy` shim sets it); templates are UI graphs,
so `templates\export-comfy-workflows.py` converts them to API format through the real frontend.

## Manual Claude Code steps

Claude Code doesn't let an agent edit its own permissions and config, so do these yourself:

1. **Global context:** `Copy-Item ~\AISetup\templates\CLAUDE.md ~\.claude\CLAUDE.md` (edit to taste first).
2. **MCP servers** (run from `~`):
   - `claude mcp remove higgsfield -s local` (the unauthenticated duplicate; the claude.ai connector stays)
   - `claude mcp add playwright -s user -- cmd /c npx -y @playwright/mcp@latest`
   - `claude mcp add blender -s user -- blender-mcp` (official Blender MCP; Blender must be open, or headless `blender -b --online-mode x.blend --command blender_mcp`)
3. **GitHub MCP:** handled by the `claude` wrapper in `$PROFILE`, which sets `GITHUB_PERSONAL_ACCESS_TOKEN` from
   `gh auth token` when you launch `claude` from pwsh. (The desktop app and VS Code don't go through it.)
4. **`~\.claude\settings.json` permissions:**
   - Move `"Bash(git push *)"` from `allow` to `ask`, and add `"PowerShell(git push *)"` to `ask`.
   - Replace the deny rule `"Bash(del *.env)"` (cmd syntax, never matches) with
     `"Read(**/.env.local)"`, `"Read(**/.env.*.local)"`, `"Read(**/.env.production)"`.
   - Optional: `"stripe@claude-plugins-official": false` if you don't use Stripe (removes the SessionStart nag).
5. **`autoMode.environment`** in global settings describes only the `one repo` repo (e.g. "working directory").
   Consider rewording those lines so they read as "when working in <that repo>".
6. **Recommended Claude settings:** `templates\build-claude-settings.ps1` writes `templates\claude-settings.proposed.json`
   from your live settings plus: `defaultShell: powershell`, `cleanupPeriodDays: 90`, 5-minute Bash timeout,
   shell-agnostic status line, `Atelier's folder` as an extra directory, read-only allow rules for both shells, and
   autoMode notes that no longer assume one repo is the working directory. Review, then
   `Copy-Item ~\AISetup\templates\claude-settings.proposed.json ~\.claude\settings.json`.
   After a week of use, run `/fewer-permission-prompts` for anything still prompting.
7. `llm keys set anthropic` if you want `llm` to use Claude as well as Ollama.
8. **Claude plugins for 3D/web/LSP** (done 2026-09-27; re-run on a new machine):
   ```
   claude plugin install core-3d-animation@claude-design-skillstack
   claude plugin install meta-skills@claude-design-skillstack
   claude plugin install typescript-lsp@claude-plugins-official
   claude plugin install pyright-lsp@claude-plugins-official
   claude plugin install chrome-devtools-mcp@claude-plugins-official
   claude plugin install frontend-design@claude-plugins-official
   claude plugin install modern-web-guidance@claude-plugins-official
   ```
   Global TypeScript stays on 6.x: TS 7 is native and has no `tsserver` for `typescript-language-server`
   (`update-tools.ps1` re-pins it after `npm update -g`).
