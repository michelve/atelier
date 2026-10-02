# Atelier's weekly update on macOS: a launchd agent (no admin needed) that runs setup/update.ps1 on Sundays at 12:30.
# A run missed while the Mac sleeps happens when it wakes; one missed while it is off is skipped. -Unregister removes it.
param([switch]$Unregister)
. "$PSScriptRoot/../lib.ps1"

$domain = "gui/$(id -u)"
launchctl bootout "$domain/$LaunchLabel" 2>$null
if ($Unregister) {
    Remove-Item $LaunchPlist -ErrorAction Ignore
    Write-Ok 'Atelier launchd agent removed'
    return
}

Write-Step 'Registering the weekly update (launchd)'
New-Item -ItemType Directory -Force (Split-Path $LaunchPlist) | Out-Null
$pwsh = (Get-Command pwsh -CommandType Application | Select-Object -First 1).Source
Write-AtelierTemplate (Join-Path $PSScriptRoot 'com.atelier.update.plist') $LaunchPlist
(Get-Content $LaunchPlist -Raw).Replace('{{PWSH}}', $pwsh).Replace('{{HOME}}', $HOME) |
    Set-Content $LaunchPlist -Encoding utf8NoBOM -NoNewline
launchctl bootstrap $domain $LaunchPlist
if ($LASTEXITCODE) { throw "launchctl bootstrap failed (exit $LASTEXITCODE)" }
Write-Ok "$LaunchLabel (Sundays 12:30, as $env:USER)"
