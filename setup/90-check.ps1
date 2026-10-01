# Phase 90: verify the environment. Safe to run any time (read-only apart from a temp folder).
#   -Deep  also runs end-to-end document/image/web/LLM round trips.
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
    'core'   = 'git', 'gh', 'rg', 'fd', 'fzf', 'bat', 'zoxide', 'ast-grep', 'delta', 'lazygit', 'tldr', 'glow', 'xh'
    'data'   = 'jq', 'yq', 'sd', 'duckdb', 'sqlite3'
    'docs'   = 'pandoc', 'soffice', 'pdftotext', 'pdftoppm', 'qpdf', 'gswin64c', 'tesseract', 'typst', 'markitdown', 'mmdc'
    'media'  = 'magick', 'exiftool', 'oxipng', 'ffmpeg', 'yt-dlp', 'rembg'
    'web'    = 'trafilatura', 'curl'
    'ai'     = 'claude', 'llm', 'ollama', 'gemini', 'codex'
    'shell'  = 'pwsh', 'starship', 'fnm', 'node', 'npm', 'uv', 'python'
    'web3d'  = 'gltf-transform', 'gltfpack', 'toktx', 'ktx', 'blender', 'typescript-language-server', 'pyright-langserver'
    'visual' = 'inkscape', 'potrace', 'vtracer', 'svgo', 'resvg', 'pngquant', 'cwebp', 'avifenc', 'f3d', 'blender-mcp', 'comfy', 'refkit'
}
foreach ($area in $tools.Keys) {
    foreach ($t in $tools[$area]) {
        $cmd = Get-Command $t -CommandType Application -ErrorAction Ignore | Select-Object -First 1
        Check $area $t ([bool]$cmd) ($cmd ? $cmd.Source : 'not on PATH')
    }
}

# --- Config ---
$user = Get-RawPath User; $machine = Get-RawPath Machine
$all = $machine + $user
$dead = @($all | Where-Object { -not (Test-Path ([Environment]::ExpandEnvironmentVariables($_))) })
$dupes = @($all | Group-Object { ConvertTo-PathKey $_ } | Where-Object Count -gt 1)
Check 'config' 'PATH has no dead entries' ($dead.Count -eq 0) ($dead -join '; ')
Check 'config' 'PATH has no duplicates' ($dupes.Count -eq 0) (($dupes.Name) -join '; ')
$insteadOf = git config --global --get-regexp 'url\..*\.insteadof' 2>$null
Check 'config' 'git has no insteadOf loop' (-not $insteadOf) "$insteadOf"
$helper = git config --global --get-all 'credential.https://github.com.helper' 2>$null
Check 'config' 'git uses gh for github.com' ("$helper" -match 'gh') "$helper"
$nodeVer = (node -v 2>$null)
Check 'config' 'Node is 24 LTS' ("$nodeVer" -like 'v24.*') "$nodeVer"
$prefix = npm config get prefix 2>$null
Check 'config' 'npm prefix is %APPDATA%\npm' ((ConvertTo-PathKey "$prefix") -eq (ConvertTo-PathKey "$env:APPDATA\npm")) "$prefix"
Check 'config' 'PYTHONUTF8=1' ([Environment]::GetEnvironmentVariable('PYTHONUTF8', 'User') -eq '1')
$py = python -c "import docx, pptx, openpyxl, pypdf, pdfplumber, pymupdf, reportlab; print('ok')" 2>&1
Check 'config' 'Python doc libs import' ("$py" -eq 'ok') "$py"
Check 'config' 'CLAUDE.md installed' (Test-Path "$ClaudeDir\CLAUDE.md") 'manual step - see README'
# Same token source as the `claude` wrapper in $PROFILE, so this tests the real launch path.
if (-not $env:GITHUB_PERSONAL_ACCESS_TOKEN) { $env:GITHUB_PERSONAL_ACCESS_TOKEN = gh auth token 2>$null }
$mcp = claude.exe mcp list 2>&1 | Out-String
Check 'config' 'Playwright MCP connected' ($mcp -match 'playwright.*Connected') 'manual step - see README'
Check 'config' 'GitHub MCP connected' ($mcp -match 'github.*Connected') 'launch claude from pwsh so the token is set'

$tsVer = (tsc -v 2>$null)
Check 'config' 'global TypeScript is 6.x (tsserver for the LSP)' ("$tsVer" -match 'Version 6\.') "$tsVer"
Check 'config' 'OLLAMA_CONTEXT_LENGTH=32768' ([Environment]::GetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH', 'User') -eq '32768')
Check 'config' 'OLLAMA_KV_CACHE_TYPE=q8_0' ([Environment]::GetEnvironmentVariable('OLLAMA_KV_CACHE_TYPE', 'User') -eq 'q8_0')
$vsExt = @(code --list-extensions 2>$null)
foreach ($ext in 'cesium.gltf-vscode', 'raczzalan.webgl-glsl-editor', 'polymeilex.wgsl') {
    Check 'vscode' $ext ($vsExt -contains $ext)
}
Check 'vscode' 'PHP extensions only in PHP-Legacy profile' (-not ($vsExt -contains 'bmewburn.vscode-intelephense-client')) 'run 07-web3d.ps1'
$plugins = (Read-JsonFile "$ClaudeDir\settings.json").enabledPlugins
foreach ($p in 'core-3d-animation@claude-design-skillstack', 'meta-skills@claude-design-skillstack',
               'typescript-lsp@claude-plugins-official', 'chrome-devtools-mcp@claude-plugins-official',
               'frontend-design@claude-plugins-official', 'modern-web-guidance@claude-plugins-official', 'pyright-lsp@claude-plugins-official') {
    Check 'claude' "plugin $p" ($plugins.$p -eq $true)
}

# --- Visual studio (08/09) ---
$env:PYTHONNOUSERSITE = '1'
$comfyPy = "$StudioRoot\ComfyUI\python_embeded\python.exe"
$ct = (Test-Path $comfyPy) ? (& $comfyPy -s -c "import torch; print(torch.__version__, torch.cuda.is_available())" 2>&1 | Out-String).Trim() : 'not installed'
Check 'visual' 'ComfyUI torch sees the GPU' ($ct -match 'True$') $ct
$rkPy = "$StudioRoot\venvs\refkit\Scripts\python.exe"
$rt = (Test-Path $rkPy) ? (& $rkPy -c "import torch, cv2, vtracer, trimesh, spandrel; print(torch.__version__, torch.cuda.is_available())" 2>&1 | Out-String).Trim() : 'not installed'
Check 'visual' 'refkit venv imports + GPU' ($rt -match 'True$') $rt
Remove-Item Env:PYTHONNOUSERSITE
foreach ($t in $ComfyTemplates) {
    Check 'visual' "workflow $t" (Test-Path "$StudioCode\workflows\$t.api.json") 'run 09-local-ai.ps1'
}
if (Test-Path $rkPy) {
    # Same model list the installer downloads (read from the templates), so the check can't drift from it.
    $env:PYTHONNOUSERSITE = '1'
    $extra = $ComfyExtraModels | ForEach-Object { '--extra'; $_ }
    $want = & $rkPy "$Templates\fetch-comfy-models.py" --comfy "$StudioRoot\ComfyUI" --dest "$StudioRoot\models" --dry-run @ComfyTemplates @extra |
        Select-String '^\s+(\S+)\s+<-' | ForEach-Object { $_.Matches[0].Groups[1].Value }
    Remove-Item Env:PYTHONNOUSERSITE
    $missing = @($want | Where-Object { -not (Test-Path "$StudioRoot\models\$_") })
    Check 'visual' "models present ($($want.Count))" ($want.Count -gt 0 -and $missing.Count -eq 0) ($missing -join ', ')
}
$bl = blender -b --python-expr "import bpy; p=bpy.context.preferences; print('MCPCHECK', any(a.module.endswith('.mcp') for a in p.addons), p.system.use_online_access)" 2>&1 | Select-String 'MCPCHECK'
Check 'visual' 'Blender MCP add-on enabled + online access' ("$bl" -match 'MCPCHECK True True') "$bl"
Check 'visual' 'refkit skill installed' (Test-Path "$ClaudeDir\skills\refkit\SKILL.md")
Check 'visual' 'Blender MCP connected to Claude' ($mcp -match 'blender.*Connected') 'manual: claude mcp add --scope user blender -- blender-mcp'

# --- Weekly updates ---
foreach ($part in 'admin', 'user') {
    $task = Get-ScheduledTask -TaskPath '\AISetup\' -TaskName "Weekly update ($part)" -ErrorAction Ignore
    Check 'updates' "task: weekly update ($part)" ([bool]$task) ($task ? "next: $(($task | Get-ScheduledTaskInfo).NextRunTime)" : 'run 06-schedule.ps1 elevated')
    $last = Join-Path $LogDir "last-update-$part.txt"
    if (Test-Path $last) {
        $fails = @(Get-Content $last | Where-Object { $_ -like 'FAIL*' })
        Check 'updates' "last $part run clean" ($fails.Count -eq 0) "$((Get-Content $last -First 1)) $($fails -join '; ')"
    }
}

# --- Profile load time (both modes, fresh process each) ---
foreach ($mode in 'agent', 'interactive') {
    $ms = pwsh -NoLogo -NoProfile -Command "`$env:AISETUP_MODE='$mode'; `$sw=[Diagnostics.Stopwatch]::StartNew(); . `$PROFILE *>`$null; `$sw.ElapsedMilliseconds"
    $limit = $mode -eq 'agent' ? 50 : 400
    Check 'profile' "$mode load < ${limit}ms" ([int]"$ms" -lt $limit) "${ms}ms"
}

# --- Round trips ---
if ($Deep) {
    $tmp = Join-Path $env:TEMP 'aisetup-check'
    Remove-Item $tmp -Recurse -Force -ErrorAction Ignore
    New-Item -ItemType Directory $tmp | Out-Null
    Push-Location $tmp
    try {
        python -c "import docx; d=docx.Document(); d.add_paragraph('AISetup round trip ok'); d.save('t.docx')"
        soffice --headless --convert-to pdf t.docx *> $null
        Check 'deep' 'docx -> pdf (LibreOffice)' (Test-Path 't.pdf')
        Check 'deep' 'pdf -> text (Poppler)' ((pdftotext t.pdf - 2>$null | Out-String) -match 'round trip ok')
        pdftoppm -r 200 -png -singlefile t.pdf page 2>$null
        Check 'deep' 'pdf -> png -> OCR (tesseract)' ((tesseract page.png - 2>$null | Out-String) -match 'round trip')
        Check 'deep' 'docx -> markdown (markitdown)' ((markitdown t.docx 2>$null | Out-String) -match 'round trip ok')
        magick -size 64x64 xc:red red.png 2>$null
        Check 'deep' 'image create/identify (ImageMagick)' ((magick identify red.png 2>$null | Out-String) -match '64x64')
        '<h1>playwright ok</h1>' | Set-Content page.html
        python -m playwright screenshot --browser chromium "file:///$($tmp -replace '\\','/')/page.html" shot.png *> $null
        Check 'deep' 'Playwright screenshot' (Test-Path 'shot.png')
        # WebGL must hit the RTX via ANGLE, not the SwiftShader software fallback.
        $gl = (python "$PSScriptRoot\templates\webgl-renderer.py" 2>&1 | Out-String).Trim()
        Check 'deep' 'Chromium WebGL uses the GPU' ($gl -match 'NVIDIA' -and $gl -notmatch 'SwiftShader') $gl
        '{"asset":{"version":"2.0"},"scenes":[{"nodes":[]}],"scene":0}' | Set-Content empty.gltf
        gltf-transform copy empty.gltf empty.glb *> $null
        Check 'deep' 'gltf -> glb (gltf-transform)' (Test-Path 'empty.glb')
        $bl = blender -b --factory-startup --python-expr "import bpy; bpy.ops.export_scene.gltf(filepath=r'$tmp\cube.glb')" 2>&1 | Out-String
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
        $ollamaUp = try { [bool](Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2) } catch { $false }
        if ($ollamaUp) {
            $answer = (llm -m qwen3:14b 'Reply with exactly: OK /no_think' 2>&1 | Out-String).Trim() -replace '\s+', ' '
            Check 'deep' 'llm -> Ollama' ($answer -match 'OK') $answer.Substring([Math]::Max(0, $answer.Length - 60))
        } else {
            Check 'deep' 'llm -> Ollama' $false 'Ollama not running - start the app or `ollama serve`, then re-check'
        }
    } finally { Pop-Location }
}

$results | Format-Table -AutoSize -Wrap
$failed = @($results | Where-Object Result -eq 'FAIL').Count
Write-Host ("{0} checks, {1} failed" -f $results.Count, $failed) -ForegroundColor ($failed ? 'Yellow' : 'Green')
