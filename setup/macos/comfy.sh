#!/bin/sh
# Local ComfyUI ({{ENGINE}}/ComfyUI; experimental on macOS, PyTorch on Metal): localhost only, paid cloud API nodes
# disabled, shared model store. Written to ~/.local/bin/comfy by setup/shared/local-ai.ps1 from setup/macos/comfy.sh.
# refkit finds it by the engine paths below and passes its own --port (the last one wins).
# PYTORCH_ENABLE_MPS_FALLBACK runs the few ops Metal lacks on the CPU instead of failing.
export PYTHONNOUSERSITE=1
export PYTORCH_ENABLE_MPS_FALLBACK=1
cd "{{ENGINE}}/ComfyUI" || exit 1
exec venv/bin/python ComfyUI/main.py --listen 127.0.0.1 --port 8188 \
  --disable-auto-launch --disable-api-nodes --extra-model-paths-config "{{ENGINE}}/extra_model_paths.yaml" \
  --output-directory "{{ENGINE}}/output" "$@"
