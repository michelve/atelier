# Local AI stack (no admin; the setup screen's step 5): Atelier's local GPU stack. Everything runs on this machine; no cloud nodes, no accounts.
#   Engine folder = $env:ATELIER_ENGINE, else the OS default (see lib.ps1). Needs ~150 GB free on Windows, a fast drive.
#   ComfyUI in <engine>/ComfyUI ($EngineTitle: Windows = portable NVIDIA build, torch cu130), localhost only, --disable-api-nodes
#   Shared model store <engine>/models (~130 GB on Windows): every model the templates in atelier.jsonc `comfyTemplates`
#     list (Z-Image, Qwen-Image 2.1, Krea 2, FLUX.2 klein, SeedVR2, SAM 3.1, Depth Anything 3, Pixal3D, TRELLIS.2, ...)
#   refkit venv (uv, Python 3.12, torch $TorchBackend) in <engine>/venvs/refkit; `refkit` + `comfy` shims in ~/.local/bin
#   API-format workflows exported from the core templates into <repo>/studio/workflows; skills linked into Claude Code
# Re-runnable: finished steps are skipped and model downloads resume.
#   -SkipModels  install everything except the model downloads
#   -WithEngine  macOS: also install the optional local engine (always installed on Windows)
param([switch]$SkipModels, [switch]$WithEngine)
. "$PSScriptRoot/../lib.ps1"
Start-PhaseLog 'local-ai'
Update-SessionPath

$ComfyDir = Join-Path $StudioRoot 'ComfyUI'
$Venv     = Join-Path $StudioRoot 'venvs/refkit'
$VenvPy   = Get-VenvPython $Venv
# The legacy Python 3.13 user site-packages holds a CPU torch that would shadow ComfyUI's bundled CUDA torch.
$env:PYTHONNOUSERSITE = '1'

$Engine = $EngineRequired -or $WithEngine -or (Test-Path "$ComfyDir/ComfyUI/main.py")
if ($Engine) {
    Write-Step "$EngineTitle -> $ComfyDir"
    if (Test-Path "$ComfyDir/ComfyUI/main.py") { Write-Skip 'already installed (update with update.ps1)' }
    else { Install-Engine $ComfyDir }
    $torch = & (Get-EnginePython) -s -c "import torch; print(torch.__version__, $TorchGpuProbe)"
    Write-Ok "ComfyUI torch: $torch"
} else { Write-Skip "local engine: optional on this OS, not installed (add it with -WithEngine)" }

Write-Step 'Model paths, output folder, shims, ATELIER_ENGINE'
New-Item -ItemType Directory -Force "$StudioRoot/models", "$StudioRoot/output", $ShimDir | Out-Null
Write-AtelierTemplate "$SharedDir/extra_model_paths.yaml" "$StudioRoot/extra_model_paths.yaml"
if ($Engine) { Write-Shim 'comfy' }
Write-Shim 'refkit'
Add-UserPath $ShimDir
# Scheduled updates and new terminals find the same engine folder.
Set-UserEnv 'ATELIER_ENGINE' $StudioRoot
$env:ATELIER_ENGINE = $StudioRoot
# Where this clone is, for tools outside it (e.g. a shell bootstrap's check that runs Atelier's check too).
Set-UserEnv 'ATELIER_ROOT' $AtelierRoot
Write-Ok "comfy + refkit -> $ShimDir (engine $StudioRoot, repo $AtelierRoot)"

Write-Step 'Claude Code skills -> ~\.claude\skills'
& "$PSScriptRoot/link-skills.ps1"

Write-Step "refkit venv -> $Venv"
if (-not (Test-Path $VenvPy)) { uv venv --python 3.12 $Venv }
uv pip install --python $VenvPy @TorchArgs torch torchvision
uv pip install --python $VenvPy $RefkitPackages
$vt = & $VenvPy -c "import torch; print(torch.__version__, $TorchGpuProbe)"
Write-Ok "refkit torch: $vt"

if ($SkipModels) { Write-Skip 'models (-SkipModels)' }
else {
    Write-Step 'Models (resumable)'
    # Single files from templates (comfyPick) only make sense with the engine; the extras (e.g. the upscaler) don't need it.
    $pickArgs = $Engine ? $ComfyPickArgs : @()
    & $VenvPy "$PyDir/fetch-comfy-models.py" --comfy $ComfyDir --dest "$StudioRoot/models" @ComfyTemplates @ComfyModelArgs @pickArgs
    if ($LASTEXITCODE) { Write-Warn2 'some downloads failed; re-run this script to resume' }

    Write-Step 'Critic / scorer weights (Hugging Face snapshots, resumable)'
    # Paths and names go in as argv, never into the Python source (quotes and backslashes stay intact).
    $snapshot = 'import sys; from huggingface_hub import snapshot_download as s; ' +
        's(repo_id=sys.argv[1], local_dir=sys.argv[2], max_workers=8)'
    foreach ($pair in $RefkitHfModels) {
        $dir, $repo = $pair -split '=', 2
        & $VenvPy -c $snapshot $repo (Join-Path "$StudioRoot/models" $dir)
        if ($LASTEXITCODE) { Write-Warn2 "$repo failed; re-run to resume" } else { Write-Ok "$repo -> models\$dir" }
    }
    # The rest load through from_pretrained(cache_dir=...): fetch them into that cache now, not on first use.
    $cached = 'import sys; from huggingface_hub import snapshot_download as s; ' +
        's(repo_id=sys.argv[1], cache_dir=sys.argv[2], allow_patterns=sys.argv[3].split(","), max_workers=8)'
    foreach ($pair in $RefkitHfCache) {
        $repo, $files = $pair -split '=', 2
        & $VenvPy -c $cached $repo "$StudioRoot/models/scoring" $files
        if ($LASTEXITCODE) { Write-Warn2 "$repo failed; re-run to resume" } else { Write-Ok "$repo -> models\scoring (HF cache)" }
    }
}

if ($HpsEnabled) {
    Write-Step 'HPSv3++ scorer env (own uv project, pinned commit)'
    $Hps = "$StudioRoot/tools/hpsv3-4bit"
    if (-not (Test-Path "$Hps/.git")) { git clone $HpsRepo $Hps }
    git -C $Hps fetch --quiet origin
    git -C $Hps checkout --quiet $HpsCommit
    Push-Location $Hps; uv sync; Pop-Location
    if (Test-Path (Get-VenvBin "$Hps/.venv" 'hpsv3pp-score')) { Write-Ok "hpsv3pp-score @ $HpsCommit" }
    else { Write-Warn2 'hpsv3pp-score missing; refkit falls back to PickScore' }
} else { Write-Skip 'HPSv3++ scorer: not on this OS (refkit ranks with PickScore)' }

if ($Engine -and $ComfyTemplates) {
    Write-Step 'API-format workflows (via the ComfyUI frontend)'
    $up = { try { [bool](Invoke-RestMethod http://127.0.0.1:8188/system_stats -TimeoutSec 2) } catch { $false } }
    if (-not (& $up)) {
        Start-EngineServer
        foreach ($i in 1..90) { if (& $up) { break }; Start-Sleep 2 }
    }
    if (& $up) {
        # Windows: the exporter's Playwright lives in the system Python's user site, which PYTHONNOUSERSITE hides.
        $env:PYTHONNOUSERSITE = $null
        & (Get-ExporterPython) "$PyDir/export-comfy-workflows.py" --comfy $ComfyDir --out "$StudioCode/workflows" @ComfyTemplates
        $exported = -not $LASTEXITCODE
        $env:PYTHONNOUSERSITE = '1'
        if ($exported) { Write-Ok "workflows -> $StudioCode\workflows" }
        else { Write-Warn2 "workflow export failed (exit $LASTEXITCODE); refkit smoke re-exports them too" }
    } else { Write-Warn2 "ComfyUI did not start; see $StudioRoot\comfyui.log" }
}

Write-Host "`nNext: refkit status   (then setup\check.ps1 -Deep)" -ForegroundColor Cyan
Stop-Transcript | Out-Null
