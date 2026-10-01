# Phase 01 (no admin): repair what the audit found broken.
#   git URL rewrite loop, user PATH dupes/dead entries, outdated uv.
# Claude Code config changes (permissions, MCP servers, CLAUDE.md) are manual - see README.md.
. "$PSScriptRoot\lib.ps1"
if (-not (Get-OldestBackup)) { throw 'Run 00-backup.ps1 first.' }
Start-PhaseLog '01-fix'

Write-Step 'git: remove the https<->ssh insteadOf loop, use HTTPS via gh'
foreach ($key in 'url.https://github.com/.insteadof', 'url.git@github.com:.insteadof') {
    if (git config --global --get-all $key) { git config --global --unset-all $key; Write-Ok "unset $key" }
    else { Write-Skip "$key not set" }
}
gh config set git_protocol https
gh auth setup-git
Write-Ok 'gh is now the git credential helper for github.com (SSH commit signing unchanged)'

Write-Step 'user PATH: drop duplicates, dead entries, and copies of machine-wide dirs'
$machineKeys = Get-RawPath Machine | ForEach-Object { ConvertTo-PathKey $_ }
$homeKey = $HOME.ToLowerInvariant()
$seen = @{}
$kept = foreach ($entry in Get-RawPath User) {
    $key = ConvertTo-PathKey $entry
    if ($seen[$key]) { Write-Skip "dupe  $entry"; continue }
    $seen[$key] = $true
    if (-not (Test-Path ([Environment]::ExpandEnvironmentVariables($entry)))) { Write-Ok "dead  $entry"; continue }
    # Per-user dirs belong here (02-admin removes their machine copies); anything else already on the machine PATH is redundant.
    if ($machineKeys -contains $key -and -not $key.StartsWith($homeKey)) { Write-Ok "machine-dupe  $entry"; continue }
    $entry
}
Set-RawPath User $kept
Update-SessionPath
Write-Ok "user PATH now $($kept.Count) entries"

Write-Step 'uv: self update'
uv self update
Write-Ok (uv --version)

Stop-Transcript | Out-Null
