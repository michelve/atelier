# Link every skill in <repo>/claude/skills into ~/.claude/skills (a junction on Windows, a symlink on macOS), so Claude
# Code loads them from the repo (edits land in git). Safe to re-run: existing links are re-pointed; a real folder
# with the same name is left alone and reported (move it away first if you want the repo version).
# Called by local-ai.ps1 and the setup screen (step 6).
. "$PSScriptRoot/../lib.ps1"
$src = Join-Path $AtelierRoot 'claude/skills'
$dst = Join-Path $ClaudeDir 'skills'
New-Item -ItemType Directory -Force $dst | Out-Null
foreach ($skill in Get-ChildItem $src -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'SKILL.md') }) {
    $link = Join-Path $dst $skill.Name
    $item = Get-Item $link -ErrorAction Ignore
    if ($item -and -not $item.LinkType) {
        Write-Warn2 "$($skill.Name): ~/.claude/skills/$($skill.Name) is a real folder, left alone"
        continue
    }
    if ($item) { $item.Delete() }   # removes only the link, never the target
    New-Item -ItemType $SkillLinkType -Path $link -Target $skill.FullName | Out-Null
    Write-Ok "$($skill.Name) -> $($skill.FullName)"
}
