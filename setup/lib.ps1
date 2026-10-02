# Shared helpers and data for Atelier's setup. Dot-source it: . "$PSScriptRoot\lib.ps1" from setup\ (install, update,
# check), . "$PSScriptRoot\..\lib.ps1" from setup\shared\ and setup\<os>\.
$ErrorActionPreference = 'Stop'

$Root       = $PSScriptRoot                                     # setup\: entry points and this file
$SharedDir  = Join-Path $Root 'shared'                           # installers and data every OS uses
$PyDir      = Join-Path $SharedDir 'py'                          # Python helpers (model fetch, exporters)
$OsDir      = Join-Path $Root ($IsWindows ? 'windows' : 'macos') # this OS's shims, scheduler, adapter
$LogDir     = Join-Path $Root 'logs'
$BackupRoot = Join-Path $Root 'backup'
New-Item -ItemType Directory -Force $LogDir, $BackupRoot | Out-Null

# Atelier paths - nothing machine-specific is hard-coded:
#   $AtelierRoot  the repo clone (this folder's parent; resolved if setup\ is reached through a junction)
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
$ClaudeDir     = Join-Path $HOME '.claude'

# Install data per OS lives in atelier.jsonc (lists are {all, windows, macos}); the variables below are this OS's
# resolved values, so the scripts read them as before.
$OsKey = $IsWindows ? 'windows' : 'macos'
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
# folder=repo; the folder (under <engine>\models) uses this OS's path separator.
$RefkitHfModels = @(Select-ForOS $Manifest.refkitHfModels | ForEach-Object {
    $dir, $repo = $_ -split '=', 2; "$($dir -replace '/', [IO.Path]::DirectorySeparatorChar)=$repo" })
$RefkitHfCache  = @(Select-ForOS $Manifest.refkitHfCache)
$HpsRepo        = $Manifest.hps.repo
$HpsCommit      = $Manifest.hps.commit
$HpsEnabled     = $Manifest.hps.os -contains $OsKey
$RefkitPackages = @(Select-ForOS $Manifest.refkitPackages)
$TorchBackend   = Select-ForOS $Manifest.torchBackend   # '' = PyPI's default wheels

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

function Write-AtelierTemplate([string]$Source, [string]$Destination) {
    # setup\templates carry {{REPO}} / {{ENGINE}} / {{ENGINE_FWD}} instead of machine paths; fill them in on install.
    $text = (Get-Content $Source -Raw).Replace('{{REPO}}', $AtelierRoot).Replace('{{ENGINE}}', $StudioRoot).
        Replace('{{ENGINE_FWD}}', ($StudioRoot -replace '\\', '/'))
    [IO.File]::WriteAllText($Destination, $text, [Text.UTF8Encoding]::new($false))
}

# Settings files are edited as ordered hashtables so key order (and diffs) stay stable.
function Read-JsonFile([string]$Path) { Get-Content $Path -Raw | ConvertFrom-Json -AsHashtable }
function Write-JsonFile([string]$Path, $Object) {
    $Object | ConvertTo-Json -Depth 32 | Set-Content $Path -Encoding utf8NoBOM
}
