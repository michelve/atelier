# ELEVATED (registering a task needs it; the task itself runs as you, unelevated): Atelier's weekly update.
#   Sunday 12:30  setup\update.ps1 - after any other Sunday-morning updaters, so the smoke test sees their result.
# A missed run (PC off) starts at the next opportunity. -Unregister removes it.
param([switch]$Unregister)
. "$PSScriptRoot\..\lib.ps1"
if (-not (Test-Admin)) { throw 'Run this from an elevated PowerShell.' }

$taskPath = '\Atelier\'
$name = 'Weekly update'
if ($Unregister) {
    Unregister-ScheduledTask -TaskPath $taskPath -TaskName $name -Confirm:$false -ErrorAction Ignore
    Write-Ok 'Atelier scheduled task removed'
    return
}

Write-Step 'Registering the weekly update task'
$pwsh = (Get-Command pwsh -CommandType Application | Select-Object -First 1).Source
$setup = Split-Path $PSScriptRoot
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$setup\update.ps1`""
# Interactive logon type: runs as you while you're signed in, no stored password.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskPath $taskPath -TaskName $name -Force `
    -Action (New-ScheduledTaskAction -Execute $pwsh -Argument $arguments -WorkingDirectory $setup) `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '12:30') `
    -Principal $principal -Settings $settings `
    -Description "Atelier: refkit venv, ComfyUI, smoke test, requirements manifest. Logs: $LogDir" | Out-Null
Write-Ok "$taskPath$name  (Sundays 12:30, as $env:USERNAME, unelevated)"
