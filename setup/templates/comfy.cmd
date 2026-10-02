@echo off
rem Local ComfyUI ({{ENGINE}}\ComfyUI): localhost only, paid cloud API nodes disabled, shared model store.
rem Written to ~\.local\bin by setup\09-local-ai.ps1 from setup\templates\comfy.cmd ({{ENGINE}} = ATELIER_ENGINE).
rem PYTHONNOUSERSITE keeps a stray user site-packages (e.g. a CPU torch) out of the embedded Python.
rem Speed flags chosen by `refkit bench` on 2026-09-30 (RTX 4080 SUPER, ComfyUI 0.38, torch 2.14.1): fp16 accumulation +
rem cuBLAS ops + high-ram. Comfy Kitchen attention is set per workflow by refkit (ModelAttentionBackend node), not with
rem --use-ck-attention, so one workflow can opt out (ComfyUI issue #16027; A/B in refkit bench notes).
rem --reserve-vram 1 keeps 1 GB for Windows/desktop apps. Re-run `refkit bench` on other GPUs or after big updates.
set "PYTHONNOUSERSITE=1"
cd /d "{{ENGINE}}\ComfyUI"
"python_embeded\python.exe" -s ComfyUI\main.py --windows-standalone-build --listen 127.0.0.1 --port 8188 ^
  --disable-auto-launch --disable-api-nodes --extra-model-paths-config "{{ENGINE}}\extra_model_paths.yaml" ^
  --output-directory "{{ENGINE}}\output" ^
  --fast fp16_accumulation cublas_ops --high-ram --reserve-vram 1 %*
