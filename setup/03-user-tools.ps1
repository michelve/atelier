# Phase 03 (no admin, NEW terminal after 02-admin): per-user tooling.
#   Node 24 LTS via fnm, npm prefix, scoop/uv/pip packages, PATH wiring, PowerShell modules.
. "$PSScriptRoot\lib.ps1"
if (Test-Admin) { throw 'Run this as your normal user (scoop and --user installs must not run elevated).' }
Start-PhaseLog '03-user-tools'
Update-SessionPath

Write-Step 'Node 24 LTS via fnm'
if (-not (Get-Command fnm -ErrorAction Ignore)) { throw 'fnm not found - run 02-admin.ps1 first (then open a new terminal).' }
fnm install 24
fnm default 24
# fnm's "default" alias is a stable path to the active default version, so node works in every process
# (IDEs, scheduled tasks, -NoProfile shells); interactive shells layer per-project versions on top via `fnm env`.
$fnmDir = (fnm env --json | ConvertFrom-Json).FNM_DIR
if (-not $fnmDir) { $fnmDir = "$env:APPDATA\fnm" }
Add-UserPath (Join-Path $fnmDir 'aliases\default') -Prepend
Write-Ok "node $(node -v), npm $(npm -v)"

Write-Step 'npm: keep global packages in %APPDATA%\npm regardless of Node version'
npm config set prefix "$env:APPDATA\npm" --location=user
# The Node MSI uninstall (02-admin) takes %APPDATA%\npm off the user PATH; appending keeps fnm's npm ahead of it.
Add-UserPath "$env:APPDATA\npm"
# The stale global npm@10 there would shadow the npm that ships with Node 24.
if (Test-Path "$env:APPDATA\npm\node_modules\npm") { npm uninstall -g npm; Write-Ok 'removed stale global npm@10' }
npm install -g @mermaid-js/mermaid-cli
Write-Ok 'mermaid-cli (mmdc)'

Write-Step 'scoop: Ghostscript (not in winget)'
scoop install ghostscript
Write-Ok 'ghostscript'

Write-Step 'PATH wiring for installers that do not add themselves'
Add-UserPath 'C:\Program Files\Tesseract-OCR'
Add-UserPath 'C:\Program Files\ExifTool'
# LibreOffice's program dir ships its own python.exe, so expose only soffice through a shim instead of PATH.
$shimDir = "$HOME\.local\bin"
$soffice = 'C:\Program Files\LibreOffice\program\soffice.com'
if (Test-Path $soffice) {
    "@`"$soffice`" %*" | Set-Content "$shimDir\soffice.cmd" -Encoding ascii
    Write-Ok "soffice shim -> $shimDir\soffice.cmd"
} else { Write-Warn2 'LibreOffice not found; soffice shim skipped' }
# qpdf installs to a versioned dir ("qpdf 12.4.1") without touching PATH; the shim resolves the newest one at run time.
@'
@echo off
for /d %%D in ("%ProgramFiles%\qpdf *") do set "QPDF_DIR=%%D"
"%QPDF_DIR%\bin\qpdf.exe" %*
'@ | Set-Content "$shimDir\qpdf.cmd" -Encoding ascii
Write-Ok "qpdf shim -> $shimDir\qpdf.cmd"

Write-Step 'uv tools: document/web/LLM CLIs in isolated envs'
uv tool install --upgrade 'markitdown[all]'
uv tool install --upgrade llm --with llm-anthropic --with llm-ollama
uv tool install --upgrade trafilatura
uv tool install --upgrade 'rembg[cpu,cli]' --python 3.12
Write-Ok 'markitdown, llm (+anthropic, +ollama), trafilatura, rembg'

Write-Step 'Python 3.14 libraries used by the docx/pptx/xlsx/pdf skills, plus Playwright'
python -m pip install --user --upgrade --quiet openpyxl pymupdf reportlab playwright
python -m playwright install chromium
Add-UserPath "$env:APPDATA\Python\Python314\Scripts"
Write-Ok 'openpyxl, pymupdf, reportlab, playwright + chromium'

Write-Step 'PowerShell modules (CurrentUser)'
foreach ($m in $PSModules) {
    if (Get-InstalledPSResource -Name $m -Scope CurrentUser -ErrorAction Ignore) { Write-Skip "$m already installed"; continue }
    Install-PSResource -Name $m -Scope CurrentUser -TrustRepository -Quiet
    Write-Ok $m
}

Stop-Transcript | Out-Null
