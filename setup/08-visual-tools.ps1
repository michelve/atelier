# Phase 08 (no admin): classic image / vector / 3D tools for the reference -> vector / 3D / motion pipeline.
#   scoop:  potrace, resvg, pngquant, cwebp (libwebp), avifenc (libavif), Inkscape + f3d (portable, extras bucket)
#   vtracer CLI (GitHub release binary)      npm: svgo, @gltf-transform/cli, gltfpack      scoop: ktx-software
#   `blender` shim in ~\.local\bin (newest Blender install) - refkit needs it on PATH
#   Blender: official Blender Lab MCP add-on (headless install) + the blender-mcp server as a uv tool; rembg (uv tool)
#   (No Ollama model: the Claude session is the vision model; `refkit analyze --describe gemini|ollama` is opt-in.)
. "$PSScriptRoot\lib.ps1"
Start-PhaseLog '08-visual-tools'
Update-SessionPath

Write-Step 'Backup (scoop list, npm globals, uv tools, Blender user prefs)'
$dest = Join-Path $BackupRoot "$(Get-Date -Format 'yyyyMMdd-HHmmss')-visual"
New-Item -ItemType Directory $dest | Out-Null
(scoop list 6>$null).Name | Set-Content "$dest\scoop.txt"
npm ls -g --depth=0 --json 2>$null | Set-Content "$dest\npm-globals.json"
uv tool list 2>$null | Set-Content "$dest\uv-tools.txt"
$blenderConfig = Get-ChildItem "$env:APPDATA\Blender Foundation\Blender" -Directory -ErrorAction Ignore |
    Sort-Object { [version]$_.Name } | Select-Object -Last 1
if ($blenderConfig -and (Test-Path "$($blenderConfig.FullName)\config\userpref.blend")) {
    Copy-Item "$($blenderConfig.FullName)\config\userpref.blend" "$dest\blender-userpref.blend"
}
Write-Ok $dest

Write-Step 'scoop: vector, raster-optimise and 3D viewer CLIs'
if ((scoop bucket list 6>$null).Name -notcontains 'extras') { scoop bucket add extras }
$have = (scoop list 6>$null).Name
foreach ($p in $VisualScoop) {
    if ($have -contains $p) { Write-Skip "$p already installed" }
    else { scoop install $p; Write-Ok $p }
}

Write-Step 'vtracer CLI (prebuilt release; cargo install needs the MSVC linker, which is not on PATH)'
if (Get-Command vtracer -ErrorAction Ignore) { Write-Skip 'already installed' }
else {
    $vtZip = Join-Path $env:TEMP 'vtracer-win.zip'
    # Plain release URL (no `gh auth login` needed on a fresh machine).
    curl.exe -fsSL -o $vtZip 'https://github.com/visioncortex/vtracer/releases/latest/download/vtracer-x86_64-pc-windows-msvc.zip'
    New-Item -ItemType Directory -Force "$HOME\.local\bin" | Out-Null
    Expand-Archive $vtZip -DestinationPath "$env:TEMP\vtracer-win" -Force
    Get-ChildItem "$env:TEMP\vtracer-win" -Recurse -Filter vtracer.exe | Select-Object -First 1 |
        Copy-Item -Destination "$HOME\.local\bin\vtracer.exe" -Force
    if (Test-Path "$HOME\.local\bin\vtracer.exe") { Write-Ok 'vtracer -> ~\.local\bin' } else { Write-Warn2 'vtracer.exe not found in the release zip' }
}

Write-Step 'npm: svgo + glTF tools (refkit to3d optimises GLBs with gltf-transform / gltfpack)'
npm install -g svgo @gltf-transform/cli gltfpack
Write-Ok "svgo $(svgo --version), gltf-transform, gltfpack"

Write-Step 'KTX-Software (ktx/toktx for `to3d --ktx2`) via scoop'
if ((scoop list 6>$null).Name -contains 'ktx-software') { Write-Skip 'already installed' }
else { scoop install ktx-software }

Write-Step 'Blender CLI shim (refkit calls `blender`)'
$shimDir = "$HOME\.local\bin"
New-Item -ItemType Directory -Force $shimDir | Out-Null
# Blender installs to a versioned dir ("Blender 5.2"); the shim resolves the newest one at run time.
@'
@echo off
for /d %%D in ("%ProgramFiles%\Blender Foundation\Blender *") do set "BLENDER_DIR=%%D"
"%BLENDER_DIR%\blender.exe" %*
'@ | Set-Content "$shimDir\blender.cmd" -Encoding ascii
Add-UserPath $shimDir
Write-Ok "blender shim -> $shimDir\blender.cmd"

Write-Step "Blender MCP add-on $BlenderMcpVersion (Blender Lab)"
$zip = Join-Path $env:TEMP "blender-mcp-$BlenderMcpVersion.zip"
Invoke-WebRequest "https://projects.blender.org/lab/blender_mcp/releases/download/v$BlenderMcpVersion/mcp-$BlenderMcpVersion.zip" -OutFile $zip
blender --command extension install-file -r user_default -e $zip
# The add-on refuses to start its localhost bridge unless Blender's "Allow Online Access" is on.
# Multi-line --python-expr doesn't survive Windows argument quoting, so the snippet goes through a file.
$prefsPy = Join-Path $env:TEMP 'blender-mcp-prefs.py'
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
$claudeCfg = try { Get-Content "$HOME\.claude.json" -Raw -ErrorAction Stop | ConvertFrom-Json -AsHashtable } catch { @{} }
if ($claudeCfg.mcpServers?.blender) { Write-Skip 'already connected' }
elseif (-not (Get-Command claude -ErrorAction Ignore)) {
    Write-Skip 'Claude Code not installed yet - the setup screen (Setup.cmd, step 6) connects it later'
} else {
    claude mcp add --scope user blender -- blender-mcp
    Write-Ok 'connected (restart Claude Code to load it)'
}

Write-Host @'

In Blender the MCP bridge auto-starts (Preferences > Add-ons > MCP). Headless:
  blender -b --online-mode scene.blend --command blender_mcp
'@ -ForegroundColor Cyan
Stop-Transcript | Out-Null
