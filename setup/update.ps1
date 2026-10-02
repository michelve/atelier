<#
Atelier's weekly refresh, run by the weekly task (setup\<os>\ registers it: Task Scheduler \Atelier\ on Windows) or by
hand. Unelevated; updates only what Atelier installed:
  OS tools   the vector/raster/3D CLIs (Windows: scoop - $VisualScoop + ktx-software)
  uv tool    rembg (blender-mcp stays on its pinned Blender Lab tag; -Check reports a newer one)
  npm        svgo, @gltf-transform/cli, gltfpack
  refkit venv packages (torch from the $TorchBackend index), then ComfyUI (latest stable; Windows also syncs Comfy
  Desktop's record), then `refkit smoke` over both, then the requirements manifest (requirements*.txt, REQUIREMENTS.md)
The prerequisites (Windows: winget - Blender, FFmpeg, ImageMagick, ...) are machine-wide installs: upgrading them needs
elevation, so this only reports the ones that are behind.
  -Check  dry path: list what is behind and install nothing (only package indexes and ComfyUI's git tags are
          refreshed). The report goes to logs\last-check-atelier.txt; a real run writes logs\last-update-atelier.txt.
#>
param([switch]$Check)
. "$PSScriptRoot\lib.ps1"
$ErrorActionPreference = 'Continue'   # one failing updater must not stop the rest
if (-not $Check -and (Test-Admin)) { throw 'Run this unelevated (packages and the venv must not be installed as admin).' }
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

$NpmTools = 'svgo', '@gltf-transform/cli', 'gltfpack'
$VenvPy = Get-VenvPython "$StudioRoot\venvs\refkit"
$ComfyGit = "$StudioRoot\ComfyUI\ComfyUI"

try {
    # Reported in both modes: these need elevation, which a weekly user task doesn't have.
    Invoke-UpdateStep $PrereqReportTitle {
        $behind = @(Get-PrereqUpdates)
        $behind | ForEach-Object { $summary.Add("      $_") }
        Write-Ok "$($behind.Count) behind"
    }
    if ($Check) {
        # Each step prints what is behind; "ok" means the listing ran, not that everything is current.
        Invoke-UpdateStep $OsToolsTitle { Show-OsToolUpdates }
        Invoke-UpdateStep 'uv tools (rembg, blender-mcp tag)' {
            uv tool list --outdated | Select-String -Pattern '^rembg ' | Out-Host
            # blender-mcp comes from Blender Lab's git tag ($BlenderMcpVersion); uv compares it with an unrelated
            # PyPI package of the same name, so check the official tags instead.
            $tag = git ls-remote --tags --refs https://projects.blender.org/lab/blender_mcp.git |
                ForEach-Object { ($_ -split 'refs/tags/v')[1] } | Sort-Object { [version]$_ } | Select-Object -Last 1
            if ($tag -ne $BlenderMcpVersion) { $summary.Add("      blender-mcp $BlenderMcpVersion -> $tag (bump blenderMcpVersion in atelier.jsonc, re-run setup step 4)") }
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
        if ($HpsEnabled) {
            Invoke-UpdateStep 'HPSv3++ runner (pinned commit)' {
                $head = ((git ls-remote $HpsRepo HEAD) -split '\s')[0]
                if (-not $head.StartsWith($HpsCommit)) {
                    $summary.Add("      hpsv3-4bit pinned $HpsCommit, upstream $($head.Substring(0, 7)) (review, bump hps.commit in atelier.jsonc, re-run setup step 5)")
                }
            }
        }
    } else {
        Invoke-UpdateStep $OsToolsTitle { Update-OsTools }
        Invoke-UpdateStep 'uv tool: rembg' { uv tool upgrade rembg }
        Invoke-UpdateStep 'npm: svgo + glTF tools' { npm update -g @NpmTools }
        # refkit's packages first, so the smoke test below covers them as well as the new ComfyUI.
        if (Test-Path $VenvPy) {
            Invoke-UpdateStep 'refkit venv packages' {
                # --upgrade can touch torch (spandrel depends on it): on Windows pin the CUDA backend or it may resolve
                # to CPU torch ($TorchArgs is empty where PyPI's default build is the right one).
                uv pip install --python $VenvPy @TorchArgs --upgrade torch torchvision $RefkitPackages
            }
        }
        if (Test-Path "$StudioRoot\ComfyUI\ComfyUI\main.py") {
            Invoke-UpdateStep 'ComfyUI (latest stable)' { [void](Update-Engine) }
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
            & $ExporterPython "$PyDir\export-requirements.py" --repo $AtelierRoot | Out-Host
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
