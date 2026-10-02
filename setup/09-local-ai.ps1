# Phase 09 (no admin): Atelier's local GPU stack. Everything runs on this PC; no cloud nodes, no accounts.
#   Engine folder = $env:ATELIER_ENGINE, else <repo>\engine (see lib.ps1). Needs ~150 GB free, a fast drive.
#   ComfyUI portable (NVIDIA, torch cu130) in <engine>\ComfyUI, localhost only, --disable-api-nodes
#   Shared model store <engine>\models (~130 GB): every model the templates in lib.ps1 `$ComfyTemplates` list
#     (Z-Image, Qwen-Image 2.1, Krea 2, FLUX.2 klein, SeedVR2, SAM 3.1, Depth Anything 3, Pixal3D, TRELLIS.2, ...)
#   refkit venv (uv, Python 3.12, torch $TorchBackend) in <engine>\venvs\refkit; `refkit` + `comfy` shims in ~\.local\bin
#   API-format workflows exported from the core templates into <repo>\studio\workflows; skills linked into Claude Code
# Re-runnable: finished steps are skipped and model downloads resume.
param([switch]$SkipModels)
. "$PSScriptRoot\lib.ps1"
Start-PhaseLog '09-local-ai'
Update-SessionPath

$ComfyDir = Join-Path $StudioRoot 'ComfyUI'
$Venv     = Join-Path $StudioRoot 'venvs\refkit'
$VenvPy   = Join-Path $Venv 'Scripts\python.exe'
$shimDir  = "$HOME\.local\bin"
# The legacy Python 3.13 user site-packages holds a CPU torch that would shadow ComfyUI's bundled CUDA torch.
$env:PYTHONNOUSERSITE = '1'

Write-Step "ComfyUI portable -> $ComfyDir"
if (Test-Path "$ComfyDir\ComfyUI\main.py") { Write-Skip 'already installed (update with update.ps1)' }
else {
    $dl = Join-Path $StudioRoot '_downloads'
    New-Item -ItemType Directory -Force $dl | Out-Null
    # Plain release URL (no `gh auth login` needed); curl resumes an interrupted 2 GB download with -C -.
    $archive = "$dl\ComfyUI_windows_portable_nvidia.7z"
    curl.exe -fL -C - -o $archive 'https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z'
    if ($LASTEXITCODE) { throw "ComfyUI download failed (curl exit $LASTEXITCODE); re-run to resume" }
    # winget's 7-Zip doesn't put 7z.exe on PATH.
    $sevenZip = (Get-Command 7z -ErrorAction Ignore).Source
    if (-not $sevenZip) { $sevenZip = @("$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1 }
    if (-not $sevenZip) { throw '7-Zip not found: winget install 7zip.7zip (or run setup\install.ps1)' }
    & $sevenZip x -y $archive "-o$StudioRoot\_extract" | Out-Null
    Move-Item "$StudioRoot\_extract\ComfyUI_windows_portable" $ComfyDir
    Remove-Item "$StudioRoot\_extract" -Recurse -Force
    Write-Ok 'extracted'
}
$torch = & "$ComfyDir\python_embeded\python.exe" -s -c "import torch; print(torch.__version__, torch.cuda.is_available())"
Write-Ok "ComfyUI torch: $torch"

Write-Step 'Model paths, output folder, shims, ATELIER_ENGINE'
New-Item -ItemType Directory -Force "$StudioRoot\models", "$StudioRoot\output", $shimDir | Out-Null
Write-AtelierTemplate "$Templates\extra_model_paths.yaml" "$StudioRoot\extra_model_paths.yaml"
Write-AtelierTemplate "$Templates\comfy.cmd" "$shimDir\comfy.cmd"
Write-AtelierTemplate "$Templates\refkit.cmd" "$shimDir\refkit.cmd"
Add-UserPath $shimDir
# Scheduled updates and new terminals find the same engine folder.
[Environment]::SetEnvironmentVariable('ATELIER_ENGINE', $StudioRoot, 'User')
$env:ATELIER_ENGINE = $StudioRoot
# Where this clone is, for tools outside it (e.g. a shell bootstrap's check that runs Atelier's check too).
[Environment]::SetEnvironmentVariable('ATELIER_ROOT', $AtelierRoot, 'User')
Write-Ok "comfy + refkit -> $shimDir (engine $StudioRoot, repo $AtelierRoot)"

Write-Step 'Claude Code skills -> ~\.claude\skills'
& "$PSScriptRoot\link-skills.ps1"

Write-Step "refkit venv -> $Venv"
if (-not (Test-Path $VenvPy)) { uv venv --python 3.12 $Venv }
uv pip install --python $VenvPy --torch-backend $TorchBackend torch torchvision
uv pip install --python $VenvPy $RefkitPackages
$vt = & $VenvPy -c "import torch; print(torch.__version__, torch.cuda.is_available())"
Write-Ok "refkit torch: $vt"

if ($SkipModels) { Write-Skip 'models (-SkipModels)' }
else {
    Write-Step 'Models (resumable)'
    & $VenvPy "$Templates\fetch-comfy-models.py" --comfy $ComfyDir --dest "$StudioRoot\models" @ComfyTemplates @ComfyModelArgs
    if ($LASTEXITCODE) { Write-Warn2 'some downloads failed; re-run this script to resume' }

    Write-Step 'Critic / scorer weights (Hugging Face snapshots, resumable)'
    foreach ($pair in $RefkitHfModels) {
        $dir, $repo = $pair -split '=', 2
        & $VenvPy -c "from huggingface_hub import snapshot_download as s; s(repo_id='$repo', local_dir=r'$StudioRoot\models\$dir', max_workers=8)"
        if ($LASTEXITCODE) { Write-Warn2 "$repo failed; re-run to resume" } else { Write-Ok "$repo -> models\$dir" }
    }
    # The rest load through from_pretrained(cache_dir=...): fetch them into that cache now, not on first use.
    foreach ($pair in $RefkitHfCache) {
        $repo, $files = $pair -split '=', 2
        $patterns = ($files -split ',' | ForEach-Object { "'$_'" }) -join ','
        & $VenvPy -c "from huggingface_hub import snapshot_download as s; s(repo_id='$repo', cache_dir=r'$StudioRoot\models\scoring', allow_patterns=[$patterns], max_workers=8)"
        if ($LASTEXITCODE) { Write-Warn2 "$repo failed; re-run to resume" } else { Write-Ok "$repo -> models\scoring (HF cache)" }
    }
}

Write-Step 'HPSv3++ scorer env (own uv project, pinned commit)'
$Hps = "$StudioRoot\tools\hpsv3-4bit"
if (-not (Test-Path "$Hps\.git")) { git clone $HpsRepo $Hps }
git -C $Hps fetch --quiet origin
git -C $Hps checkout --quiet $HpsCommit
Push-Location $Hps; uv sync; Pop-Location
if (Test-Path "$Hps\.venv\Scripts\hpsv3pp-score.exe") { Write-Ok "hpsv3pp-score @ $HpsCommit" }
else { Write-Warn2 'hpsv3pp-score missing; refkit falls back to PickScore' }

Write-Step 'API-format workflows (via the ComfyUI frontend)'
$up = { try { [bool](Invoke-RestMethod http://127.0.0.1:8188/system_stats -TimeoutSec 2) } catch { $false } }
if (-not (& $up)) {
    # Start-Process straight on the shim: wrapping it in `cmd /c "... >> log"` breaks on quoting (and clink AutoRun).
    Start-Process -FilePath "$shimDir\comfy.cmd" -WindowStyle Hidden `
        -RedirectStandardOutput "$StudioRoot\comfyui.log" -RedirectStandardError "$StudioRoot\comfyui.err.log"
    foreach ($i in 1..90) { if (& $up) { break }; Start-Sleep 2 }
}
if (& $up) {
    python "$Templates\export-comfy-workflows.py" --comfy $ComfyDir --out "$StudioCode\workflows" @ComfyTemplates
    Write-Ok "workflows -> $StudioCode\workflows"
} else { Write-Warn2 "ComfyUI did not start; see $StudioRoot\comfyui.log" }

Write-Host "`nNext: refkit status   (then setup\check.ps1 -Deep)" -ForegroundColor Cyan
Stop-Transcript | Out-Null
