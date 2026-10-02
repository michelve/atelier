# Weekly toolchain refresh, run by the scheduled tasks 06-schedule.ps1 registers (or by hand).
#   -Part Admin  winget upgrades for AISetup's packages (needs elevation)
#   -Part User   scoop, uv tools, Node 24.x, npm globals, Python doc libs + Playwright, PowerShell modules, tldr,
#                refkit venv, ComfyUI (latest stable) + `refkit smoke`, the requirements manifest,
#                then a fetch-only report on the git repos under -RepoRoot ($env:ATELIER_REPOS; skipped when unset)
#   -FastForwardRepos  also fast-forward repos that are clean and simply behind their upstream
#   -Check   dry path: list what each part would update and install nothing (no elevation needed; only scoop's
#            bucket index and ComfyUI's git tags are refreshed). The report goes to logs\last-check-<part>.txt,
#            so 90-check's last-update view stays about real updates
param(
    [Parameter(Mandatory)][ValidateSet('User', 'Admin')][string]$Part,
    [string]$RepoRoot = $env:ATELIER_REPOS,
    [switch]$FastForwardRepos,
    [switch]$Check
)
. "$PSScriptRoot\lib.ps1"
$ErrorActionPreference = 'Continue'   # one failing updater must not stop the rest
if (-not $Check) {
    if ($Part -eq 'Admin' -and -not (Test-Admin)) { throw '-Part Admin needs elevation.' }
    if ($Part -eq 'User' -and (Test-Admin)) { throw '-Part User must run unelevated (scoop and --user installs).' }
}
$mode = $Check ? 'check' : 'update'
$run = "$mode-$($Part.ToLower())"
Start-PhaseLog $run
Update-SessionPath

$summary = [Collections.Generic.List[string]]::new()
function Invoke-UpdateStep([string]$Name, [scriptblock]$Action) {
    Write-Step $Name
    try { & $Action; $summary.Add("ok    $Name") }
    catch { Write-Warn2 $_; $summary.Add("FAIL  $Name - $_") }
}

if ($Check) {
    # Each step prints what is behind; "ok" means the listing ran, not that everything is current.
    if ($Part -eq 'Admin') {
        Invoke-UpdateStep 'winget: AISetup packages with an update' {
            $ids = $WingetPackages + $WingetPreexisting
            $behind = Get-WinGetPackage | Where-Object { $_.IsUpdateAvailable -and $ids -contains $_.Id }
            $behind | ForEach-Object { $summary.Add("      $($_.Id) $($_.InstalledVersion) -> $($_.AvailableVersions[0])") }
            Write-Ok "$(@($behind).Count) of $($ids.Count) behind"
        }
    } else {
        Invoke-UpdateStep 'scoop' { scoop update | Out-Null; scoop status | Out-Host }
        Invoke-UpdateStep 'uv tools' {
            # blender-mcp comes from Blender Lab's git tag ($BlenderMcpVersion); uv compares it with an unrelated
            # PyPI package of the same name, so check the official tags instead.
            uv tool list --outdated | Select-String -NotMatch 'blender-mcp' | Out-Host
            $tag = git ls-remote --tags --refs https://projects.blender.org/lab/blender_mcp.git |
                ForEach-Object { ($_ -split 'refs/tags/v')[1] } | Sort-Object { [version]$_ } | Select-Object -Last 1
            if ($tag -ne $BlenderMcpVersion) { $summary.Add("      blender-mcp $BlenderMcpVersion -> $tag (bump `$BlenderMcpVersion in lib.ps1, re-run 08)") }
        }
        Invoke-UpdateStep 'Node 24.x' {
            $latest = fnm list-remote | Select-String -Pattern 'v24\.\d+\.\d+' | Select-Object -Last 1
            Write-Ok "installed $(node -v), latest $($latest.Matches.Value)"
        }
        Invoke-UpdateStep 'npm globals' { npm outdated -g --depth=0 | Select-String -NotMatch '^typescript ' | Out-Host }   # TS stays on 6 (see below)
        Invoke-UpdateStep 'Python doc libraries' {
            python -m pip list --user --outdated 2>$null | Select-String -Pattern ($PythonDocLibs -join '|') | Out-Host
        }
        Invoke-UpdateStep 'PowerShell modules' {
            foreach ($m in $PSModules) {
                $have = Get-InstalledPSResource -Name $m -Scope CurrentUser -ErrorAction Ignore | Sort-Object Version | Select-Object -Last 1
                $new = Find-PSResource -Name $m -ErrorAction Ignore
                if ($have -and $new -and $new.Version -gt $have.Version) { $summary.Add("      $m $($have.Version) -> $($new.Version)") }
            }
        }
        $comfy = "$StudioRoot\ComfyUI\ComfyUI"
        if (Test-Path "$comfy\.git") {
            Invoke-UpdateStep 'ComfyUI (latest stable tag)' {
                git -C $comfy fetch --tags --quiet   # refs only; the working tree is not touched
                $tag = git -C $comfy tag --list 'v*' --sort=-v:refname | Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } | Select-Object -First 1
                $summary.Add("      ComfyUI $(git -C $comfy describe --tags) installed, latest stable $tag")
            }
        }
        if (Test-Path "$StudioRoot\venvs\refkit\Scripts\python.exe") {
            Invoke-UpdateStep 'refkit venv packages' {
                uv pip list --python "$StudioRoot\venvs\refkit\Scripts\python.exe" --outdated | Out-Host
            }
        }
        Invoke-UpdateStep 'HPSv3++ runner (pinned commit)' {
            $head = ((git ls-remote $HpsRepo HEAD) -split '\s')[0]
            if (-not $head.StartsWith($HpsCommit)) {
                $summary.Add("      hpsv3-4bit pinned $HpsCommit, upstream $($head.Substring(0, 7)) (review, bump `$HpsCommit, re-run 09)")
            }
        }
    }
} elseif ($Part -eq 'Admin') {
    # winget reports "no update available" and "not installed" as error codes; neither is a failure here.
    $noChange = -1978335189, -1978335212   # 0x8A15002B UPDATE_NOT_APPLICABLE, 0x8A150014 NO_APPLICATIONS_FOUND
    Invoke-UpdateStep 'winget: AISetup packages' {
        foreach ($id in $WingetPackages + $WingetPreexisting) {
            winget upgrade --id $id --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
            if ($LASTEXITCODE -eq 0) { Write-Ok "upgraded $id" }
            elseif ($noChange -notcontains $LASTEXITCODE) { Write-Warn2 "$id exit $LASTEXITCODE" }
        }
    }
} else {
    Invoke-UpdateStep 'scoop' {
        scoop update; scoop update *
        # One failing app aborts the rest of `scoop update *` without an error here (2026-09-27: 7zip's MSI hit
        # 1618 "another install in progress", so gh/podman/act/supabase were skipped). Retry once, then report.
        $behind = { @(scoop status | Where-Object { $_.'Latest Version' -and $_.Info -notmatch 'Held' }) }
        $left = & $behind
        if ($left) { scoop update $left.Name; $left = & $behind }
        if ($left) { throw "still behind: $($left.Name -join ', ')" }
    }
    Invoke-UpdateStep 'uv + uv tools' { uv self update; uv tool upgrade --all }

    Invoke-UpdateStep 'Node 24.x (latest patch) via fnm' {
        fnm install 24 2>&1 | Out-Host
        fnm default 24
        # Keep only the newest 24.x so old patch releases don't pile up.
        $versions = fnm list | Select-String -Pattern 'v24\.\d+\.\d+' -AllMatches |
            ForEach-Object { $_.Matches.Value } | Sort-Object { [version]$_.TrimStart('v') } -Unique
        $versions | Select-Object -SkipLast 1 | ForEach-Object { fnm uninstall $_; Write-Ok "removed $_" }
        Write-Ok "node $(node -v)"
    }
    # `npm update -g` moves TypeScript to 7 (native, no tsserver); typescript-language-server needs 6.
    Invoke-UpdateStep 'npm globals' { npm update -g; npm install -g typescript@6 }

    Invoke-UpdateStep 'Python doc libraries + Playwright browser' {
        python -m pip install --user --upgrade --quiet $PythonDocLibs
        python -m playwright install chromium
    }
    Invoke-UpdateStep 'PowerShell modules' {
        Update-PSResource -Name $PSModules -Scope CurrentUser -TrustRepository -Quiet
    }
    Invoke-UpdateStep 'tldr pages' { tldr --update }
    # refkit's packages first, so the smoke test below covers them as well as the new ComfyUI.
    if (Test-Path "$StudioRoot\venvs\refkit\Scripts\python.exe") {
        Invoke-UpdateStep 'refkit venv packages' {
            # --upgrade can touch torch (spandrel depends on it): pin the CUDA backend or it may resolve to CPU torch.
            uv pip install --python "$StudioRoot\venvs\refkit\Scripts\python.exe" --torch-backend $TorchBackend --upgrade torch torchvision $RefkitPackages
        }
    }
    if (Test-Path "$StudioRoot\ComfyUI\update\update.py") {
        # Latest *stable* release (what update_comfyui_stable.bat does), run with the embedded Python directly:
        # `cmd /c *.bat` breaks here because clink's cmd AutoRun changes the working directory.
        # Torch is never touched (requirements leave it unpinned); upgrade it by hand, see $TorchBackend.
        Invoke-UpdateStep 'ComfyUI (latest stable)' {
            $env:PYTHONNOUSERSITE = '1'
            $py = "$StudioRoot\ComfyUI\python_embeded\python.exe"
            Push-Location "$StudioRoot\ComfyUI\update"
            try {
                & $py -s .\update.py ..\ComfyUI\ --stable | Out-Host
                if (Test-Path .\update_new.py) {   # the updater updated itself; run the new one
                    Move-Item -Force .\update_new.py .\update.py
                    & $py -s .\update.py ..\ComfyUI\ --skip_self_update --stable | Out-Host
                }
            } finally { Pop-Location }
            if ($LASTEXITCODE) { throw "update.py exit $LASTEXITCODE" }
            Write-Ok "ComfyUI $(git -C "$StudioRoot\ComfyUI\ComfyUI" describe --tags)"
            python "$PSScriptRoot\templates\sync-comfy-desktop.py" | Out-Host   # Desktop shows the real version
        }
        # Safety net: restart our server if it still runs the old version (smoke does it when idle), re-export
        # workflows if the bundled templates changed, validate them against the new node definitions, and run
        # gen + cutout + to3d + render + the critic. A failure is reported here, not discovered mid-job.
        if (Get-Command refkit -ErrorAction SilentlyContinue) {
            Invoke-UpdateStep 'refkit smoke test (updated ComfyUI + refkit packages)' {
                refkit smoke 2>&1 | Out-Host
                if ($LASTEXITCODE) { throw "refkit smoke failed - see $AtelierRoot\scratch\smoke and the log above" }
            }
        }
    }
    # blender-mcp is pinned to a Blender Lab tag ($BlenderMcpVersion, 08): `uv tool upgrade --all` keeps it there;
    # -Check reports a newer tag.
    # Keep the repo's requirements.txt / requirements-lock.txt / REQUIREMENTS.md matching what is now installed
    # (the changes show up in `git status` in the Atelier repo for review + commit).
    Invoke-UpdateStep 'requirements manifest (repo)' {
        python "$PSScriptRoot\templates\export-requirements.py" --repo $AtelierRoot | Out-Host
    }

    if ($RepoRoot -and (Test-Path $RepoRoot)) {
        Invoke-UpdateStep "repos under $RepoRoot (fetch$($FastForwardRepos ? ' + fast-forward clean' : ' only'))" {
            # Never prompt: a repo needing interactive auth is reported, not left hanging.
            $env:GIT_TERMINAL_PROMPT = '0'
            $env:GIT_SSH_COMMAND = 'ssh -o BatchMode=yes'
            foreach ($repo in Get-ChildItem $RepoRoot -Directory | Where-Object { Test-Path "$($_.FullName)\.git" }) {
                $git = { git -C $repo.FullName @args 2>$null }
                & $git fetch --all --prune --quiet
                if ($LASTEXITCODE) { $summary.Add("      $($repo.Name): fetch failed"); continue }
                if (-not (& $git rev-parse --abbrev-ref '@{u}')) { continue }   # no upstream
                $behind = [int](& $git rev-list --count 'HEAD..@{u}')
                if (-not $behind) { continue }
                $dirty = [bool](& $git status --porcelain)
                if ($FastForwardRepos -and -not $dirty) {
                    & $git merge --ff-only --quiet '@{u}'
                    $summary.Add("      $($repo.Name): fast-forwarded $behind commit(s)" + ($LASTEXITCODE ? ' - FAILED (diverged?)' : ''))
                } else {
                    $summary.Add("      $($repo.Name): behind by $behind$($dirty ? ' (uncommitted changes)' : '')")
                }
            }
        }
    }
}

# Keep the last 12 runs of each part.
Get-ChildItem $LogDir -Filter "$run-*.log" | Sort-Object Name -Descending |
    Select-Object -Skip 12 | Remove-Item -ErrorAction Ignore

$report = @("AISetup $mode ($Part) - $(Get-Date -Format 'yyyy-MM-dd HH:mm')") + $summary
$report | Set-Content (Join-Path $LogDir "last-$run.txt") -Encoding utf8NoBOM
$report | Write-Host
Stop-Transcript | Out-Null
