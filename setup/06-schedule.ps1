# Phase 06 (ELEVATED; 02-admin.ps1 calls it): weekly update tasks in Task Scheduler under \AISetup\.
#   Sunday 11:00  update-tools -Part Admin  (winget, elevated)
#   Sunday 11:30  update-tools -Part User   (everything else, unelevated)
# A missed run (PC off) starts at the next opportunity. -Unregister removes both tasks.
param(
    [switch]$Unregister,
    [switch]$FastForwardRepos   # pass through to the user task: fast-forward clean repos, not just report
)
. "$PSScriptRoot\lib.ps1"
if (-not (Test-Admin)) { throw 'Run this from an elevated PowerShell.' }

$taskPath = '\AISetup\'
$tasks = [ordered]@{
    'Weekly update (admin)' = @{ Part = 'Admin'; At = '11:00'; RunLevel = 'Highest' }
    'Weekly update (user)'  = @{ Part = 'User';  At = '11:30'; RunLevel = 'Limited' }
}

if ($Unregister) {
    foreach ($name in $tasks.Keys) { Unregister-ScheduledTask -TaskPath $taskPath -TaskName $name -Confirm:$false -ErrorAction Ignore }
    Write-Ok 'AISetup scheduled tasks removed'
    return
}

Write-Step 'Registering weekly update tasks'
$pwsh = (Get-Command pwsh -CommandType Application | Select-Object -First 1).Source
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
foreach ($name in $tasks.Keys) {
    $t = $tasks[$name]
    $arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Root\update-tools.ps1`" -Part $($t.Part)"
    if ($FastForwardRepos -and $t.Part -eq 'User') { $arguments += ' -FastForwardRepos' }
    # Interactive logon type: runs as you while you're signed in, no stored password.
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel $t.RunLevel
    Register-ScheduledTask -TaskPath $taskPath -TaskName $name -Force `
        -Action (New-ScheduledTaskAction -Execute $pwsh -Argument $arguments -WorkingDirectory $Root) `
        -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $t.At) `
        -Principal $principal -Settings $settings `
        -Description "AISetup: keeps the AI toolchain current. Logs: $LogDir" | Out-Null
    Write-Ok "$taskPath$name  (Sundays $($t.At), $($t.RunLevel))"
}
