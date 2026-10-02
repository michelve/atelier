# Atelier's check: tools, engine, models, workflows, Blender MCP, the weekly task. Read-only apart from a temp folder.
#   -Deep  also runs refkit round trips (analyze, vectorize, render, qa) and `refkit smoke` (~4 min).
param([switch]$Deep)
. "$PSScriptRoot\lib.ps1"
$ErrorActionPreference = 'Continue'
Update-SessionPath
$results = [Collections.Generic.List[object]]::new()
function Check([string]$Area, [string]$Name, [bool]$Pass, [string]$Detail = '') {
    $results.Add([pscustomobject]@{ Area = $Area; Check = $Name; Result = ($Pass ? 'PASS' : 'FAIL'); Detail = $Detail })
}

# --- Tools on PATH ---
$tools = [ordered]@{
    'tools'  = 'git', 'uv', 'python', 'node', 'npm', 'blender', 'ffmpeg', 'ffprobe', 'magick', 'exiftool', 'oxipng',
               'tesseract', 'rembg', 'gltf-transform', 'gltfpack', 'toktx', 'ktx'
    'visual' = 'inkscape', 'potrace', 'vtracer', 'svgo', 'resvg', 'pngquant', 'cwebp', 'avifenc', 'f3d', 'blender-mcp', 'comfy', 'refkit'
}
foreach ($area in $tools.Keys) {
    foreach ($t in $tools[$area]) {
        $cmd = Get-Command $t -CommandType Application -ErrorAction Ignore | Select-Object -First 1
        if (-not $cmd -and $OptionalTools -contains $t) { continue }   # not used on this OS / optional engine
        Check $area $t ([bool]$cmd) ($cmd ? $cmd.Source : 'not on PATH')
    }
}

# --- Engine, venv, weights, workflows (setup steps 4-5) ---
$env:PYTHONNOUSERSITE = '1'
$comfyPy = Get-EnginePython
if ((Test-Path $comfyPy) -or $EngineRequired) {
    $ct = (Test-Path $comfyPy) ? (& $comfyPy -s -c "import torch; print(torch.__version__, $TorchGpuProbe)" 2>&1 | Out-String).Trim() : 'not installed'
    Check 'visual' 'ComfyUI torch sees the GPU' ($ct -match 'True$') $ct
}
$rkPy = Get-VenvPython "$StudioRoot\venvs\refkit"
$rt = (Test-Path $rkPy) ? (& $rkPy -c "import $VenvImports; print(torch.__version__, $TorchGpuProbe)" 2>&1 | Out-String).Trim() : 'not installed'
Check 'visual' 'refkit venv imports + GPU' ($rt -match 'True$') $rt
# Local critic / scorers (vlm.py, score.py): Hugging Face snapshots + the HPSv3++ runner's own env.
foreach ($pair in $RefkitHfModels) {
    $dir = ($pair -split '=', 2)[0]
    $ok = (Test-Path "$StudioRoot\models\$dir\config.json") -or (Test-Path "$StudioRoot\models\$dir\adapter_config.json")
    Check 'visual' "weights models\$dir" $ok 'run setup step 5 (shared\local-ai.ps1)'
}
foreach ($pair in $RefkitHfCache) {
    $repo = ($pair -split '=', 2)[0]
    $ok = Test-Path "$StudioRoot\models\scoring\models--$($repo -replace '/', '--')\snapshots\*\config.json"
    Check 'visual' "weights $repo (HF cache)" $ok 'run setup step 5 (else downloaded on first use)'
}
if ($HpsEnabled) {
    Check 'visual' "HPSv3++ scorer env ($HpsCommit)" (Test-Path (Get-VenvBin "$StudioRoot\tools\hpsv3-4bit\.venv" 'hpsv3pp-score')) 'run setup step 5 (refkit falls back to PickScore)'
}
Remove-Item Env:PYTHONNOUSERSITE
foreach ($t in $ComfyTemplates) {
    Check 'visual' "workflow $t" (Test-Path "$StudioCode\workflows\$t.api.json") 'run setup step 5'
}
if ((Test-Path $rkPy) -and $ComfyTemplates) {
    # Same model list the installer downloads (read from the templates), so the check can't drift from it.
    $env:PYTHONNOUSERSITE = '1'
    $want = & $rkPy "$PyDir\fetch-comfy-models.py" --comfy "$StudioRoot\ComfyUI" --dest "$StudioRoot\models" --dry-run @ComfyTemplates @ComfyModelArgs |
        Select-String '^\s+(\S+)\s+<-' | ForEach-Object { $_.Matches[0].Groups[1].Value }
    Remove-Item Env:PYTHONNOUSERSITE
    $missing = @($want | Where-Object { -not (Test-Path "$StudioRoot\models\$_") })
    Check 'visual' "models present ($($want.Count))" ($want.Count -gt 0 -and $missing.Count -eq 0) ($missing -join ', ')
}

# --- Blender MCP + Claude Code ---
$bl = blender -b --python-expr "import bpy; p=bpy.context.preferences; print('MCPCHECK', any(a.module.endswith('.mcp') for a in p.addons), p.system.use_online_access)" 2>&1 | Select-String 'MCPCHECK'
Check 'visual' 'Blender MCP add-on enabled + online access' ("$bl" -match 'MCPCHECK True True') "$bl"
Check 'visual' 'refkit skill installed' (Test-Path "$ClaudeDir\skills\refkit\SKILL.md")
$mcp = (Get-Command claude -ErrorAction Ignore) ? (claude mcp list 2>&1 | Out-String) : ''
Check 'visual' 'Blender MCP connected to Claude' ($mcp -match 'blender.*Connected') 'manual: claude mcp add --scope user blender -- blender-mcp'

# --- Weekly update ---
$task = Get-ScheduledUpdate
Check 'updates' 'task: Atelier weekly update' $task.Registered ($task.Registered ? "next: $($task.Next)" : 'optional: setup screen step 9')
$last = Join-Path $LogDir 'last-update-atelier.txt'
if (Test-Path $last) {
    $fails = @(Get-Content $last | Where-Object { $_ -like 'FAIL*' })
    Check 'updates' 'last Atelier update clean' ($fails.Count -eq 0) "$((Get-Content $last -First 1)) $($fails -join '; ')"
}

# --- Round trips ---
if ($Deep) {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) 'atelier-check'
    Remove-Item $tmp -Recurse -Force -ErrorAction Ignore
    New-Item -ItemType Directory $tmp | Out-Null
    Push-Location $tmp
    try {
        $bl = blender -b --factory-startup --python-expr "import bpy; bpy.ops.export_scene.gltf(filepath=r'$(Join-Path $tmp 'cube.glb')')" 2>&1 | Out-String
        Check 'deep' 'Blender headless glTF export' (Test-Path 'cube.glb') "$($bl -split "`n" | Select-String '^Blender \d' | Select-Object -First 1)"
        # refkit round trip: flat test graphic -> analyze -> vectorize -> qa; GLB -> 1-frame Cycles render.
        magick -size 512x512 xc:'#0d0d12' -fill '#8f6bff' -draw 'roundrectangle 96,96 416,416 48,48' -fill '#ece8ff' -draw 'circle 256,256 256,176' flat.png 2>$null
        refkit analyze flat.png --fast *> $null
        Check 'deep' 'refkit analyze' (Test-Path 'flat.refkit\analysis.json')
        refkit vectorize flat.png --preset clean *> $null
        $vr = (Test-Path 'flat.refkit\vector-report.json') ? (Get-Content 'flat.refkit\vector-report.json' -Raw | ConvertFrom-Json).best : $null
        Check 'deep' 'refkit vectorize (SSIM >= 0.9)' ($vr -and $vr.ssim -ge 0.9) ($vr ? "ssim $($vr.ssim), $($vr.paths) paths" : '')
        refkit render cube.glb --frames 1 --res 256x256 --samples 8 *> $null
        Check 'deep' 'refkit render (Cycles GPU still)' (Test-Path 'cube.refkit\poster.webp')
        refkit qa flat.refkit\vector.svg --ref flat.png *> $null
        Check 'deep' 'refkit qa' ($LASTEXITCODE -eq 0)
        # Whole pipeline: workflows vs this ComfyUI, gen + cutout, to3d + inspect, render, local critic (~4 min).
        refkit smoke --no-export *> $null
        Check 'deep' 'refkit smoke (gen, cutout, to3d, render, critic)' ($LASTEXITCODE -eq 0) 'see scratch\smoke'
    } finally { Pop-Location }
}

$results | Format-Table -AutoSize -Wrap
$failed = @($results | Where-Object Result -eq 'FAIL').Count
Write-Host ("{0} checks, {1} failed" -f $results.Count, $failed) -ForegroundColor ($failed ? 'Yellow' : 'Green')
