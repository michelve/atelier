# Shared helpers for the setup phase scripts. Dot-source from each phase: . "$PSScriptRoot\lib.ps1"
$ErrorActionPreference = 'Stop'

$Root       = $PSScriptRoot
$LogDir     = Join-Path $Root 'logs'
$BackupRoot = Join-Path $Root 'backup'
$Templates  = Join-Path $Root 'templates'
New-Item -ItemType Directory -Force $LogDir, $BackupRoot | Out-Null

# Atelier paths - nothing machine-specific is hard-coded:
#   $AtelierRoot  the repo clone (this folder's parent; resolved through a junction such as ~\AISetup)
#   $StudioRoot   the engine folder: ComfyUI portable, models (~130 GB), venvs, outputs. $env:ATELIER_ENGINE, else
#                 <repo>\engine (git-ignored). Put it on a big, fast drive: setx ATELIER_ENGINE D:\AtelierEngine
$setupItem   = Get-Item $PSScriptRoot
$setupReal   = if ($setupItem.LinkType) { @($setupItem.Target)[0] } else { $setupItem.FullName }
$AtelierRoot = Split-Path $setupReal
# A terminal opened before ATELIER_ENGINE was set won't have it: fall back to the saved user value.
$engineVar   = if ($env:ATELIER_ENGINE) { $env:ATELIER_ENGINE } else { [Environment]::GetEnvironmentVariable('ATELIER_ENGINE', 'User') }
$StudioRoot  = if ($engineVar) { $engineVar } else { Join-Path $AtelierRoot 'engine' }
$env:ATELIER_ENGINE = $StudioRoot   # child processes (export-requirements, sync-comfy-desktop, refkit) agree
$StudioCode  = Join-Path $AtelierRoot 'studio'   # refkit source + workflows

$UserEnvKey    = 'HKCU:\Environment'
$MachineEnvKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
$WtSettings    = "$env:LOCALAPPDATA\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json"
$ClaudeDir     = Join-Path $HOME '.claude'

# winget packages AISetup installs (02-admin) and keeps current (update-tools -Part Admin).
$WingetPackages = @(
    # search, navigation, data
    'sharkdp.fd', 'junegunn.fzf', 'sharkdp.bat', 'ajeetdsouza.zoxide', 'ast-grep.ast-grep', 'dandavison.delta',
    'jqlang.jq', 'MikeFarah.yq', 'chmln.sd', 'DuckDB.cli', 'charmbracelet.glow', 'dbrgn.tealdeer',
    'ducaale.xh', 'JesseDuffield.lazygit',
    # documents
    'TheDocumentFoundation.LibreOffice', 'oschwartz10612.Poppler', 'QPDF.QPDF', 'UB-Mannheim.TesseractOCR', 'Typst.Typst',
    # images and media
    'ImageMagick.ImageMagick', 'OliverBetz.ExifTool', 'Shssoichiro.Oxipng', 'yt-dlp.yt-dlp',
    # shell
    'Starship.Starship', 'chrisant996.Clink', 'Schniz.fnm', 'DEVCOM.JetBrainsMonoNerdFont'
)
# Installed before AISetup via winget; updated alongside, never installed by it.
$WingetPreexisting = @('BurntSushi.ripgrep.MSVC', 'Gyan.FFmpeg', 'BlenderFoundation.Blender')

# Python 3.14 libraries the docx/pptx/xlsx/pdf skills rely on, and the PowerShell modules the profile loads.
$PythonDocLibs = @('python-docx', 'python-pptx', 'openpyxl', 'pypdf', 'pdfplumber', 'pymupdf', 'reportlab', 'playwright')
# Visual studio (08/09): portable CLIs from scoop (extras holds inkscape + f3d), the local AI root on E:.
$VisualScoop = @('potrace', 'resvg', 'pngquant', 'libwebp', 'libavif', 'inkscape', 'f3d')
$BlenderMcpVersion = '1.0.3'
# ComfyUI core templates refkit drives; their embedded model lists decide what 09 downloads.
$ComfyTemplates = @(
    'image_z_image_turbo_int8', 'image_flux2_klein_image_edit_4b_distilled', 'utility_image_segment_sam3',
    'utility_depth_anything3_image_depth_estimation', 'utility-gan_upscaler',
    '3d_pixal3d_trellis2_image_to_model', '3d_hunyuan3d-v2.1',
    # added 2026-09-30 (audit): best open image/edit models, SeedVR2 upscaling, multi-view 3D, video finishing
    'image_qwen_image_2_1_t2i', 'image_qwen_image_2_1_image_edit', 'image_qwen_image_2_1_background_removal',
    'image_krea2_turbo_t2i_int8', 'image_krea2_turbo_int8_image_style_reference',
    'utility_seedvr2_3b_int8_upscale_image', 'utility_seedvr2_7b_int8_upscale_image',
    'utility_seedvr2_3b_int8_upscale_video', 'utility_video_frame_interpolation', '3d_pixal3d_multi_views',
    # added 2026-10-01 (upgrade): HiDream-O1 Dev (MIT photoreal + edit), Marigold V2 albedo (to3d --delight)
    'image_hidream_o1_dev', 'image_marigold_v2_albedo_estimation'
)
$ComfyExtraModels = @(
    'upscale_models=https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.safetensors',
    # Qwen-Image 2.1 LoRAs: AnyAngle (Apache-2.0; to3d --refine-views), Consistency (qwen-research; gen --consistent, fix)
    'loras=https://huggingface.co/lilylilith/QI_2.1_AnyAngle/resolve/main/QI2.1_AnyAngle.safetensors',
    'loras=https://huggingface.co/ausboss/Qwen-Image-2.1-Consistency-LoRA/resolve/main/qwen-image-2.1-consistency.safetensors'
)
# Hugging Face snapshots for refkit's own Python (not ComfyUI): local critic + edit scorer (vlm.py), HPSv3++ (score.py).
$RefkitHfModels = @(
    'vlm\Qwen3-VL-8B-Instruct=Qwen/Qwen3-VL-8B-Instruct',
    'scoring\EditScore-Qwen3-VL-8B-Instruct=EditScore/EditScore-Qwen3-VL-8B-Instruct',
    'scoring\HPSv3-PlusPlus-bnb-NF4=stella221125/HPSv3-PlusPlus-bnb-NF4'
)
# HPSv3++ runner (MIT) in its own uv env under <engine>\tools: it pins transformers <5.18, refkit's venv is newer.
$HpsRepo = 'https://github.com/Stella2211/hpsv3-4bit'
$HpsCommit = 'a4c8dc5'
# transformers: PickScore ranking; bitsandbytes/accelerate/peft/qwen-vl-utils/editscore: the 4-bit Qwen3-VL critic
# and EditScore (vlm.py). Weights live in <engine>\models\scoring and \vlm.
$RefkitPackages = @('opencv-python-headless', 'scikit-image', 'vtracer', 'trimesh', 'pygltflib', 'spandrel', 'pillow',
                    'numpy', 'scipy', 'requests', 'open3d', 'google-genai<3', 'transformers',   # genai 3.0 drops video params
                    'bitsandbytes', 'accelerate', 'peft', 'qwen-vl-utils', 'editscore')
# CUDA build for every torch install (refkit venv and ComfyUI's embedded Python). PyPI's Windows torch is CPU-only,
# so any uv/pip call that may touch torch must name this backend. The 4080 SUPER driver (616.x) supports cu130.
$TorchBackend = 'cu130'
$PSModules = @('PSFzf', 'CompletionPredictor', 'Terminal-Icons', 'Pester', 'Microsoft.PowerShell.SecretManagement', 'Microsoft.PowerShell.SecretStore')

function Write-Step([string]$Msg) { Write-Host "==> $Msg" -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host "    ok  $Msg" -ForegroundColor Green }
function Write-Skip([string]$Msg) { Write-Host "    --  $Msg" -ForegroundColor DarkGray }
function Write-Warn2([string]$Msg){ Write-Host "    !!  $Msg" -ForegroundColor Yellow }

function Start-PhaseLog([string]$Name) {
    Start-Transcript -Path (Join-Path $LogDir "$Name-$(Get-Date -Format yyyyMMdd-HHmmss).log") | Out-Null
}

function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-OldestBackup {
    Get-ChildItem $BackupRoot -Directory | Sort-Object Name | Select-Object -First 1
}

# PATH is read/written raw so %VAR% entries survive and the value stays REG_EXPAND_SZ.
function Get-RawPath([ValidateSet('User', 'Machine')][string]$Scope) {
    $key = Get-Item ($Scope -eq 'User' ? $UserEnvKey : $MachineEnvKey)
    @($key.GetValue('Path', '', 'DoNotExpandEnvironmentNames') -split ';' | Where-Object { $_ })
}

function Set-RawPath([ValidateSet('User', 'Machine')][string]$Scope, [string[]]$Entries) {
    Set-ItemProperty -Path ($Scope -eq 'User' ? $UserEnvKey : $MachineEnvKey) -Name Path `
        -Value ($Entries -join ';') -Type ExpandString
    Send-EnvironmentChange
}

function ConvertTo-PathKey([string]$Entry) {
    [Environment]::ExpandEnvironmentVariables($Entry).TrimEnd('\').ToLowerInvariant()
}

# Setting and clearing a throwaway user variable makes .NET broadcast WM_SETTINGCHANGE,
# so Explorer and newly started terminals pick up registry PATH edits without a sign-out.
function Send-EnvironmentChange {
    [Environment]::SetEnvironmentVariable('AISETUP_PING', '1', 'User')
    [Environment]::SetEnvironmentVariable('AISETUP_PING', $null, 'User')
}

function Test-HasExecutables([string]$Dir) {
    [bool](Get-ChildItem ([Environment]::ExpandEnvironmentVariables($Dir)) -File -ErrorAction Ignore |
        Where-Object Extension -in '.exe', '.cmd', '.bat', '.ps1', '.com' | Select-Object -First 1)
}

function Update-SessionPath {
    $env:PATH = (@(Get-RawPath Machine) + @(Get-RawPath User) |
        ForEach-Object { [Environment]::ExpandEnvironmentVariables($_) }) -join ';'
}

function Add-UserPath([string]$Dir, [switch]$Prepend) {
    if (-not (Test-Path $Dir)) { Write-Skip "not present, not added to PATH: $Dir"; return }
    $key = ConvertTo-PathKey $Dir
    $all = @(Get-RawPath Machine) + @(Get-RawPath User) | ForEach-Object { ConvertTo-PathKey $_ }
    if ($all -contains $key) { Write-Skip "already on PATH: $Dir"; return }
    $user = Get-RawPath User
    Set-RawPath User ($Prepend ? @($Dir) + $user : $user + @($Dir))
    Update-SessionPath
    Write-Ok "added to user PATH: $Dir"
}

function Remove-UserPath([string]$Dir) {
    $key = ConvertTo-PathKey $Dir
    $user = Get-RawPath User
    $kept = @($user | Where-Object { (ConvertTo-PathKey $_) -ne $key })
    if ($kept.Count -ne $user.Count) { Set-RawPath User $kept; Update-SessionPath; Write-Ok "removed from user PATH: $Dir" }
}

function Test-WingetInstalled([string]$Id) {
    $out = winget list --id $Id --exact --accept-source-agreements --disable-interactivity 2>$null | Out-String
    $out -match [regex]::Escape($Id)
}

function Install-WingetPackage([string]$Id, [string]$Override) {
    if (Test-WingetInstalled $Id) { Write-Skip "$Id already installed"; return }
    $wargs = @('install', '--id', $Id, '--exact', '--silent', '--accept-package-agreements',
               '--accept-source-agreements', '--disable-interactivity')
    if ($Override) { $wargs += @('--override', $Override) }
    winget @wargs
    if ($LASTEXITCODE -eq 0) { Write-Ok $Id } else { Write-Warn2 "$Id failed (exit $LASTEXITCODE)" }
}

# Settings files are edited as ordered hashtables so key order (and diffs) stay stable.
function Write-AtelierTemplate([string]$Source, [string]$Destination) {
    # setup\templates carry {{REPO}} / {{ENGINE}} / {{ENGINE_FWD}} instead of machine paths; fill them in on install.
    $text = (Get-Content $Source -Raw).Replace('{{REPO}}', $AtelierRoot).Replace('{{ENGINE}}', $StudioRoot).
        Replace('{{ENGINE_FWD}}', ($StudioRoot -replace '\\', '/'))
    [IO.File]::WriteAllText($Destination, $text, [Text.UTF8Encoding]::new($false))
}

function Read-JsonFile([string]$Path) { Get-Content $Path -Raw | ConvertFrom-Json -AsHashtable }
function Write-JsonFile([string]$Path, $Object) {
    $Object | ConvertTo-Json -Depth 32 | Set-Content $Path -Encoding utf8NoBOM
}

function Add-Unique([object[]]$List, [string[]]$Items) {
    @(@($List | Where-Object { $_ }) + $Items | Select-Object -Unique)
}
