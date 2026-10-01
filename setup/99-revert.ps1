# Phase 99: undo AISetup's config changes from a backup (default: the OLDEST, i.e. pre-change state).
# Installed packages are NOT removed automatically; the uninstall commands are printed at the end.
#   -Machine  also restore the machine PATH and turn Developer Mode / sudo back off (needs elevation)
param([string]$Backup, [switch]$Machine)
. "$PSScriptRoot\lib.ps1"
$src = $Backup ? (Get-Item $Backup) : (Get-OldestBackup)
if (-not $src) { throw 'No backup found.' }
if ($Machine -and -not (Test-Admin)) { throw '-Machine needs an elevated PowerShell.' }
Start-PhaseLog '99-revert'
Write-Step "Restoring from $($src.FullName)"

Set-RawPath User ((Get-Content "$src\path-user.txt" -Raw).Trim() -split ';')
Write-Ok 'user PATH'
if ($Machine) {
    Set-RawPath Machine ((Get-Content "$src\path-machine.txt" -Raw).Trim() -split ';')
    Remove-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -ErrorAction Ignore
    Remove-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Sudo' -Name Enabled -ErrorAction Ignore
    & "$PSScriptRoot\06-schedule.ps1" -Unregister
    Write-Ok 'machine PATH, Developer Mode, sudo, weekly update tasks'
}

# Only files the phase scripts write; Claude Code's own files are left to you.
$restore = [ordered]@{
    'profile.ps1'      = $PROFILE
    'wt-settings.json' = $WtSettings
    'gitconfig'        = "$HOME\.gitconfig"
    'npmrc'            = "$HOME\.npmrc"
    'starship.toml'    = "$HOME\.config\starship.toml"
}
$absent = @(Get-Content "$src\absent.txt" -ErrorAction Ignore)
foreach ($name in $restore.Keys) {
    if (Test-Path "$src\$name") { Copy-Item "$src\$name" $restore[$name] -Force; Write-Ok "restored $name" }
    elseif ($absent -contains $name -and (Test-Path $restore[$name])) { Remove-Item $restore[$name]; Write-Ok "removed $name (did not exist before)" }
}

# Phase 07: VS Code extensions/settings from its own backup, Ollama env vars, Blender shim.
$web3d = Get-ChildItem $BackupRoot -Directory -Filter '*-web3d' | Sort-Object Name | Select-Object -First 1
if ($web3d) {
    $now = @(code --list-extensions)
    Get-Content "$($web3d.FullName)\vscode-extensions.txt" | Where-Object { $now -notcontains $_ } |
        ForEach-Object { code --install-extension $_ | Out-Null; Write-Ok "reinstalled $_" }
    Copy-Item "$($web3d.FullName)\vscode-settings.json" "$env:APPDATA\Code\User\settings.json" -Force
    Write-Ok 'VS Code extensions + settings (the PHP-Legacy profile is left; delete it from the Profiles menu)'
}
'OLLAMA_CONTEXT_LENGTH', 'OLLAMA_KV_CACHE_TYPE' | ForEach-Object { [Environment]::SetEnvironmentVariable($_, $null, 'User') }
Remove-Item "$HOME\.local\bin\blender.cmd" -ErrorAction Ignore

# Phases 08/09: shims, Blender MCP add-on. The engine folder (ComfyUI, ~130 GB models, venv) is left; delete it by hand.
Remove-Item "$HOME\.local\bin\comfy.cmd", "$HOME\.local\bin\refkit.cmd", "$HOME\.local\bin\vtracer.exe" -ErrorAction Ignore
if (Get-Command blender -ErrorAction Ignore) { blender --command extension remove mcp 2>$null | Out-Null }
Write-Ok 'comfy/refkit/vtracer shims, Blender MCP add-on'

[Environment]::SetEnvironmentVariable('PYTHONUTF8', $null, 'User')
Remove-Item "$HOME\.local\bin\soffice.cmd", "$env:LOCALAPPDATA\clink\starship.lua" -ErrorAction Ignore
Remove-Item "$env:LOCALAPPDATA\pwsh-init-cache" -Recurse -ErrorAction Ignore
$clink = @("${env:ProgramFiles(x86)}\clink\clink.bat", "$env:ProgramFiles\clink\clink.bat") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($clink) { & $clink autorun uninstall; Write-Ok 'clink autorun off' }
Write-Ok 'PYTHONUTF8, soffice shim, init caches'

Write-Host @"

Packages were left installed. To remove them:
  winget uninstall --id <Id>          (ids are listed in 02-admin.ps1)
  uv tool uninstall markitdown llm trafilatura rembg
  scoop uninstall ghostscript
  npm uninstall -g @mermaid-js/mermaid-cli @gltf-transform/cli gltfpack typescript-language-server pyright
  scoop uninstall ktx-software
  scoop uninstall potrace resvg pngquant libwebp libavif inkscape f3d; npm uninstall -g svgo; uv tool uninstall blender-mcp
  Remove-Item -Recurse $StudioRoot   (ComfyUI, models, refkit venv); the skill junctions in ~\.claude\skills
  winget install --id OpenJS.NodeJS   (to go back to system-wide Node instead of fnm)
Claude Code changes (CLAUDE.md, MCP servers, permissions) were manual; undo them the same way.
"@ -ForegroundColor Cyan
Stop-Transcript | Out-Null
