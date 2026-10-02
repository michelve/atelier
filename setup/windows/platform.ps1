# Windows side of Atelier's setup: everything that differs from macOS (registry environment, winget/scoop, Task
# Scheduler, ComfyUI portable, .cmd shims, venv layout). lib.ps1 dot-sources it; setup\macos\platform.ps1 defines the
# same functions and variables, so keep the two in step.

$ShimDir       = Join-Path $HOME '.local\bin'
$UserEnvKey    = 'HKCU:\Environment'
$MachineEnvKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
# The workflow exporter drives the real ComfyUI frontend with Playwright from the system Python (its user site).
$ExporterPython = 'python'
# What the checks import to prove the venvs work, and how torch reports the GPU.
$VenvImports   = 'torch, cv2, vtracer, trimesh, spandrel, bitsandbytes, peft, editscore'
$TorchGpuProbe = 'torch.cuda.is_available()'
# The local engine (ComfyUI + models) is required here; tools the check may skip when missing: none.
$EngineRequired = $true
$OptionalTools  = @()

# --- user environment ---------------------------------------------------------------------------------------
function Get-UserEnv([string]$Name) { [Environment]::GetEnvironmentVariable($Name, 'User') }
function Set-UserEnv([string]$Name, [string]$Value) { [Environment]::SetEnvironmentVariable($Name, $Value, 'User') }
# API keys are user environment variables on Windows, like the other settings.
function Test-Secret([string]$Name) { [bool](Get-UserEnv $Name) }
function Set-Secret([string]$Name, [string]$Value) { Set-UserEnv $Name $Value }

function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
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

# --- paths ----------------------------------------------------------------------------------------------------
function Get-VenvPython([string]$Venv) { Join-Path $Venv 'Scripts\python.exe' }
function Get-VenvBin([string]$Venv, [string]$Name) { Join-Path $Venv "Scripts\$Name.exe" }
function Get-EnginePython { Join-Path $StudioRoot 'ComfyUI\python_embeded\python.exe' }
function Get-ShimPath([string]$Name) { Join-Path $ShimDir "$Name.cmd" }
# setup\windows\<name>.cmd, rendered with this clone's and the engine's paths.
function Write-Shim([string]$Name) { Write-AtelierTemplate (Join-Path $OsDir "$Name.cmd") (Get-ShimPath $Name) }

function Find-7Zip {
    (Get-Command 7z -ErrorAction Ignore).Source ??
        (@("$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1)
}
function Find-Blender {
    Get-ChildItem "$env:ProgramFiles\Blender Foundation" -Directory -Filter 'Blender *' -ErrorAction Ignore |
        Where-Object { Test-Path "$($_.FullName)\blender.exe" } | Select-Object -Last 1
}

# --- setup screen (install.ps1) ---------------------------------------------------------------------------------
$SystemCheckDetail = 'Windows 11, NVIDIA GPU + driver, VRAM'
function Get-SystemCheck {
    $gpu = if (Get-Command nvidia-smi -ErrorAction Ignore) { nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null | Select-Object -First 1 }
    $win11 = [Environment]::OSVersion.Version.Build -ge 22000
    if (-not $gpu) { return @{ State = 'todo'; Note = 'no NVIDIA GPU/driver found (nvidia-smi)' } }
    $name, $mem, $drv = $gpu -split ',\s*'
    $gb = [math]::Round([double]$mem / 1024)
    $state = if ($win11 -and $gb -ge 15) { 'done' } else { 'warn' }
    @{ State = $state; Note = "$name, $gb GB, driver $drv$(if (-not $win11) { ' - Windows 11 recommended' })$(if ($gb -lt 15) { ' - 16 GB VRAM recommended' })" }
}
function Show-SystemHelp {
    Write-Host '  Atelier needs Windows 11 and an NVIDIA GPU (16 GB VRAM recommended; the local models use CUDA).'
    Write-Host '  No NVIDIA driver? Install the latest Game Ready / Studio driver from nvidia.com, then come back.'
}
$SystemCheckFix = 'fix the system check first (NVIDIA GPU + driver)'

function Test-Python {
    # The Microsoft Store "python" alias in WindowsApps only opens the Store; it doesn't count.
    $p = Get-Command python -ErrorAction Ignore
    if (-not $p -or $p.Source -like '*\WindowsApps\*') { return $false }
    (& python -c "import sys; print(sys.version_info >= (3, 10))" 2>$null) -eq 'True'
}
function Test-Playwright {
    if (-not (Test-Python)) { return $false }
    $env:PYTHONNOUSERSITE = $null
    & python -c "import playwright" 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    # Browsers live in PLAYWRIGHT_BROWSERS_PATH when it's set (e.g. moved off C:), else %LOCALAPPDATA%\ms-playwright.
    $browsers = $env:PLAYWRIGHT_BROWSERS_PATH ?? [Environment]::GetEnvironmentVariable('PLAYWRIGHT_BROWSERS_PATH', 'User') ??
        "$env:LOCALAPPDATA\ms-playwright"
    [bool](Get-ChildItem $browsers -Directory -Filter 'chromium*' -ErrorAction Ignore)
}
$PrereqsDetail = 'Git, uv, Python, Node, 7-Zip, Blender, FFmpeg, ImageMagick, Scoop, Playwright'
$Prereqs = @(
    @{ Name = 'Git';                 Test = { Test-Cmd git };      Winget = 'Git.Git' }
    @{ Name = 'uv (Python manager)'; Test = { Test-Cmd uv };       Winget = 'astral-sh.uv' }
    @{ Name = 'Python 3.10+';        Test = { Test-Python };       Winget = 'Python.Python.3.13' }
    @{ Name = 'Node.js (npm)';       Test = { Test-Cmd npm };      Winget = 'OpenJS.NodeJS.LTS' }
    @{ Name = '7-Zip';               Test = { [bool](Find-7Zip) }; Winget = '7zip.7zip' }
    @{ Name = 'Blender';             Test = { [bool](Find-Blender) }; Winget = 'BlenderFoundation.Blender' }
    @{ Name = 'FFmpeg';              Test = { Test-Cmd ffmpeg };   Winget = 'Gyan.FFmpeg' }
    @{ Name = 'ImageMagick';         Test = { Test-Cmd magick };   Winget = 'ImageMagick.ImageMagick' }
    @{ Name = 'ExifTool';            Test = { Test-Cmd exiftool }; Winget = 'OliverBetz.ExifTool' }
    @{ Name = 'oxipng';              Test = { Test-Cmd oxipng };   Winget = 'Shssoichiro.Oxipng' }
    @{ Name = 'Tesseract OCR';       Test = { (Test-Cmd tesseract) -or (Test-Path "$env:ProgramFiles\Tesseract-OCR\tesseract.exe") }
       Winget = 'UB-Mannheim.TesseractOCR'; Optional = $true }
    @{ Name = 'Scoop';               Test = { Test-Cmd scoop }
       Custom = { Invoke-RestMethod https://get.scoop.sh | Invoke-Expression } }
    @{ Name = 'Playwright + Chromium'; Test = { Test-Playwright }
       Custom = { $env:PYTHONNOUSERSITE = $null
                  python -m pip install --user --upgrade playwright
                  python -m playwright install chromium } }
)
function Assert-PackageManager {
    if (-not (Test-Cmd winget)) { throw 'winget is missing: install "App Installer" from the Microsoft Store, then re-run.' }
}
function Install-Prereq($P) { if ($P.Winget) { Install-WingetPackage $P.Winget } else { & $P.Custom } }

# Engine folder: ComfyUI, ~130 GB of models and the venvs, so the user picks a big drive.
$EngineSizeGB   = 150
$EngineSizeNote = 'models alone are ~130 GB'
$MinModelFiles  = 30   # fewer model files than this = the download didn't finish
function Show-FreeSpace {
    Write-Host '  The engine needs ~150 GB. Free space per drive:'
    Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free } | ForEach-Object {
        Write-Host ("    {0}:  {1,6:N0} GB free" -f $_.Name, ($_.Free / 1GB)) }
}
function Get-FreeSpaceGB([string]$Path) { (Get-PSDrive -Name $Path.Substring(0, 1) -ErrorAction Ignore).Free / 1GB }
function Get-DefaultEngine { Join-Path $AtelierRoot 'engine' }
function ConvertFrom-PathInput([string]$Text) { $Text.Trim('"', ' ') }
function Test-EngineLocation([string]$Path) { }   # any local NTFS folder works

$SecretSavedNote = 'saved as a user environment variable'

$ClaudeInstallerName = 'claude.ai/install.ps1'
function Install-ClaudeCode {
    Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
    Add-UserPath $ShimDir
    Update-SessionPath
}

# Weekly update: Task Scheduler (registering needs elevation; the task itself runs unelevated).
$ScheduleDetail = 'optional: Task Scheduler runs setup\update.ps1 (asks for admin once)'
function Get-ScheduledUpdate {
    $t = Get-ScheduledTask -TaskPath '\Atelier\' -TaskName 'Weekly update' -ErrorAction Ignore
    if (-not $t) { return @{ Registered = $false } }
    @{ Registered = $true; Current = $t.Actions[0].Arguments -like "*$AtelierRoot\setup\update.ps1*"
       Next = ($t | Get-ScheduledTaskInfo).NextRunTime; When = 'Sundays 12:30' }
}
function Register-ScheduledUpdate {
    $p = Start-Process pwsh -Verb RunAs -Wait -PassThru -WorkingDirectory $env:WINDIR `
        -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "$OsDir\schedule.ps1"
    if ($p.ExitCode) { throw "windows\schedule.ps1 exit $($p.ExitCode)" }
}

# --- visual tools (visual-tools.ps1) ----------------------------------------------------------------------------
$VisualToolsHeader = 'scoop: vector, raster-optimise and 3D viewer CLIs'
function Backup-VisualState([string]$Dest) {
    (scoop list 6>$null).Name | Set-Content "$Dest\scoop.txt"
    $blenderConfig = Get-ChildItem "$env:APPDATA\Blender Foundation\Blender" -Directory -ErrorAction Ignore |
        Sort-Object { [version]$_.Name } | Select-Object -Last 1
    if ($blenderConfig -and (Test-Path "$($blenderConfig.FullName)\config\userpref.blend")) {
        Copy-Item "$($blenderConfig.FullName)\config\userpref.blend" "$Dest\blender-userpref.blend"
    }
}

function Install-VisualPackages {
    if ((scoop bucket list 6>$null).Name -notcontains 'extras') { scoop bucket add extras }
    $have = (scoop list 6>$null).Name
    foreach ($p in $VisualScoop) {
        if ($have -contains $p) { Write-Skip "$p already installed" }
        else { scoop install $p; Write-Ok $p }
    }

    Write-Step 'vtracer CLI (prebuilt release; cargo install needs the MSVC linker, which is not on PATH)'
    if (Get-Command vtracer -ErrorAction Ignore) { Write-Skip 'already installed' }
    else {
        $vtZip = Join-Path $env:TEMP 'vtracer-win.zip'
        # Plain release URL (no `gh auth login` needed on a fresh machine).
        curl.exe -fsSL -o $vtZip 'https://github.com/visioncortex/vtracer/releases/latest/download/vtracer-x86_64-pc-windows-msvc.zip'
        New-Item -ItemType Directory -Force $ShimDir | Out-Null
        Expand-Archive $vtZip -DestinationPath "$env:TEMP\vtracer-win" -Force
        Get-ChildItem "$env:TEMP\vtracer-win" -Recurse -Filter vtracer.exe | Select-Object -First 1 |
            Copy-Item -Destination "$ShimDir\vtracer.exe" -Force
        if (Test-Path "$ShimDir\vtracer.exe") { Write-Ok 'vtracer -> ~\.local\bin' } else { Write-Warn2 'vtracer.exe not found in the release zip' }
    }

    Write-Step 'KTX-Software (ktx/toktx for `to3d --ktx2`) via scoop'
    if ((scoop list 6>$null).Name -contains 'ktx-software') { Write-Skip 'already installed' }
    else { scoop install ktx-software }
}

function Install-BlenderShim {
    New-Item -ItemType Directory -Force $ShimDir | Out-Null
    # Blender installs to a versioned dir ("Blender 5.2"); the shim resolves the newest one at run time.
    @'
@echo off
for /d %%D in ("%ProgramFiles%\Blender Foundation\Blender *") do set "BLENDER_DIR=%%D"
"%BLENDER_DIR%\blender.exe" %*
'@ | Set-Content "$ShimDir\blender.cmd" -Encoding ascii
    Add-UserPath $ShimDir
    Write-Ok "blender shim -> $ShimDir\blender.cmd"
}

# --- engine (local-ai.ps1, update.ps1, check.ps1) ---------------------------------------------------------------
$EngineTitle = 'ComfyUI portable'
function Install-Engine([string]$ComfyDir) {
    $dl = Join-Path $StudioRoot '_downloads'
    New-Item -ItemType Directory -Force $dl | Out-Null
    # Plain release URL (no `gh auth login` needed); curl resumes an interrupted 2 GB download with -C -.
    $archive = "$dl\ComfyUI_windows_portable_nvidia.7z"
    curl.exe -fL -C - -o $archive 'https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z'
    if ($LASTEXITCODE) { throw "ComfyUI download failed (curl exit $LASTEXITCODE); re-run to resume" }
    # winget's 7-Zip doesn't put 7z.exe on PATH.
    $sevenZip = Find-7Zip
    if (-not $sevenZip) { throw '7-Zip not found: winget install 7zip.7zip (or run setup\install.ps1)' }
    & $sevenZip x -y $archive "-o$StudioRoot\_extract" | Out-Null
    Move-Item "$StudioRoot\_extract\ComfyUI_windows_portable" $ComfyDir
    Remove-Item "$StudioRoot\_extract" -Recurse -Force
    Write-Ok 'extracted'
}

function Start-EngineServer {
    # Start-Process straight on the shim: wrapping it in `cmd /c "... >> log"` breaks on quoting (and clink AutoRun).
    Start-Process -FilePath (Get-ShimPath 'comfy') -WindowStyle Hidden `
        -RedirectStandardOutput "$StudioRoot\comfyui.log" -RedirectStandardError "$StudioRoot\comfyui.err.log"
}

function Update-Engine {
    # Latest *stable* release (what update_comfyui_stable.bat does), run with the embedded Python directly:
    # `cmd /c *.bat` breaks here because clink's cmd AutoRun changes the working directory.
    # Torch is never touched (requirements leave it unpinned); upgrade it by hand, see $TorchBackend.
    if (-not (Test-Path "$StudioRoot\ComfyUI\update\update.py")) { return $false }
    $env:PYTHONNOUSERSITE = '1'
    $py = Get-EnginePython
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
    python "$OsDir\sync-comfy-desktop.py" | Out-Host   # Desktop shows the real version
    $true
}

# --- weekly update (update.ps1) ---------------------------------------------------------------------------------
$OsToolsTitle = 'scoop (Atelier tools)'
function Get-AtelierScoopApps { $VisualScoop + 'ktx-software' }

# The winget prerequisites are machine-wide installs: updating them needs elevation, so they are only reported.
$PrereqReportTitle = 'winget prerequisites (report only)'
function Get-PrereqUpdates {
    if (-not (Get-Command Get-WinGetPackage -ErrorAction Ignore)) { Write-Skip 'Microsoft.WinGet.Client not installed'; return }
    Get-WinGetPackage | Where-Object { $_.IsUpdateAvailable -and $AtelierWinget -contains $_.Id } |
        ForEach-Object { "$($_.Id) $($_.InstalledVersion) -> $($_.AvailableVersions[0]) (winget upgrade --id $($_.Id))" }
}

function Show-OsToolUpdates {
    $apps = Get-AtelierScoopApps
    scoop update | Out-Null
    scoop status | Where-Object { $apps -contains $_.Name } | Out-Host
}

function Update-OsTools {
    $apps = Get-AtelierScoopApps
    scoop update
    $installed = @((scoop list 6>$null).Name)
    $apps = @($apps | Where-Object { $installed -contains $_ })
    if ($apps) { scoop update @apps }
    # One failing app aborts the rest of `scoop update` without an error here (2026-09-27: 7zip's MSI hit
    # 1618 "another install in progress"). Retry once, then report.
    $behind = { @(scoop status | Where-Object { $apps -contains $_.Name -and $_.'Latest Version' -and $_.Info -notmatch 'Held' }) }
    $left = & $behind
    if ($left) { scoop update $left.Name; $left = & $behind }
    if ($left) { throw "still behind: $($left.Name -join ', ')" }
}
