# Phase 04 (no admin): shell experience.
#   PowerShell profile, UTF-8 for Python, starship, clink for cmd, Windows Terminal defaults, delta for git.
. "$PSScriptRoot\lib.ps1"
if (-not (Get-OldestBackup)) { throw 'Run 00-backup.ps1 first.' }
Start-PhaseLog '04-shell'
Update-SessionPath

Write-Step 'PowerShell profile'
New-Item -ItemType Directory -Force (Split-Path $PROFILE) | Out-Null
Copy-Item "$Templates\profile.ps1" $PROFILE -Force
Write-Ok "installed $PROFILE"

Write-Step 'PYTHONUTF8=1 (Python defaults to UTF-8 for files and pipes, without the system-wide UTF-8 beta)'
[Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'User')
Write-Ok 'set for the user'

Write-Step 'starship config (Catppuccin Mocha powerline)'
$starshipCfg = "$HOME\.config\starship.toml"
# Only replace a config AISetup wrote itself; a hand-made one is left alone.
if ((Test-Path $starshipCfg) -and -not (Select-String -Path $starshipCfg -SimpleMatch 'AISetup' -Quiet)) {
    Write-Skip 'starship.toml was not written by AISetup, left alone'
} else {
    New-Item -ItemType Directory -Force (Split-Path $starshipCfg) | Out-Null
    Copy-Item "$Templates\starship.toml" $starshipCfg -Force
    Write-Ok $starshipCfg
}

Write-Step 'cmd: clink (readline, history, completion) + starship prompt'
$clink = @("${env:ProgramFiles(x86)}\clink\clink.bat", "$env:ProgramFiles\clink\clink.bat") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($clink) {
    & $clink autorun install -- --quiet
    New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\clink" | Out-Null
    "load(io.popen('starship init cmd'):read('*a'))()" | Set-Content "$env:LOCALAPPDATA\clink\starship.lua" -Encoding ascii
    Write-Ok 'clink autorun on for this user; starship.lua installed'
} else { Write-Warn2 'clink not found - run 02-admin.ps1 first' }

Write-Step 'Windows Terminal: Nerd Font, longer scrollback, hide stale profiles'
if (Test-Path $WtSettings) {
    $wt = Read-JsonFile $WtSettings
    if ($null -eq $wt.profiles.defaults) { $wt.profiles.defaults = [ordered]@{} }
    $defaults = $wt.profiles.defaults
    $nerdFont = Get-ChildItem "$env:WINDIR\Fonts", "$env:LOCALAPPDATA\Microsoft\Windows\Fonts" -Filter 'JetBrainsMonoNerdFont*' -ErrorAction Ignore
    if ($nerdFont) {
        if (-not $defaults.font) { $defaults.font = [ordered]@{} }
        $defaults.font.face = 'JetBrainsMono Nerd Font'
        Write-Ok 'font: JetBrainsMono Nerd Font'
    } else { Write-Warn2 'Nerd Font not installed yet; font left unchanged' }
    $defaults.historySize = 20000
    # Catppuccin Mocha to match the starship palette; replaced by name so reruns don't duplicate it.
    $scheme = Read-JsonFile "$Templates\wt-catppuccin-mocha.json"
    $wt.schemes = @(@($wt.schemes | Where-Object { $_ -and $_.name -ne $scheme.name }) + $scheme)
    $defaults.colorScheme = $scheme.name
    Write-Ok "color scheme: $($scheme.name)"
    $hide = 'Azure Cloud Shell', 'Developer Command Prompt for VS 2019', 'Developer PowerShell for VS 2019',
            'Ubuntu-24.04', 'podman-machine-default'
    foreach ($profileEntry in $wt.profiles.list) {
        if ($hide -contains $profileEntry.name -and -not $profileEntry.hidden) {
            $profileEntry.hidden = $true
            Write-Ok "hidden: $($profileEntry.name)"
        }
    }
    Write-JsonFile $WtSettings $wt
} else { Write-Warn2 'Windows Terminal settings not found' }

Write-Step 'git: delta for human-facing diffs (git never pages when output is not a TTY, so agents are unaffected)'
if (Get-Command delta -ErrorAction Ignore) {
    git config --global core.pager delta
    git config --global interactive.diffFilter 'delta --color-only'
    git config --global delta.navigate true
    git config --global merge.conflictStyle zdiff3
    Write-Ok 'delta configured'
} else { Write-Warn2 'delta not found - run 02-admin.ps1 first' }

Write-Host "`nOpen a new terminal to load the profile, then run 90-check.ps1." -ForegroundColor Cyan
Stop-Transcript | Out-Null
