# Shared helpers and data for Atelier's setup. Dot-source it: . "$PSScriptRoot\lib.ps1" from setup\ (install, update,
# check), . "$PSScriptRoot\..\lib.ps1" from setup\shared\ and setup\<os>\.
# What differs per OS (environment, package managers, scheduler, ComfyUI install, shims, venv layout) lives in
# setup\<os>\platform.ps1, dot-sourced below; both define the same functions.
$ErrorActionPreference = 'Stop'

$Root       = $PSScriptRoot                                     # setup\: entry points and this file
$SharedDir  = Join-Path $Root 'shared'                           # installers and data every OS uses
$PyDir      = Join-Path $SharedDir 'py'                          # Python helpers (model fetch, exporters)
$OsKey      = $IsWindows ? 'windows' : ($IsMacOS ? 'macos' : $null)
if (-not $OsKey) { throw 'Atelier setup supports Windows and macOS.' }
$OsDir      = Join-Path $Root $OsKey                             # this OS's adapter, shims, scheduler
$LogDir     = Join-Path $Root 'logs'
$BackupRoot = Join-Path $Root 'backup'
New-Item -ItemType Directory -Force $LogDir, $BackupRoot | Out-Null
$ClaudeDir  = Join-Path $HOME '.claude'

function Write-Step([string]$Msg) { Write-Host "==> $Msg" -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host "    ok  $Msg" -ForegroundColor Green }
function Write-Skip([string]$Msg) { Write-Host "    --  $Msg" -ForegroundColor DarkGray }
function Write-Warn2([string]$Msg){ Write-Host "    !!  $Msg" -ForegroundColor Yellow }
function Test-Cmd([string]$Name) { [bool](Get-Command $Name -ErrorAction Ignore) }

function Start-PhaseLog([string]$Name) {
    Start-Transcript -Path (Join-Path $LogDir "$Name-$(Get-Date -Format yyyyMMdd-HHmmss).log") | Out-Null
}

. (Join-Path $OsDir 'platform.ps1')

# Atelier paths - nothing machine-specific is hard-coded:
#   $AtelierRoot  the repo clone (this folder's parent; resolved if setup\ is reached through a junction)
#   $StudioRoot   the engine folder: ComfyUI, models (~130 GB), venvs, outputs. $env:ATELIER_ENGINE, else
#                 <repo>\engine (git-ignored). Put it on a big, fast drive (the setup screen asks, step 3).
$setupItem   = Get-Item $PSScriptRoot
$setupReal   = if ($setupItem.LinkType) { @($setupItem.Target)[0] } else { $setupItem.FullName }
$AtelierRoot = Split-Path $setupReal
# A terminal opened before ATELIER_ENGINE was set won't have it: fall back to the saved user value.
$engineVar   = if ($env:ATELIER_ENGINE) { $env:ATELIER_ENGINE } else { Get-UserEnv 'ATELIER_ENGINE' }
$StudioRoot  = if ($engineVar) { $engineVar } else { Get-DefaultEngine }
$env:ATELIER_ENGINE = $StudioRoot   # child processes (export-requirements, sync-comfy-desktop, refkit) agree
$StudioCode  = Join-Path $AtelierRoot 'studio'   # refkit source + workflows

# Install data per OS lives in atelier.jsonc (lists are {all, windows, macos}); the variables below are this OS's
# resolved values, so the scripts read them as before.
$Manifest = Get-Content (Join-Path $Root 'atelier.jsonc') -Raw | ConvertFrom-Json -AsHashtable
function Select-ForOS($Entry) {
    # Emits "all" then this OS's part; nothing for an OS the entry doesn't list (so @(...) is empty, not @($null)).
    if ($Entry -isnot [Collections.IDictionary]) { return $Entry }
    if ($Entry.Contains('all')) { $Entry['all'] }
    if ($null -ne $Entry[$OsKey]) { $Entry[$OsKey] }
}
$AtelierWinget     = @(Select-ForOS $Manifest.atelierWinget)
$VisualScoop       = @(Select-ForOS $Manifest.visualScoop)
$BlenderMcpVersion = $Manifest.blenderMcpVersion
$ComfyTemplates    = @(Select-ForOS $Manifest.comfyTemplates)
$ComfyExtraModels  = @(Select-ForOS $Manifest.comfyExtraModels)
$ComfySkipModels   = @(Select-ForOS $Manifest.comfySkipModels)
# fetch-comfy-models.py arguments for both the installer (local-ai) and the check, so the check can't drift from it.
$ComfyModelArgs = @($ComfyExtraModels | ForEach-Object { '--extra'; $_ }) + @($ComfySkipModels | ForEach-Object { '--skip'; $_ })
# Single files from templates the engine can't run whole (template:file); used only when the engine is installed.
$ComfyPick      = @(Select-ForOS $Manifest.comfyPick)
$ComfyPickArgs  = @($ComfyPick | ForEach-Object { '--pick'; $_ })
# folder=repo; the folder (under <engine>\models) uses this OS's path separator.
$RefkitHfModels = @(Select-ForOS $Manifest.refkitHfModels | ForEach-Object {
    $dir, $repo = $_ -split '=', 2; "$($dir -replace '/', [IO.Path]::DirectorySeparatorChar)=$repo" })
$RefkitHfCache  = @(Select-ForOS $Manifest.refkitHfCache)
$HpsRepo        = $Manifest.hps.repo
$HpsCommit      = $Manifest.hps.commit
$HpsEnabled     = $Manifest.hps.os -contains $OsKey
$RefkitPackages = @(Select-ForOS $Manifest.refkitPackages)
$TorchBackend   = Select-ForOS $Manifest.torchBackend   # '' = PyPI's default wheels
# uv arguments that pin torch's build where the OS needs one (Windows: CUDA index), nothing elsewhere.
$TorchArgs      = $TorchBackend ? @('--torch-backend', $TorchBackend) : @()

function Write-AtelierTemplate([string]$Source, [string]$Destination) {
    # Templates carry {{REPO}} / {{ENGINE}} / {{ENGINE_FWD}} instead of machine paths; fill them in on install.
    $text = (Get-Content $Source -Raw).Replace('{{REPO}}', $AtelierRoot).Replace('{{ENGINE}}', $StudioRoot).
        Replace('{{ENGINE_FWD}}', ($StudioRoot -replace '\\', '/'))
    [IO.File]::WriteAllText($Destination, $text, [Text.UTF8Encoding]::new($false))
}

# Settings files are edited as ordered hashtables so key order (and diffs) stay stable.
function Read-JsonFile([string]$Path) { Get-Content $Path -Raw | ConvertFrom-Json -AsHashtable }
function Write-JsonFile([string]$Path, $Object) {
    $Object | ConvertTo-Json -Depth 32 | Set-Content $Path -Encoding utf8NoBOM
}
