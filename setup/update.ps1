<#
Atelier's weekly refresh, run by the \Atelier\ scheduled task (setup\windows\schedule.ps1 registers it) or by hand.
Unelevated; updates only what Atelier installed:
  scoop      the vector/raster/3D CLIs ($VisualScoop, ktx-software)
  uv tool    rembg (blender-mcp stays on its pinned Blender Lab tag; -Check reports a newer one)
  npm        svgo, @gltf-transform/cli, gltfpack
  refkit venv packages (torch from the $TorchBackend index), then ComfyUI (latest stable) + Comfy Desktop's record,
  then `refkit smoke` over both, then the requirements manifest (requirements*.txt, REQUIREMENTS.md)
The winget prerequisites (Blender, FFmpeg, ImageMagick, ...) are machine-wide installs: upgrading them needs
elevation, so this only reports the ones that are behind (winget upgrade --id <Id>, or a winget auto-updater).
  -Check  dry path: list what is behind and install nothing (only scoop's bucket index and ComfyUI's git tags are
          refreshed). The report goes to logs\last-check-atelier.txt; a real run writes logs\last-update-atelier.txt.
#>
param([switch]$Check)
. "$PSScriptRoot\lib.ps1"
$ErrorActionPreference = 'Continue'   # one failing updater must not stop the rest
if (-not $Check -and (Test-Admin)) { throw 'Run this unelevated (scoop and the venv must not be installed as admin).' }
# One run at a time: a hand run must not overlap the scheduled one (both would update the same venv and ComfyUI).
$lock = [Threading.Mutex]::new($false, 'AtelierUpdate')
if (-not $lock.WaitOne(0)) { throw 'Another Atelier update is running.' }
$mode = $Check ? 'check' : 'update'
$run = "$mode-atelier"
Start-PhaseLog $run
Update-SessionPath

$summary = [Collections.Generic.List[string]]::new()
function Invoke-UpdateStep([string]$Name, [scriptblock]$Action) {
    Write-Step $Name
    try { & $Action; $summary.Add("ok    $Name") }
    catch { Write-Warn2 $_; $summary.Add("FAIL  $Name - $_") }
}

$ScoopApps = $VisualScoop + 'ktx-software'
$NpmTools = 'svgo', '@gltf-transform/cli', 'gltfpack'
$VenvPy = "$StudioRoot\venvs\refkit\Scripts\python.exe"
$ComfyGit = "$StudioRoot\ComfyUI\ComfyUI"

try {
    # Reported in both modes: these need an elevated winget, which a weekly user task can't do.
    Invoke-UpdateStep 'winget prerequisites (report only)' {
        if (-not (Get-Command Get-WinGetPackage -ErrorAction Ignore)) { Write-Skip 'Microsoft.WinGet.Client not installed'; return }
        $behind = Get-WinGetPackage | Where-Object { $_.IsUpdateAvailable -and $AtelierWinget -contains $_.Id }
        $behind | ForEach-Object { $summary.Add("      $($_.Id) $($_.InstalledVersion) -> $($_.AvailableVersions[0]) (winget upgrade --id $($_.Id))") }
        Write-Ok "$(@($behind).Count) behind"
    }
    if ($Check) {
        # Each step prints what is behind; "ok" means the listing ran, not that everything is current.
        Invoke-UpdateStep 'scoop (Atelier tools)' {
            scoop update | Out-Null
            scoop status | Where-Object { $ScoopApps -contains $_.Name } | Out-Host
        }
        Invoke-UpdateStep 'uv tools (rembg, blender-mcp tag)' {
            uv tool list --outdated | Select-String -Pattern '^rembg ' | Out-Host
            # blender-mcp comes from Blender Lab's git tag ($BlenderMcpVersion); uv compares it with an unrelated
            # PyPI package of the same name, so check the official tags instead.
            $tag = git ls-remote --tags --refs https://projects.blender.org/lab/blender_mcp.git |
                ForEach-Object { ($_ -split 'refs/tags/v')[1] } | Sort-Object { [version]$_ } | Select-Object -Last 1
            if ($tag -ne $BlenderMcpVersion) { $summary.Add("      blender-mcp $BlenderMcpVersion -> $tag (bump `$BlenderMcpVersion in lib.ps1, re-run 08)") }
        }
        Invoke-UpdateStep 'npm (svgo, glTF tools)' {
            npm outdated -g --depth=0 | Select-String -Pattern ('^(' + (($NpmTools | ForEach-Object { [regex]::Escape($_) }) -join '|') + ') ') | Out-Host
        }
        if (Test-Path "$ComfyGit\.git") {
            Invoke-UpdateStep 'ComfyUI (latest stable tag)' {
                git -C $ComfyGit fetch --tags --quiet   # refs only; the working tree is not touched
                $tag = git -C $ComfyGit tag --list 'v*' --sort=-v:refname | Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } | Select-Object -First 1
                $summary.Add("      ComfyUI $(git -C $ComfyGit describe --tags) installed, latest stable $tag")
            }
        }
        if (Test-Path $VenvPy) {
            Invoke-UpdateStep 'refkit venv packages' { uv pip list --python $VenvPy --outdated | Out-Host }
        }
        Invoke-UpdateStep 'HPSv3++ runner (pinned commit)' {
            $head = ((git ls-remote $HpsRepo HEAD) -split '\s')[0]
            if (-not $head.StartsWith($HpsCommit)) {
                $summary.Add("      hpsv3-4bit pinned $HpsCommit, upstream $($head.Substring(0, 7)) (review, bump `$HpsCommit, re-run 09)")
            }
        }
    } else {
        Invoke-UpdateStep 'scoop (Atelier tools)' {
            scoop update
            $installed = @((scoop list 6>$null).Name)
            $apps = @($ScoopApps | Where-Object { $installed -contains $_ })
            if ($apps) { scoop update @apps }
            # One failing app aborts the rest of `scoop update` without an error here (2026-09-27: 7zip's MSI hit
            # 1618 "another install in progress"). Retry once, then report.
            $behind = { @(scoop status | Where-Object { $apps -contains $_.Name -and $_.'Latest Version' -and $_.Info -notmatch 'Held' }) }
            $left = & $behind
            if ($left) { scoop update $left.Name; $left = & $behind }
            if ($left) { throw "still behind: $($left.Name -join ', ')" }
        }
        Invoke-UpdateStep 'uv tool: rembg' { uv tool upgrade rembg }
        Invoke-UpdateStep 'npm: svgo + glTF tools' { npm update -g @NpmTools }
        # refkit's packages first, so the smoke test below covers them as well as the new ComfyUI.
        if (Test-Path $VenvPy) {
            Invoke-UpdateStep 'refkit venv packages' {
                # --upgrade can touch torch (spandrel depends on it): pin the CUDA backend or it may resolve to CPU torch.
                uv pip install --python $VenvPy --torch-backend $TorchBackend --upgrade torch torchvision $RefkitPackages
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
                Write-Ok "ComfyUI $(git -C $ComfyGit describe --tags)"
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
        # Keep the repo's requirements.txt / requirements-lock.txt / REQUIREMENTS.md matching what is now installed
        # (the changes show up in `git status` for review + commit).
        Invoke-UpdateStep 'requirements manifest (repo)' {
            python "$PSScriptRoot\templates\export-requirements.py" --repo $AtelierRoot | Out-Host
        }
    }
} finally { $lock.ReleaseMutex() }

# Keep the last 12 runs.
Get-ChildItem $LogDir -Filter "$run-*.log" | Sort-Object Name -Descending |
    Select-Object -Skip 12 | Remove-Item -ErrorAction Ignore

$report = @("Atelier $mode - $(Get-Date -Format 'yyyy-MM-dd HH:mm')") + $summary
$report | Set-Content (Join-Path $LogDir "last-$run.txt") -Encoding utf8NoBOM
$report | Write-Host
Stop-Transcript | Out-Null
