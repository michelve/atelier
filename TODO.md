# Atelier upgrade — open items

Plan: `~\.claude\plans\lovely-watching-sonnet.md` (2026-10-01). Done so far: commits aab127d, b97cca2 (local, not
pushed). An item is ticked only when it has run and its result was looked at. Keep this file until every line is
ticked or moved to "Deferred" with the reason.

## A. Quick verifications and fixes
- [x] A1 `render --ground` run once (shadow catcher visible, transparent variant too) — verified: contact shadow on dark and transparent renders
- [x] A2 `analyze` 3d_candidate hint run on an object photo and on a busy scene — fixed: std<20 heuristic missed a plain backdrop; now background texture < 8 (5/5 right)
- [x] A3 `comfy.validate()` before every submit (plan Phase 1) — submit() validates (cached /object_info, 0.004 s); bad node rejected before queueing
- [x] A4 Sidecar records the enhanced prompt when `--enhance` is used — enhanced_prompt from the template's preview node; tested with krea --enhance
- [x] A5 Paid video (Omni/Veo) outputs get a refkit sidecar (no paid test call: unit-test the record path) — record_cloud() merges into nanobanana's JSON (interaction_id kept); unit-tested, no paid call
- [x] A6 Follow jobs through the Jobs API (`/api/jobs/{id}`), `/history` as fallback — wait(): Jobs API status, /history for outputs; tested normal / cancelled / rejected
- [x] A7 Regenerate REQUIREMENTS.md / requirements*.txt (`setup/templates/export-requirements.py`) — regenerated: 70 model files / 304 GB listed, 20 deps, 119 pins
- [x] A8 `setup/90-check.ps1`: check the new pieces (VLM weights, HPSv3++ env, LoRAs, new workflows) — 90-check: VLM/scorer weights, HPSv3++ env, venv imports, deep = refkit smoke; model check skips Ming's unused 27B rewriter ($ComfySkipModels, also used by 09) — 130 checks, 0 failed
- [x] A9 `/simplify` on the full diff, apply what holds up — ~25 changes (comfy.title/drop_ui/first_output, gen.img2img shared by upscale+fix, to3d _queue_glb + finish_mesh returns the tilt, qa _text_prompt, smoke uses the real parser, video/meta/golden/vlm/score/auto trims, setup $ComfyModelArgs + update-tools if/elseif). Proof: 40 workflow graphs (every local gen model +-enhance, 3D models +-alpha, multi-view 1-4 views x framed x alpha) byte-identical before/after; 16/16 CPU tests; ruff F clean. Bug fixed on the way: a critic OOM no longer aborts --refine-views (and the VLM is always unloaded). Not done: VLM kept loaded across --auto steps (unmeasured; would share VRAM with the HPSv3++ subprocess), shared Blender helpers for views/turntable (denoiser setup differs), record_cloud inline (A5's test calls it)
- [x] A10 `update-tools.ps1` dry path — `-Check` (both parts, no elevation, installs nothing; report in logs\last-check-<part>.txt). Found: scoop updates silently failing since 2026-09-27 (7zip MSI 1618 aborted `scoop update *`; gh/podman/act/supabase left behind) -> scoop step now retries and FAILs on leftovers; blender-mcp 'outdated' was a false positive (git-tag install vs an unrelated PyPI name) -> checked against Blender Lab tags (1.0.3 = latest); ComfyUI 0.38.2 out (see A12); winget 1/30 behind (lazygit patch)
- [ ] A12 ComfyUI 0.38.0 -> 0.38.2 (released 2026-10-02: templates 0.11.74, partner nodes, Qwen int8-cache fix), re-export workflows, smoke — waiting for the user: needs a ComfyUI restart (another session was using it) and a smoke run; the weekly update also does it (Sunday 11:30)
- [x] A13 Setup/scripts/packages audit (2026-10-02) — DINOv2/PickScore/CLIP processor were downloaded on first use: now `$RefkitHfCache` pre-fetched by 09 + checked by 90-check (command run: reuses the cache); weekly update now upgrades the refkit venv BEFORE ComfyUI + smoke, so smoke covers both; smoke restarts our server onto a newer installed ComfyUI when idle (comfy.ensure_current; before, a running old server was what got validated) and errors instead of interrupting jobs; `refkit status` shows jobs running/queued; `refkit bench` refuses while jobs run (it restarts ComfyUI); -Check reports the HPSv3++ pin vs upstream; redundant blender-mcp upgrade step dropped (git-tag pin); qwen-vl-utils dropped from the explicit list (editscore brings it); REQUIREMENTS lists HF-cache models by repo name; requirements regenerated. All setup scripts parse; ruff F clean

## B. Plan features not built yet
- [x] B1 `to3d --camera ref`: render at the reference camera + silhouette IoU / DINO score vs the cutout; use it to — fidelity.py: photo-view render of the camera-frame mesh vs cutout (silhouette IoU + DINOv2); broken mesh 0.69/0.05 vs sound 0.97/0.88; sorts -n runs, drives --auto pick; front-only (backs still by eye; on the camera my pick differed from both scores)
      rank `-n` runs (plan Phase 3.1)
- [x] B3 Per-map KTX2 codecs (UASTC normal/ORM, ETC1S colour) — already the case: `optimize --texture-compress ktx2` writes UASTC normal/ORM + ETC1S colour (verified with gltf-transform inspect); the audit's 'one codec' claim was wrong
- [x] B6 MoGe 3 in the Pixal3D graph (if the template accepts it; A/B vs MoGe 2) — adopted: MoGe 3 for the fov estimate; silhouette/DINO up on both (mug 0.968->0.980/0.875->0.888, camera 0.972->0.989/0.922->0.939), visuals comparable
- [x] B7 UV unwrap `adaptive` vs `pec` A/B on the golden objects — pec stays: adaptive gave 4x the charts on the camera (8335 vs 2091), 145 s vs 3.6 s unwrap, same texture
- [x] B9 Ming-Image-0.1-Design spike (keep only if < 2 min/image, no VRAM thrash) — kept as `gen -m ming` (MIT): 17.6 s cold / ~6 s warm, ~15 GB peak; posters and UI text exact when quoted, unquoted filler text is gibberish (in the recipe); the 27B prompt rewriter is cut out

## C. Verification gaps
- [x] C1 Golden "before": run the old code (d9b54b9, git worktree) on the golden 3D inputs, compare with final — seed 1234, defaults, sheets in scratch/c1/compare-*.png. Silhouette IoU up on 4/4 (mug .964->.980, camera .975->.993, fox .958->.977, teapot .977->.981); DINO up on the camera (.915->.940), within 0.02 on the rest. Viewed: new is better on 4/4 (stands upright: levelled 2-15 deg; crisper camera dials and teapot bamboo handle; cleaner fox ears); open edges: camera 164->491 (non-manifold 510->257), fox 18->6. Found a slowdown: mesh 70->117 s on the teapot; A/B (ComfyUI execution time, same seed) traced it to the AO bake at 2048 (125/129 s vs 72 s) -> AO back to <=1024. MoGe 3 and kitchen attention made no measurable difference in that A/B (noisy: another session shared the GPU). inspect + fidelity add ~20 s per run
- [x] C2 HPSv3++ vs PickScore vs Claude's pick on a bigger set (>= 3 prompts x 4) — top-1 match with Claude's pick: HPSv3++ 3/3, PickScore 2/3 (posters x2, teapot); a 4th set (wallets) was a tie: all four ignored 'lying open' and neither scorer noticed
- [x] C3 `fix` on a genuinely broken region (not an already-good hand) — a swirled, mangled hand came back as a natural hand around the cup; nothing else changed (37 s)
- [x] C5 qa FAILs a GLB without UVs (crafted) — qa FAILs a crafted no-UV textured GLB, exit 1

## D. Wrap-up
- [x] D1 Docs/skill/README updated for everything above; memory updated — SKILL.md: 'Working well with refkit — what we've learned' (sidecars/--json, scores pre-sort, text quoting, fix-don't-re-roll, batching, 3D input rules, fidelity limits, shared-GPU rules, paid-never-a-test, measure-don't-assume) + measured time budget; recipes: local Wan video recipe, shared-queue and smoke/update-check troubleshooting; checklists: Wan video, scores-are-a-pre-sort; tools.md: models/venv/setup lists corrected, new no-go rows, 3D evidence, not-evaluated list, ComfyUI 0.38.2 noted; README weekly update; memory updated
- [ ] D2 Final commit; push only after the user says so

## Deferred (with reason)
- B4 `--quads`: AutoRemesher 1.2.0 ignores --target-quads on generated meshes (8000 asked -> 91k quads in 5.8 min; 107k from a 15k-tri input with --edge-scaling 4); Blender QuadriFlow refuses them (non-manifold), also after a voxel remesh. Re-check with a newer AutoRemesher or a manifold-repair step.
- B8: Qwen-Image-Layered tested on the poster: 72 s, 640 px max, the lighthouse layer was clean but the text layer carried a chunk of sky/sea — not clean enough for per-layer vectorize. Weights kept (fp8 20.5 GB + 7B TE); revisit with Ming-Design-Layer once ComfyUI ships a template for it.
- B12: comfy-mcp would add ~40 tools to every Claude session's context; refkit covers the production path. The user's call — one `claude mcp add` if wanted.
- A11 (09 end to end): not run (user stopped tests 2026-10-02); the changed parts were parse-checked, the new HF-cache pre-fetch command was run (no-op on this PC), 90-check's new checks were evaluated.
- B2 `--tex-upscale`: stopped mid-run at the user's request (teapot atlas 2048->4096 in 26 s, swapped back; renders not compared). Script moved to scratch/b2 (retexture.py, tex_up.sh, compare.py); not wired into refkit.
- B5 TripoSplat preview: not run (user stopped tests 2026-10-02); spike ready in scratch/b5b10/spikes.py splat.
- B10 Wan 2.2 FLF2V 4-step: not run (user stopped tests 2026-10-02); spike ready in scratch/b5b10/spikes.py flf (640x640, 81 frames).
- B11 LTX-2.5 vs Wan: blocked on the user (Hugging Face token + licence on the gated repo).
- C4 `--refine-views` on the camera: not run (user stopped tests 2026-10-02).
- C6 fresh-session test: not run (user stopped tests 2026-10-02); brief ready in scratch/c6/brief.md.
