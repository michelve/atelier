# Phase 02 (ELEVATED): machine-wide changes, run once from an admin shell.
#   machine PATH cleanup, Developer Mode, Windows sudo, winget tool installs,
#   Node 25 (EOL) removal, jq moved from Chocolatey to winget.
param(
    [switch]$UpgradeAll   # also run `winget upgrade --all` at the end (review `winget upgrade` first)
)
. "$PSScriptRoot\lib.ps1"
if (-not (Test-Admin)) { throw 'Run this from an elevated PowerShell.' }
if (-not (Get-OldestBackup)) { throw 'Run 00-backup.ps1 first.' }
Start-PhaseLog '02-admin'

Write-Step 'machine PATH: drop duplicates and dead entries; move per-user dirs to the user PATH'
$homeKey = $HOME.ToLowerInvariant()
$userKeys = Get-RawPath User | ForEach-Object { ConvertTo-PathKey $_ }
$toUser = [Collections.Generic.List[string]]::new()
$seen = @{}
$kept = foreach ($entry in Get-RawPath Machine) {
    $key = ConvertTo-PathKey $entry
    if ($seen[$key]) { Write-Skip "dupe  $entry"; continue }
    $seen[$key] = $true
    if (-not (Test-Path ([Environment]::ExpandEnvironmentVariables($entry)))) { Write-Ok "dead  $entry"; continue }
    if ($key.StartsWith($homeKey)) {
        if ($userKeys -contains $key) { Write-Ok "per-user, already on user PATH  $entry" }
        elseif (Test-HasExecutables $entry) { $toUser.Add($entry); Write-Ok "per-user, moved to user PATH  $entry" }
        else { Write-Ok "per-user, no executables, dropped  $entry" }
        continue
    }
    $entry
}
Set-RawPath Machine $kept
if ($toUser.Count) { Set-RawPath User (@(Get-RawPath User) + $toUser) }
Update-SessionPath
Write-Ok "machine PATH now $($kept.Count) entries"

Write-Step 'Developer Mode (symlinks without admin) and sudo (opens elevated commands in a new window)'
$unlock = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
New-Item $unlock -Force | Out-Null
Set-ItemProperty $unlock -Name AllowDevelopmentWithoutDevLicense -Value 1 -Type DWord
$sudoKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Sudo'
New-Item $sudoKey -Force | Out-Null
Set-ItemProperty $sudoKey -Name Enabled -Value 1 -Type DWord   # 1 = forceNewWindow, the most conservative mode
Write-Ok 'Developer Mode on; sudo on (new-window mode)'

Write-Step 'winget: CLI toolbelt, document/image/web tools, shell tooling'
foreach ($id in $WingetPackages) { Install-WingetPackage $id }

Write-Step 'Node 25 (end-of-life) -> removed; 03-user-tools installs Node 24 LTS via fnm'
if (Test-WingetInstalled 'OpenJS.NodeJS') {
    winget uninstall --id OpenJS.NodeJS --exact --silent --disable-interactivity
    Write-Ok 'Node.js 25 uninstalled (global npm packages in %APPDATA%\npm are kept)'
} else { Write-Skip 'OpenJS.NodeJS not installed' }

Write-Step 'jq: drop the Chocolatey copy now that winget provides it'
if (Get-Command choco -ErrorAction Ignore) {
    if (choco list --exact jq --limit-output 2>$null) { choco uninstall jq -y --no-progress; Write-Ok 'choco jq removed' }
    else { Write-Skip 'choco jq not installed' }
}

& "$PSScriptRoot\06-schedule.ps1"

if ($UpgradeAll) {
    Write-Step 'winget upgrade --all'
    winget upgrade --all --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
}

Write-Host "`nDone. Close this window and continue with 03-user-tools.ps1 in a NEW (non-admin) terminal." -ForegroundColor Cyan
Stop-Transcript | Out-Null
