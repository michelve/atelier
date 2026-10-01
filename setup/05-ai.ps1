# Phase 05 (no admin): AI working folders.
# Claude Code's own config (CLAUDE.md, MCP servers, permission rules) is changed by hand - see README.md.
. "$PSScriptRoot\lib.ps1"
Start-PhaseLog '05-ai'

Write-Step 'AI output folders'
foreach ($sub in 'images', 'docs', 'web', 'scratch') {
    New-Item -ItemType Directory -Force (Join-Path $AtelierRoot $sub) | Out-Null
}
Write-Ok "$AtelierRoot\{images,docs,web,scratch} (git-ignored)"

# The Ollama app keeps its model location in its own settings; a server started any other way
# (`ollama serve`, agents, scripts) falls back to the empty ~\.ollama\models without this.
# An existing OLLAMA_MODELS is kept; otherwise models go next to the engine folder.
$ollamaModels = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
if (-not $ollamaModels) { $ollamaModels = Join-Path (Split-Path $StudioRoot) 'ollama' }
Write-Step "OLLAMA_MODELS -> $ollamaModels"
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $ollamaModels, 'User')
Write-Ok 'set for the user'

Write-Host "`nNext: the manual Claude Code steps in README.md, then 90-check.ps1." -ForegroundColor Cyan
Stop-Transcript | Out-Null
