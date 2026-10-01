@echo off
rem Atelier setup: opens the step-by-step setup screen (setup\install.ps1) in PowerShell 7.
rem Double-click it, or run it from a terminal. Safe to run again: finished steps are skipped.
where pwsh >nul 2>nul
if errorlevel 1 (
  echo PowerShell 7 is required - installing it with winget...
  winget install --id Microsoft.PowerShell -e --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo Could not install PowerShell 7. Install it from https://aka.ms/powershell and run Setup.cmd again.
    pause
    exit /b 1
  )
  set "PATH=%ProgramFiles%\PowerShell\7;%PATH%"
)
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\install.ps1" %*
if errorlevel 1 pause
