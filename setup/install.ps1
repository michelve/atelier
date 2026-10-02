<#
Atelier setup screen: runs the whole install in order, one step at a time, and shows what's done.
Start it with Setup.cmd in the repo root (double-click), or: pwsh -File setup\install.ps1

Every step's status is detected from the machine each time (nothing is cached), so it is safe to re-run and to
come back later: finished steps show [done], and "run all remaining" skips them.

  -Status      print the step list and exit
  -All         run every required step that isn't done yet, in order (no menu)
  -Step N      run just step N (no menu)
  -Engine DIR  the engine folder (ComfyUI, ~130 GB of models, venv) without being asked
  -SkipModels  install everything except the model downloads (run step 5 again later to fetch them)
#>
param([switch]$Status, [switch]$All, [int]$Step, [string]$Engine, [switch]$SkipModels)
. "$PSScriptRoot/lib.ps1"   # $AtelierRoot, $StudioRoot, package lists, Write-* helpers
$ErrorActionPreference = 'Continue'   # a failed probe must not end the setup screen

# --- probes (the OS-specific ones and the $Prereqs table come from setup\<os>\platform.ps1) ----------------------
function Get-SavedEngine { Get-UserEnv 'ATELIER_ENGINE' }
function Get-ClaudeConfig {
    # ~\.claude.json holds user-scope MCP servers and the login state (read directly: `claude mcp list` is slow).
    try { Get-Content "$HOME/.claude.json" -Raw -ErrorAction Stop | ConvertFrom-Json -AsHashtable } catch { @{} }
}
function Test-BlenderMcp { [bool](Get-ClaudeConfig).mcpServers?.blender }
function Test-ClaudeSignedIn {
    $cfg = Get-ClaudeConfig
    [bool]($cfg.oauthAccount -or $cfg.primaryApiKey -or $env:ANTHROPIC_API_KEY -or (Get-UserEnv 'ANTHROPIC_API_KEY'))
}

$VisualTools = 'vtracer', 'svgo', 'gltf-transform', 'gltfpack', 'potrace', 'resvg', 'f3d', 'blender', 'blender-mcp', 'rembg'

# --- steps -------------------------------------------------------------------------------------------------
# Check returns @{ State = 'done' | 'todo' | 'partial' | 'warn'; Note = '...' }
$Steps = @(
    @{ Key = 'system'; Title = 'System check'; Detail = $SystemCheckDetail
       Check = { Get-SystemCheck }
       Run = { Show-SystemHelp } }
    @{ Key = 'prereqs'; Title = 'Prerequisites'; Detail = $PrereqsDetail
       Check = {
           $missing = @($Prereqs | Where-Object { -not $_.Optional -and -not (& $_.Test) } | ForEach-Object { $_.Name })
           if ($missing) { @{ State = 'todo'; Note = "missing: $($missing -join ', ')" } } else { @{ State = 'done'; Note = 'all present' } }
       }
       Run = {
           Assert-PackageManager
           foreach ($p in $Prereqs) {
               if (& $p.Test) { Write-Skip "$($p.Name)"; continue }
               Write-Step "Installing $($p.Name)"
               Install-Prereq $p
               Update-SessionPath
               if (& $p.Test) { Write-Ok $p.Name } elseif ($p.Optional) { Write-Warn2 "$($p.Name) (optional) not detected" }
               else { Write-Warn2 "$($p.Name) still not detected - open a new terminal and re-run, or install it by hand" }
           }
       } }
    @{ Key = 'engine'; Title = 'Engine folder'; Detail = 'where ComfyUI, ~130 GB of models and the venv live (ATELIER_ENGINE)'
       Check = {
           $saved = Get-SavedEngine
           if ($saved) { @{ State = 'done'; Note = $saved } }
           else { @{ State = 'todo'; Note = "not chosen yet (default would be $(Get-DefaultEngine))" } }
       }
       Run = {
           $choice = $Engine
           if (-not $choice) {
               Show-FreeSpace
               $default = (Get-SavedEngine) ?? (Get-DefaultEngine)
               $answer = Read-Host "  Engine folder [$default]"
               $choice = if ($answer) { ConvertFrom-PathInput $answer } else { $default }
           }
           $choice = [IO.Path]::GetFullPath($choice)
           New-Item -ItemType Directory -Force $choice | Out-Null
           Test-EngineLocation $choice
           $free = Get-FreeSpaceGB $choice
           if ($free -and $free -lt $EngineSizeGB) { Write-Warn2 ("only {0:N0} GB free on that drive; $EngineSizeNote" -f $free) }
           Set-UserEnv 'ATELIER_ENGINE' $choice
           $env:ATELIER_ENGINE = $choice
           $script:StudioRoot = $choice
           Write-Ok "ATELIER_ENGINE = $choice (saved for your user)"
       } }
    @{ Key = 'visual'; Title = 'Visual tools'; Detail = 'shared\visual-tools.ps1: vectorizers, glTF/KTX tools, Inkscape, f3d, blender shim, Blender MCP'
       Check = {
           $missing = @($VisualTools | Where-Object { -not (Test-Cmd $_) })
           if ($missing) { @{ State = 'todo'; Note = "missing: $($missing -join ', ')" } } else { @{ State = 'done'; Note = 'all on PATH' } }
       }
       Run = { Invoke-Phase 'shared/visual-tools.ps1' } }
    @{ Key = 'ai'; Title = 'Local AI stack'; Detail = 'shared\local-ai.ps1: ComfyUI, models (~130 GB, resumable), venv, workflows, refkit + comfy commands, Claude skills'
       Check = {
           $eng = (Get-SavedEngine) ?? $StudioRoot
           $parts = [ordered]@{}
           # The local engine is required on Windows, optional on a Mac (see the run below).
           if ($EngineRequired) { $parts.ComfyUI = Test-Path "$eng/ComfyUI/ComfyUI/main.py" }
           $parts.venv      = Test-Path (Get-VenvPython "$eng/venvs/refkit")
           $parts.refkit    = Test-Path (Get-ShimPath 'refkit')
           $parts.workflows = (@(Get-ChildItem "$AtelierRoot/studio/workflows" -Filter *.api.json -ErrorAction Ignore).Count -ge $ComfyTemplates.Count)
           $models = @(Get-ChildItem "$eng/models" -Recurse -File -Include *.safetensors, *.pth -ErrorAction Ignore).Count
           $missing = @($parts.Keys | Where-Object { -not $parts[$_] })
           if ($missing.Count -eq $parts.Count) { return @{ State = 'todo'; Note = 'not installed' } }
           if ($missing -or $models -lt $MinModelFiles) { return @{ State = 'partial'; Note = "missing: $((@($missing) + $(if ($models -lt $MinModelFiles) { "models ($models files)" })) -join ', ')" } }
           @{ State = 'done'; Note = "$models model files in $eng" }
       }
       Run = {
           $extra = @(if ($SkipModels) { '-SkipModels' })
           if (-not $EngineRequired -and -not (Test-Path "$StudioRoot/ComfyUI/ComfyUI/main.py") -and -not $All -and
               (Read-Host '  Also install the optional local engine (experimental: ComfyUI on Metal with SAM 3.1, BiRefNet, Depth Anything 3, FILM; ~10 GB)? [y/N]') -match '^[Yy]') {
               $extra += '-WithEngine'
           }
           Invoke-Phase 'shared/local-ai.ps1' $extra
       } }
    @{ Key = 'claude'; Title = 'Claude Code + skills'; Detail = 'installs Claude Code, links the skills into ~\.claude\skills, connects Blender MCP'
       Check = {
           $skills = @(Get-ChildItem "$AtelierRoot/claude/skills" -Directory | Where-Object { Test-Path "$($_.FullName)/SKILL.md" })
           $linked = @($skills | Where-Object { (Get-Item "$ClaudeDir/skills/$($_.Name)" -ErrorAction Ignore).LinkType })
           $mcp = Test-BlenderMcp
           $note = "skills $($linked.Count)/$($skills.Count), Blender MCP $(if ($mcp) { 'connected' } else { 'not connected' })"
           if (-not (Test-Cmd claude)) { return @{ State = 'todo'; Note = "Claude Code not installed; $note" } }
           $signedIn = Test-ClaudeSignedIn
           if (-not $signedIn) { $note += '; sign in: run `claude` once' }
           @{ State = $(if ($linked.Count -eq $skills.Count -and $mcp -and $signedIn) { 'done' } else { 'partial' }); Note = $note }
       }
       Run = {
           if (-not (Test-Cmd claude)) {
               $go = $All -or ((Read-Host "  Install Claude Code now with the official installer ($ClaudeInstallerName)? [Y/n]") -notmatch '^[Nn]')
               if ($go) { Install-ClaudeCode }
               if (Test-Cmd claude) { Write-Ok "Claude Code $(claude --version)" }
               else { Write-Warn2 'Claude Code not installed - see https://claude.com/claude-code, then run this step again' }
           }
           & "$SharedDir/link-skills.ps1"
           # Blender MCP lets Claude drive a running Blender; 08 installs the add-on + the blender-mcp server.
           if ((Test-Cmd claude) -and (Test-Cmd blender-mcp) -and -not (Test-BlenderMcp)) {
               claude mcp add --scope user blender -- blender-mcp
               if (Test-BlenderMcp) { Write-Ok 'Blender MCP connected to Claude Code (user scope)' }
           } elseif (-not (Test-Cmd blender-mcp)) { Write-Skip 'blender-mcp not installed yet (step 4)' }
           else { Write-Skip 'Blender MCP already connected' }
           if ((Test-Cmd claude) -and -not (Test-ClaudeSignedIn)) {
               Write-Warn2 'Sign in once: open a new terminal, run `claude` and follow the login (a Claude plan or API key).'
           }
       } }
    @{ Key = 'verify'; Title = 'Verify'; Detail = 'refkit status + refkit smoke (tiny end-to-end generation and cutout)'
       Check = {
           $s = Get-Item "$AtelierRoot/scratch/smoke/smoke.png" -ErrorAction Ignore
           if ($s) { @{ State = 'done'; Note = "last smoke test $($s.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))" } }
           else { @{ State = 'todo'; Note = 'not run yet' } }
       }
       Run = {
           & (Get-ShimPath 'refkit') status
           & (Get-ShimPath 'refkit') smoke
           if ($LASTEXITCODE) { throw 'refkit smoke failed - see the output above' }
           Write-Ok "look at $AtelierRoot\scratch\smoke\smoke.png"
       } }
    @{ Key = 'gemini'; Title = 'Gemini API key'; Detail = 'optional, paid: Nano Banana images, Omni/Veo video'; Optional = $true
       Check = {
           if (Test-Secret 'GEMINI_API_KEY') { @{ State = 'done'; Note = 'GEMINI_API_KEY set' } }
           else { @{ State = 'todo'; Note = 'not set (local generation works without it)' } }
       }
       Run = {
           Write-Host '  Get a key at https://aistudio.google.com/apikey. Every paid call shows its cost and needs --yes.'
           $sec = Read-Host '  Paste the key (hidden; Enter to skip)' -AsSecureString
           $key = [Net.NetworkCredential]::new('', $sec).Password
           if ($key) { Set-Secret 'GEMINI_API_KEY' $key; Write-Ok $SecretSavedNote }
           else { Write-Skip 'skipped' }
       } }
    @{ Key = 'schedule'; Title = 'Weekly updates'; Detail = $ScheduleDetail; Optional = $true
       Check = {
           $t = Get-ScheduledUpdate
           if (-not $t.Registered) { return @{ State = 'todo'; Note = 'not scheduled' } }
           @{ State = $(if ($t.Current) { 'done' } else { 'partial' }); Note = $(if ($t.Current) { $t.When } else { 'scheduled, but for another folder' }) }
       }
       Run = { Register-ScheduledUpdate } }
    @{ Key = 'bench'; Title = 'Tune speed for this GPU'; Detail = "optional: refkit bench (~15 min), then copy the winning flags into setup\$OsKey\$(Split-Path (Get-ShimPath 'comfy') -Leaf) and re-run step 5"; Optional = $true
       Check = {
           $r = Get-Item "$AtelierRoot/scratch/bench/results.json" -ErrorAction Ignore
           if ($r) { @{ State = 'done'; Note = "results $($r.LastWriteTime.ToString('yyyy-MM-dd'))" } } else { @{ State = 'todo'; Note = 'not run' } }
       }
       Run = { & (Get-ShimPath 'refkit') bench } }
)

function Invoke-Phase([string]$Script, [string[]]$Extra) {
    # Each phase runs in its own pwsh so it gets a fresh lib.ps1 (with the chosen ATELIER_ENGINE) and its own log.
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot $Script))
    if ($Extra) { $argList += $Extra }
    & pwsh @argList
    Update-SessionPath
    if ($LASTEXITCODE) { throw "$Script exited with code $LASTEXITCODE (log in $LogDir)" }
}

# --- screen ------------------------------------------------------------------------------------------------
$Tags = @{ done = @('[done]', 'Green'); todo = @('[todo]', 'Yellow'); partial = @('[part]', 'DarkYellow'); warn = @('[warn]', 'Magenta') }

function Get-StepStatus($Step) {
    try { & $Step.Check } catch { @{ State = 'todo'; Note = "check failed: $($_.Exception.Message)" } }
}

function Show-Screen {
    Write-Host ''
    Write-Host '  Atelier setup' -ForegroundColor Cyan -NoNewline
    Write-Host "   repo $AtelierRoot" -ForegroundColor DarkGray
    Write-Host ''
    $i = 0
    foreach ($s in $Steps) {
        $i++
        $st = Get-StepStatus $s
        $tag, $color = $Tags[$st.State]
        Write-Host ("  {0,2}. " -f $i) -NoNewline
        Write-Host $tag -ForegroundColor $color -NoNewline
        Write-Host (" {0,-27}" -f ($s.Title + $(if ($s.Optional) { ' *' }))) -NoNewline
        Write-Host $st.Note -ForegroundColor DarkGray
    }
    Write-Host '      * optional' -ForegroundColor DarkGray
}

function Invoke-Step([int]$Index) {
    $s = $Steps[$Index]
    Write-Host ''
    Write-Host "==> $($Index + 1). $($s.Title)" -ForegroundColor Cyan -NoNewline
    Write-Host " - $($s.Detail)" -ForegroundColor DarkGray
    try { & $s.Run; return $true }
    catch { Write-Warn2 $_.Exception.Message; return $false }
}

function Invoke-Remaining {
    for ($i = 0; $i -lt $Steps.Count; $i++) {
        $s = $Steps[$i]
        if ($s.Optional) { continue }
        $st = Get-StepStatus $s
        if ($st.State -eq 'done' -or ($s.Key -eq 'system' -and $st.State -eq 'warn')) { continue }
        if ($s.Key -eq 'system') { & $s.Run; throw $SystemCheckFix }
        if (-not (Invoke-Step $i)) { throw "step $($i + 1) ($($s.Title)) failed - fix it and choose it again" }
    }
    Write-Ok 'all required steps are done - open a new terminal and try: refkit gen "a ceramic cup on linen" -n 4 --pick'
}

Start-PhaseLog 'install'
try {
    if ($Status) { Show-Screen; return }
    if ($All) { Invoke-Remaining; Show-Screen; return }
    if ($Step) { $ok = Invoke-Step ($Step - 1); Show-Screen; if (-not $ok) { exit 1 }; return }
    while ($true) {
        Show-Screen
        Write-Host ''
        $c = Read-Host '  [Enter] run all remaining  [1-9, 10] run one step  [R] refresh  [Q] quit'
        switch -Regex ($c.Trim()) {
            '^$'        { try { Invoke-Remaining } catch { Write-Warn2 $_.Exception.Message } }
            '^[Qq]$'    { return }
            '^[Rr]$'    { }
            '^\d+$'     { $n = [int]$c - 1; if ($n -ge 0 -and $n -lt $Steps.Count) { [void](Invoke-Step $n) } else { Write-Warn2 'no such step' } }
            default     { Write-Warn2 'type a step number, Enter, R or Q' }
        }
    }
} finally { Stop-Transcript | Out-Null }
