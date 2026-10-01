# Phase 00: snapshot everything later phases touch. Always writes a NEW timestamped folder;
# 99-revert.ps1 restores from the OLDEST one (the true pre-change state) unless told otherwise.
. "$PSScriptRoot\lib.ps1"
Start-PhaseLog '00-backup'

$dest = Join-Path $BackupRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
if (Get-ChildItem $BackupRoot -Directory) {
    Write-Warn2 "Earlier backup exists ($((Get-OldestBackup).Name)); it stays the default restore point."
}
New-Item -ItemType Directory $dest | Out-Null
Write-Step "Backing up to $dest"

(Get-RawPath User) -join ';'    | Set-Content "$dest\path-user.txt" -Encoding utf8NoBOM
(Get-RawPath Machine) -join ';' | Set-Content "$dest\path-machine.txt" -Encoding utf8NoBOM
reg export 'HKCU\Environment' "$dest\env-user.reg" /y | Out-Null
reg export 'HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' "$dest\env-machine.reg" /y | Out-Null
Write-Ok 'PATH + environment'

$files = [ordered]@{
    'profile.ps1'          = $PROFILE
    'wt-settings.json'     = $WtSettings
    'gitconfig'            = "$HOME\.gitconfig"
    'npmrc'                = "$HOME\.npmrc"
    'claude-settings.json' = "$ClaudeDir\settings.json"
    'claude-settings.local.json' = "$ClaudeDir\settings.local.json"
    'claude.json'          = "$HOME\.claude.json"
    'CLAUDE.md'            = "$ClaudeDir\CLAUDE.md"
    'starship.toml'        = "$HOME\.config\starship.toml"
}
foreach ($name in $files.Keys) {
    if (Test-Path $files[$name]) { Copy-Item $files[$name] "$dest\$name"; Write-Ok $name }
    else { Write-Skip "$name (did not exist)" }
}
# Record which files were absent so revert can delete what AISetup created.
$files.Keys | Where-Object { -not (Test-Path $files[$_]) } | Set-Content "$dest\absent.txt"

npm ls -g --depth=0 --json 2>$null | Set-Content "$dest\npm-globals.json"
uv tool list 2>$null             | Set-Content "$dest\uv-tools.txt"
git config --global --list       | Set-Content "$dest\git-config.txt"
winget export -o "$dest\winget-export.json" --accept-source-agreements --disable-interactivity 2>$null | Out-Null
Write-Ok 'package inventories'

Stop-Transcript | Out-Null
