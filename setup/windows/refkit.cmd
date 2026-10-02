@echo off
rem refkit: Atelier's CLI. Written to ~\.local\bin by setup\shared\local-ai.ps1 from setup\windows\refkit.cmd;
rem {{REPO}} = the Atelier clone, {{ENGINE}} = the engine folder (ATELIER_ENGINE).
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "ATELIER_ENGINE={{ENGINE}}"
set "PYTHONPATH={{REPO}}\studio"
"{{ENGINE}}\venvs\refkit\Scripts\python.exe" -m refkit %*
