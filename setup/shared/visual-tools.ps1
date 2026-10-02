# Visual tools (no admin; the setup screen's step 4): classic image / vector / 3D tools for the reference -> vector / 3D / motion pipeline.
#   OS packages (setup\<os>\platform.ps1, Install-VisualPackages): potrace, resvg, pngquant, cwebp, avifenc, Inkscape,
#     f3d, KTX-Software (ktx/toktx) and the vtracer CLI - Windows: scoop (extras bucket) + the vtracer release binary
#   npm: svgo, @gltf-transform/cli, gltfpack
#   `blender` shim in ~/.local/bin (the installed Blender) - refkit needs it on PATH
#   Blender: official Blender Lab MCP add-on (headless install) + the blender-mcp server as a uv tool; rembg (uv tool)
#   (No Ollama model: the Claude session is the vision model; `refkit analyze --describe gemini|ollama` is opt-in.)
. "$PSScriptRoot/../lib.ps1"
Start-PhaseLog 'visual-tools'
Update-SessionPath
$tmp = [IO.Path]::GetTempPath()

Write-Step 'Backup (packages, npm globals, uv tools, Blender user prefs)'
$dest = Join-Path $BackupRoot "$(Get-Date -Format 'yyyyMMdd-HHmmss')-visual"
New-Item -ItemType Directory $dest | Out-Null
Backup-VisualState $dest
npm ls -g --depth=0 --json 2>$null | Set-Content "$dest/npm-globals.json"
uv tool list 2>$null | Set-Content "$dest/uv-tools.txt"
Write-Ok $dest

Write-Step $VisualToolsHeader
Install-VisualPackages

Write-Step 'npm: svgo + glTF tools (refkit to3d optimises GLBs with gltf-transform / gltfpack)'
npm install -g svgo @gltf-transform/cli gltfpack
Write-Ok "svgo $(svgo --version), gltf-transform, gltfpack"

Write-Step 'Blender CLI shim (refkit calls `blender`)'
Install-BlenderShim

Write-Step "Blender MCP add-on $BlenderMcpVersion (Blender Lab)"
$zip = Join-Path $tmp "blender-mcp-$BlenderMcpVersion.zip"
Invoke-WebRequest "https://projects.blender.org/lab/blender_mcp/releases/download/v$BlenderMcpVersion/mcp-$BlenderMcpVersion.zip" -OutFile $zip
blender --command extension install-file -r user_default -e $zip
# The add-on refuses to start its localhost bridge unless Blender's "Allow Online Access" is on.
# Multi-line --python-expr doesn't survive Windows argument quoting, so the snippet goes through a file.
$prefsPy = Join-Path $tmp 'blender-mcp-prefs.py'
@'
import bpy
bpy.context.preferences.system.use_online_access = True
bpy.ops.wm.save_userpref()
print("MCP-PREFS-OK online_access =", bpy.context.preferences.system.use_online_access)
'@ | Set-Content $prefsPy -Encoding utf8NoBOM
blender -b --python $prefsPy 2>&1 | Select-String 'MCP-PREFS-OK' | ForEach-Object { Write-Ok "$_" }

Write-Step 'blender-mcp server (uv tool)'
uv tool install --force "git+https://projects.blender.org/lab/blender_mcp.git@v$BlenderMcpVersion#subdirectory=mcp"
Write-Ok "blender-mcp -> $((Get-Command blender-mcp -ErrorAction Ignore).Source)"

Write-Step 'rembg (uv tool): background removal for `refkit analyze` and `cutout --engine rembg`, no ComfyUI needed'
uv tool install --upgrade 'rembg[cpu,cli]' --python 3.12
Write-Ok "rembg -> $((Get-Command rembg -ErrorAction Ignore).Source)"

Write-Step 'Connect Blender MCP to Claude Code (user scope)'
$claudeCfg = try { Get-Content "$HOME/.claude.json" -Raw -ErrorAction Stop | ConvertFrom-Json -AsHashtable } catch { @{} }
if ($claudeCfg.mcpServers?.blender) { Write-Skip 'already connected' }
elseif (-not (Get-Command claude -ErrorAction Ignore)) {
    Write-Skip 'Claude Code not installed yet - the setup screen (step 6) connects it later'
} else {
    claude mcp add --scope user blender -- blender-mcp
    Write-Ok 'connected (restart Claude Code to load it)'
}

Write-Host @'

In Blender the MCP bridge auto-starts (Preferences > Add-ons > MCP). Headless:
  blender -b --online-mode scene.blend --command blender_mcp
'@ -ForegroundColor Cyan
Stop-Transcript | Out-Null
