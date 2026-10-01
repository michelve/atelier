# PowerShell 7 profile - installed by ~\AISetup\04-shell.ps1 (the previous profile is in ~\AISetup\backup\).
#
# Two modes, so AI agents get fast, plain shells and humans get the full experience:
#   agent       - Claude Code / Gemini CLI / Codex sessions and -Command/-NonInteractive runs: essentials only
#   interactive - predictions, fzf, zoxide, fnm auto-switching, starship prompt
# Force a mode for testing with $env:AISETUP_MODE = 'agent' | 'interactive'.

$IsAgentShell = switch ($env:AISETUP_MODE) {
    'agent'       { $true }
    'interactive' { $false }
    default {
        # -NoExit means a human keeps the shell after the command (VS Code's terminal launches this way).
        $argv = [Environment]::GetCommandLineArgs()
        [bool]($env:CLAUDECODE -or $env:GEMINI_CLI -or $env:CODEX_SANDBOX) -or (
            @($argv -match '^-(NonInteractive|noni|c|Command|e|ec|EncodedCommand|f|File)$').Count -gt 0 -and
            @($argv -match '^-(NoExit|noe)$').Count -eq 0)
    }
}
Remove-Variable argv -ErrorAction Ignore

# --- Both modes -------------------------------------------------------------------------------------------

# UTF-8 in and out, so native tools and Python round-trip non-ASCII text. Setting the console
# encodings throws when no console is attached (redirected agent shells), which is harmless.
$OutputEncoding = [Text.UTF8Encoding]::new($false)
try { [Console]::InputEncoding = [Console]::OutputEncoding = $OutputEncoding } catch {}

if ($IsAgentShell) { return }

# --- Interactive only -------------------------------------------------------------------------------------

# Predictions need a real VT console; skip them quietly when output is redirected.
try {
    Set-PSReadLineOption -EditMode Windows -PredictionSource HistoryAndPlugin -PredictionViewStyle ListView `
        -MaximumHistoryCount 50000 -HistoryNoDuplicates -BellStyle None
} catch {}
Set-PSReadLineKeyHandler -Key UpArrow -Function HistorySearchBackward
Set-PSReadLineKeyHandler -Key DownArrow -Function HistorySearchForward
Set-PSReadLineKeyHandler -Key Tab -Function MenuComplete

Import-Module CompletionPredictor -ErrorAction Ignore

# PSFzf, CommandNotFound and Terminal-Icons cost ~300ms together; load them once the first prompt is idle.
# Event actions run in their own scope, hence -Global.
$null = Register-EngineEvent -SourceIdentifier PowerShell.OnIdle -MaxTriggerCount 1 -Action {
    Import-Module Microsoft.WinGet.CommandNotFound -Global -ErrorAction Ignore
    Import-Module Terminal-Icons -Global -ErrorAction Ignore
    if (Get-Command fzf -ErrorAction Ignore) {
        Import-Module PSFzf -Global -ErrorAction Ignore
        if (Get-Module PSFzf) { Set-PsFzfOption -PSReadlineChordProvider 'Ctrl+t' -PSReadlineChordReverseHistory 'Ctrl+r' }
    }
}

# fnm's output is per-session (a fresh multishell dir), so it can't be cached like the inits below.
if (Get-Command fnm -ErrorAction Ignore) { fnm env --use-on-cd --shell powershell | Out-String | Invoke-Expression }

# zoxide and starship init scripts only change when the exe does; cache them to skip two process spawns per shell.
function Get-InitScript([string]$Name, [scriptblock]$Generate) {
    $exe = Get-Command $Name -CommandType Application -ErrorAction Ignore | Select-Object -First 1
    if (-not $exe) { return $null }
    $cache = Join-Path $env:LOCALAPPDATA "pwsh-init-cache\$Name.ps1"
    if (-not (Test-Path $cache) -or (Get-Item $cache).LastWriteTime -lt (Get-Item $exe.Source).LastWriteTime) {
        New-Item -ItemType Directory -Force (Split-Path $cache) | Out-Null
        & $Generate | Out-String | Set-Content $cache -Encoding utf8NoBOM
    }
    $cache
}
# Terminal tab title = current folder name ("~" at home). Starship calls this before drawing each prompt.
function Invoke-Starship-PreCommand {
    $path = $PWD.ProviderPath
    $Host.UI.RawUI.WindowTitle = $path -eq $HOME ? '~' : (Split-Path $path -Leaf)
}

if ($init = Get-InitScript zoxide { zoxide init powershell }) { . $init }
if ($init = Get-InitScript starship { starship init powershell --print-full-init }) { . $init }
Remove-Variable init -ErrorAction Ignore

# Claude Code's GitHub MCP server reads GITHUB_PERSONAL_ACCESS_TOKEN at startup. Pull it from gh's
# keyring on demand instead of storing the token in the environment permanently.
function claude {
    if (-not $env:GITHUB_PERSONAL_ACCESS_TOKEN -and (Get-Command gh -ErrorAction Ignore)) {
        $env:GITHUB_PERSONAL_ACCESS_TOKEN = gh auth token 2>$null
    }
    & (Get-Command claude -CommandType Application | Select-Object -First 1).Source @args
}

function ai-check { & "$HOME\AISetup\90-check.ps1" @args }
