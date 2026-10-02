#!/bin/sh
# refkit: Atelier's CLI. Written to ~/.local/bin/refkit by setup/shared/local-ai.ps1 from setup/macos/refkit.sh;
# {{REPO}} = the Atelier clone, {{ENGINE}} = the engine folder (ATELIER_ENGINE).
export PYTHONNOUSERSITE=1
export PYTHONUTF8=1
export ATELIER_ENGINE="{{ENGINE}}"
export PYTHONPATH="{{REPO}}/studio"
exec "{{ENGINE}}/venvs/refkit/bin/python" -m refkit "$@"
