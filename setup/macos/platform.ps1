# macOS side of Atelier's setup (Apple Silicon): Homebrew, settings in ~/.config/atelier/env (sourced by ~/.zprofile),
# API keys in the login Keychain, launchd for the weekly update, sh shims, and an optional, experimental ComfyUI
# engine (git checkout + uv venv, PyTorch on Metal). lib.ps1 dot-sources it; setup/windows/platform.ps1 defines the
# same functions and variables, so keep the two in step. A Mac has no CUDA: refkit's caps.py says what runs here.

$ShimDir     = Join-Path $HOME '.local/bin'
$EnvFile     = Join-Path $HOME '.config/atelier/env'
$KeychainService = 'atelier'   # login Keychain: service "atelier", account = the variable name (as refkit reads it)
# What the checks import to prove the venvs work, and how torch reports the GPU.
$VenvImports   = 'torch, cv2, vtracer, trimesh, spandrel'
$TorchGpuProbe = 'torch.backends.mps.is_available()'
# The local engine is optional on a Mac; tools the check skips when they are missing.
$EngineRequired = $false
$OptionalTools  = @('vtracer', 'toktx', 'ktx', 'comfy', 'python')   # python: uv builds the venvs
$SkillLinkType  = 'SymbolicLink'

# --- user environment -----------------------------------------------------------------------------------------
# ~/.config/atelier/env holds `export NAME='value'` lines; ~/.zprofile sources it (marker block), so new terminals,
# launchd (via the plist) and refkit (host.saved_env) all see the same values.
function Get-EnvLines { if (Test-Path $EnvFile) { @(Get-Content $EnvFile) } else { @() } }
function Get-UserEnv([string]$Name) {
    $line = Get-EnvLines | Where-Object { $_ -match "^export $([regex]::Escape($Name))=" } | Select-Object -Last 1
    if ($line -match "^export [^=]+='(.*)'$") { $Matches[1] -replace "'\\''", "'" }
}
function Set-UserEnv([string]$Name, [string]$Value) {
    New-Item -ItemType Directory -Force (Split-Path $EnvFile) | Out-Null
    $kept = @(Get-EnvLines | Where-Object { $_ -notmatch "^export $([regex]::Escape($Name))=" })
    if ($Value) { $kept += "export $Name='$($Value -replace "'", "'\''")'" }
    Set-Content $EnvFile $kept -Encoding utf8NoBOM
    chmod 600 $EnvFile
    Add-ProfileSource
}
function Add-ProfileSource {
    $zprofile = Join-Path $HOME '.zprofile'
    $marker = '# >>> atelier >>>'
    if ((Test-Path $zprofile) -and (Select-String -Path $zprofile -SimpleMatch $marker -Quiet)) { return }
    Add-Content $zprofile @(
        '', $marker, '[ -f "$HOME/.config/atelier/env" ] && . "$HOME/.config/atelier/env"', '# <<< atelier <<<'
    ) -Encoding utf8NoBOM
}
function Test-Secret([string]$Name) {
    security find-generic-password -s $KeychainService -a $Name *> $null
    $LASTEXITCODE -eq 0
}
function Set-Secret([string]$Name, [string]$Value) {
    security add-generic-password -U -s $KeychainService -a $Name -w $Value
    if ($LASTEXITCODE) { throw "could not save $Name in the login Keychain (security exit $LASTEXITCODE)" }
}
$SecretSavedNote = 'saved in your login Keychain (service "atelier")'

function Test-Admin { (id -u) -eq '0' }

function Update-SessionPath {
    $want = @('/opt/homebrew/bin', '/opt/homebrew/sbin', $ShimDir) +
        @(Get-EnvLines | ForEach-Object { if ($_ -match '^export PATH="([^":$]+):\$PATH"$') { $Matches[1] } })
    foreach ($dir in $want) {
        if ((Test-Path $dir) -and ($env:PATH -split ':') -notcontains $dir) { $env:PATH = "${dir}:$env:PATH" }
    }
}
function Add-UserPath([string]$Dir, [switch]$Prepend) {
    if (-not (Test-Path $Dir)) { Write-Skip "not present, not added to PATH: $Dir"; return }
    $line = "export PATH=`"${Dir}:`$PATH`""
    if ((Get-EnvLines) -contains $line) { Write-Skip "already on PATH: $Dir"; Update-SessionPath; return }
    New-Item -ItemType Directory -Force (Split-Path $EnvFile) | Out-Null
    Add-Content $EnvFile $line -Encoding utf8NoBOM
    Add-ProfileSource
    Update-SessionPath
    Write-Ok "added to PATH (~/.config/atelier/env): $Dir"
}

function Install-BrewPackage([string]$Name, [switch]$Cask) {
    $kind = $Cask ? '--cask' : '--formula'
    if (brew list $kind $Name 2>$null) { Write-Skip "$Name already installed"; return }
    brew install $kind $Name
    if ($LASTEXITCODE -eq 0) { Write-Ok $Name } else { Write-Warn2 "$Name failed (exit $LASTEXITCODE)" }
}

# --- paths ----------------------------------------------------------------------------------------------------
function Get-VenvPython([string]$Venv) { Join-Path $Venv 'bin/python' }
function Get-VenvBin([string]$Venv, [string]$Name) { Join-Path $Venv "bin/$Name" }
function Get-EnginePython { Join-Path $StudioRoot 'ComfyUI/venv/bin/python' }
# The exporter and export-requirements run with refkit's own venv here (no system Python needed).
function Get-ExporterPython { Get-VenvPython (Join-Path $StudioRoot 'venvs/refkit') }
function Get-ShimPath([string]$Name) { Join-Path $ShimDir $Name }
# setup/macos/<name>.sh, rendered with this clone's and the engine's paths, as an executable ~/.local/bin/<name>.
function Write-Shim([string]$Name) {
    New-Item -ItemType Directory -Force $ShimDir | Out-Null
    Write-AtelierTemplate (Join-Path $OsDir "$Name.sh") (Get-ShimPath $Name)
    chmod 755 (Get-ShimPath $Name)
}
function Write-AppShim([string]$Name, [string]$App, [string]$Binary) {
    # A cask app's CLI, found at run time in /Applications or ~/Applications.
    New-Item -ItemType Directory -Force $ShimDir | Out-Null
    $path = Get-ShimPath $Name
    @"
#!/bin/sh
# $Name -> $App ($Binary), written by Atelier's setup.
for d in /Applications "`$HOME/Applications"; do
  [ -x "`$d/$App/Contents/MacOS/$Binary" ] && exec "`$d/$App/Contents/MacOS/$Binary" "`$@"
done
echo "$Name`: $App not found in /Applications or ~/Applications" >&2; exit 127
"@ -replace "`r`n", "`n" | Set-Content $path -Encoding utf8NoBOM -NoNewline
    chmod 755 $path
    Write-Ok "$Name shim -> $path"
}

function Find-Blender {
    @('/Applications/Blender.app', (Join-Path $HOME 'Applications/Blender.app')) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

# --- setup screen (install.ps1) ---------------------------------------------------------------------------------
$SystemCheckDetail = 'macOS on Apple Silicon (arm64, not under Rosetta), memory'
function Get-SystemCheck {
    $arch = uname -m
    $rosetta = (sysctl -n sysctl.proc_translated 2>$null) -eq '1'
    if ($arch -ne 'arm64' -or $rosetta) {
        return @{ State = 'todo'; Note = "needs Apple Silicon running natively (this shell: $arch$(if ($rosetta) { ', under Rosetta' }))" }
    }
    $chip = sysctl -n machdep.cpu.brand_string
    $gb = [math]::Round([double](sysctl -n hw.memsize) / 1GB)
    @{ State = 'done'; Note = "$chip, $gb GB, macOS $(sw_vers -productVersion); no CUDA, so local GPU models stay on the NVIDIA PC" }
}
function Show-SystemHelp {
    Write-Host '  Atelier on a Mac needs Apple Silicon and a native (arm64) terminal: in Finder, Get Info on Terminal and'
    Write-Host '  untick "Open using Rosetta", then run ./Setup.command again.'
}
$SystemCheckFix = 'fix the system check first (Apple Silicon, native terminal)'

$PrereqsDetail = 'Homebrew, Git, uv, Node, Blender, FFmpeg, ImageMagick, ExifTool, oxipng, Tesseract'
$Prereqs = @(
    @{ Name = 'Homebrew';            Test = { Test-Cmd brew }
       Custom = { throw 'Homebrew is missing: run ./Setup.command, which installs it first.' } }
    @{ Name = 'Git';                 Test = { Test-Cmd git };      Brew = 'git' }
    @{ Name = 'uv (Python manager)'; Test = { Test-Cmd uv };       Brew = 'uv' }
    @{ Name = 'Node.js (npm)';       Test = { Test-Cmd npm };      Brew = 'node' }
    @{ Name = 'Blender';             Test = { [bool](Find-Blender) }; Cask = 'blender' }
    @{ Name = 'FFmpeg';              Test = { Test-Cmd ffmpeg };   Brew = 'ffmpeg' }
    @{ Name = 'ImageMagick';         Test = { Test-Cmd magick };   Brew = 'imagemagick' }
    @{ Name = 'ExifTool';            Test = { Test-Cmd exiftool }; Brew = 'exiftool' }
    @{ Name = 'oxipng';              Test = { Test-Cmd oxipng };   Brew = 'oxipng' }
    @{ Name = 'Tesseract OCR';       Test = { Test-Cmd tesseract }; Brew = 'tesseract'; Optional = $true }
)
function Assert-PackageManager {
    if (-not (Test-Cmd brew)) { throw 'Homebrew is missing: run ./Setup.command, which installs it first.' }
}
function Install-Prereq($P) {
    if ($P.Brew) { Install-BrewPackage $P.Brew } elseif ($P.Cask) { Install-BrewPackage $P.Cask -Cask } else { & $P.Custom }
}

# Engine folder: the refkit venv and, if you add it, the local engine with its small model set.
$EngineSizeGB   = 15
$EngineSizeNote = 'the venv and the optional engine need ~15 GB'
$MinModelFiles  = 0
function Show-FreeSpace {
    Write-Host "  The engine folder needs ~$EngineSizeGB GB (refkit's venv; the local engine is optional). Free space:"
    foreach ($vol in @($HOME) + @(Get-ChildItem /Volumes -Directory -ErrorAction Ignore | ForEach-Object FullName)) {
        $free = Get-FreeSpaceGB $vol
        if ($free) { Write-Host ("    {0,-30} {1,6:N0} GB free" -f $vol, $free) }
    }
}
function Get-FreeSpaceGB([string]$Path) {
    $probe = $Path
    while ($probe -and -not (Test-Path $probe)) { $probe = Split-Path $probe }
    $cols = (df -Pk $probe 2>$null | Select-Object -Last 1) -split '\s+'
    if ($cols.Count -ge 4) { [double]$cols[3] / 1MB }   # 1K blocks -> GB
}
function Get-DefaultEngine { Join-Path $HOME 'AtelierEngine' }
function ConvertFrom-PathInput([string]$Text) {
    # Finder drag-and-drop escapes spaces ("My\ Drive"); a leading ~ means home.
    $t = $Text.Trim('"', "'", ' ') -replace '\\ ', ' '
    if ($t -eq '~' -or $t.StartsWith('~/')) { $t = $HOME + $t.Substring(1) }
    $t
}
function Test-EngineLocation([string]$Path) {
    # Background jobs (launchd) can't prompt for access to Documents/Desktop/iCloud or removable volumes, and iCloud
    # would upload gigabytes of models: keep the engine elsewhere.
    foreach ($bad in 'Documents', 'Desktop', 'Library/Mobile Documents') {
        if ($Path -like "$(Join-Path $HOME $bad)*") { Write-Warn2 "~/$bad is a poor place for the engine (iCloud sync, privacy prompts); ~/AtelierEngine is better" }
    }
    if ($Path -like '/Volumes/*') { Write-Warn2 'an external volume works, but the weekly update fails while it is unplugged' }
    # Keep it out of Time Machine and Spotlight.
    tmutil addexclusion $Path 2>$null
    New-Item -ItemType File -Force (Join-Path $Path '.metadata_never_index') | Out-Null
}

$ClaudeInstallerName = 'claude.ai/install.sh'
function Install-ClaudeCode {
    bash -c 'curl -fsSL https://claude.ai/install.sh | bash'
    Add-UserPath $ShimDir
    Update-SessionPath
}

# Weekly update: a launchd agent (no admin needed).
$ScheduleDetail = 'optional: launchd runs setup/update.ps1 every Sunday 12:30'
$LaunchLabel = 'com.atelier.update'
$LaunchPlist = Join-Path $HOME "Library/LaunchAgents/$LaunchLabel.plist"
function Get-ScheduledUpdate {
    if (-not (Test-Path $LaunchPlist)) { return @{ Registered = $false } }
    launchctl print "gui/$(id -u)/$LaunchLabel" *> $null
    @{ Registered = ($LASTEXITCODE -eq 0); Current = [bool](Select-String -Path $LaunchPlist -SimpleMatch "$AtelierRoot/setup/update.ps1" -Quiet)
       Next = 'Sunday 12:30'; When = 'Sundays 12:30' }
}
function Register-ScheduledUpdate { & (Join-Path $OsDir 'schedule.ps1') }

# --- visual tools (visual-tools.ps1) ----------------------------------------------------------------------------
$VisualToolsHeader = 'Homebrew: vector, raster-optimise and 3D viewer CLIs, Inkscape'
$VisualBrew = @('potrace', 'resvg', 'pngquant', 'webp', 'libavif', 'f3d')
function Backup-VisualState([string]$Dest) {
    brew list --formula 2>$null | Set-Content "$Dest/brew-formulae.txt"
    brew list --cask 2>$null | Set-Content "$Dest/brew-casks.txt"
    $prefs = Get-ChildItem (Join-Path $HOME 'Library/Application Support/Blender') -Directory -ErrorAction Ignore |
        Where-Object { $_.Name -as [version] } | Sort-Object { [version]$_.Name } | Select-Object -Last 1
    if ($prefs -and (Test-Path "$($prefs.FullName)/config/userpref.blend")) {
        Copy-Item "$($prefs.FullName)/config/userpref.blend" "$Dest/blender-userpref.blend"
    }
}
function Install-VisualPackages {
    foreach ($p in $VisualBrew) { Install-BrewPackage $p }
    Install-BrewPackage 'inkscape' -Cask
    Write-AppShim 'inkscape' 'Inkscape.app' 'inkscape'
    # refkit traces with the vtracer Python module; the CLI is optional. KTX-Software (ktx/toktx) has no Homebrew
    # package and only `to3d --ktx2` uses it, which needs the NVIDIA PC anyway.
    Write-Skip 'vtracer CLI (optional: refkit uses the vtracer Python module)'
    Write-Skip 'KTX-Software (only to3d --ktx2 uses it; to3d runs on the NVIDIA PC)'
}
function Install-BlenderShim { Write-AppShim 'blender' 'Blender.app' 'Blender'; Add-UserPath $ShimDir }

# --- engine (local-ai.ps1, update.ps1, check.ps1) ---------------------------------------------------------------
$EngineTitle = 'ComfyUI (experimental on macOS: git checkout + venv, PyTorch on Metal)'
function Get-ComfyStableTag([string]$Repo) {
    git -C $Repo tag --list 'v*' --sort=-v:refname | Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } | Select-Object -First 1
}
function Install-Engine([string]$ComfyDir) {
    $repo = Join-Path $ComfyDir 'ComfyUI'
    New-Item -ItemType Directory -Force $ComfyDir | Out-Null
    if (-not (Test-Path "$repo/.git")) { git clone --quiet https://github.com/comfyanonymous/ComfyUI $repo }
    git -C $repo fetch --tags --quiet
    $tag = Get-ComfyStableTag $repo
    git -C $repo checkout --quiet $tag
    $venv = Join-Path $ComfyDir 'venv'
    if (-not (Test-Path (Get-VenvPython $venv))) { uv venv --python 3.12 $venv }
    # PyPI's macOS torch wheels include Metal (MPS); no index or backend needed.
    uv pip install --python (Get-VenvPython $venv) torch torchvision torchaudio
    uv pip install --python (Get-VenvPython $venv) -r "$repo/requirements.txt"
    if ($LASTEXITCODE) { throw "ComfyUI requirements failed (uv exit $LASTEXITCODE)" }
    Write-Ok "ComfyUI $tag"
}
function Start-EngineServer {
    Start-Process -FilePath (Get-ShimPath 'comfy') -RedirectStandardOutput "$StudioRoot/comfyui.log" -RedirectStandardError "$StudioRoot/comfyui.err.log"
}
function Update-Engine {
    $repo = Join-Path $StudioRoot 'ComfyUI/ComfyUI'
    if (-not (Test-Path "$repo/.git")) { return $false }
    git -C $repo fetch --tags --quiet
    $tag = Get-ComfyStableTag $repo
    git -C $repo checkout --quiet $tag
    uv pip install --python (Get-EnginePython) -r "$repo/requirements.txt"
    if ($LASTEXITCODE) { throw "ComfyUI requirements failed (uv exit $LASTEXITCODE)" }
    Write-Ok "ComfyUI $tag"
    $true
}

# --- weekly update (update.ps1) ---------------------------------------------------------------------------------
# Homebrew upgrades need no elevation, so the prerequisites are upgraded with the visual tools.
$OsToolsTitle = 'Homebrew (Atelier tools and prerequisites)'
$PrereqReportTitle = 'Homebrew: outdated Atelier packages'
function Get-AtelierBrew { $VisualBrew + @($Prereqs | ForEach-Object { $_.Brew } | Where-Object { $_ }) }
function Get-AtelierCasks { 'blender', 'inkscape' }
function Get-PrereqUpdates {
    if (-not (Test-Cmd brew)) { return }
    $installed = @(brew list --formula) + @(brew list --cask)
    $mine = @(Get-AtelierBrew) + @(Get-AtelierCasks) | Where-Object { $installed -contains $_ }
    if ($mine) { brew outdated --greedy @mine 2>$null }
}
function Show-OsToolUpdates { brew update --quiet 2>$null | Out-Null }   # the outdated list is the report above
function Update-OsTools {
    brew update --quiet
    $installed = @(brew list --formula) + @(brew list --cask)
    $formulae = @(Get-AtelierBrew | Where-Object { $installed -contains $_ })
    $casks = @(Get-AtelierCasks | Where-Object { $installed -contains $_ })
    if ($formulae) { brew upgrade --formula @formulae }
    if ($casks) { brew upgrade --cask @casks }
    if ($LASTEXITCODE) { throw "brew upgrade exit $LASTEXITCODE" }
}
