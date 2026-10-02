# Recipes

Outputs default to `<input>.refkit/`. Replace paths as needed. Always finish with `refkit qa` + a visual check.

## Logo / icon from a photo, screenshot or sketch
1. `refkit analyze logo.jpg` → note palette and shapes; decide exact brand hex values.
2. `refkit cutout logo.jpg` (skip if already on a flat background).
3. `refkit vectorize logo.refkit/cutout.png --palette "#0d0d12,#8f6bff,#ece8ff" --preset clean`
   - one colour: `--mono --mono-color "#8f6bff"` (potrace gives the smoothest curves)
   - SSIM below target → `--preset detailed`, or fewer/more `--colors`, or raise `--min-side 2048`.
4. Hand-finish: replace traced circles/rounded rects with primitives, snap to grid, set viewBox, `currentColor`.
   Edit the SVG text directly or with `inkscape --actions "…" --export-filename out.svg`.
5. `refkit qa vector.svg --ref logo.jpg`; export PNG sizes with `resvg vector.svg icon-512.png -w 512`.

## Icon set in one style
1. Analyze 1-2 reference icons; fix stroke width, radius, grid (e.g. 24 px, 1.5 px stroke, 2 px radius).
2. Draw simple icons as SVG by hand (primitives, clean paths); generate complex ones with
   `refkit gen "flat line icon of X, <stroke/cap/corner style from the reference>, on white" -n 4`, then `vectorize --mono`.
3. Normalise: same viewBox, stroke, padding; `svgo --multipass`; qa each; contact sheet with `magick montage`.

## Hero image / illustration matching a reference
1. `refkit analyze ref.png`, write a precise prompt from your own look at the sheet (subject, composition,
   camera, materials, light, palette hex, edges/corners and effects exactly as the reference shows them).
   Check the model's recipe: `refkit gen --recipe krea` (or qwen / z-image).
2. Explore cheaply: `refkit gen --prompt-file p.txt -m z-image --size 1344x768 -n 4 --pick` -> view `contact.png`.
3. Final model: `-m krea` (photographic) or `-m qwen` (text, layout, strict adherence) with the refined prompt,
   `-n 2-4 --pick` again. Restyle the reference instead: `refkit gen "... Keep everything else the same." -i ref.png`
   (qwen-edit; `-m klein-edit` for a quick pass).
4. Fix small things with an edit, not a re-roll: `refkit gen "change only X" -i best.png`.
5. Size: `refkit upscale best.png --long 3840` (add `--refine "<short prompt>"` if the draft has generator mush;
   `--model 7b` for the hero).
6. Dense exact text / 4K straight out / more than 3 refs -> `-m banana --yes` (NB2, ~$0.10-0.15), same QA after.
7. Encode AVIF/WebP, `oxipng --strip safe` any PNG (removes the embedded prompt), qa.

## 3D object from a reference (for a render or WebGL)
1. `refkit cutout ref.png [--prompt "the object"]`. No photo yet? Make one that reconstructs well (text-to-3D):
   `refkit gen "<object>, three-quarter front view, centred on a plain light grey background, soft even light,
   no cast shadow" -m z-image -n 4 --pick` → cutout. `refkit analyze` flags good inputs (`3d_candidate`).
2. `refkit to3d ref.refkit/cutout.png -n 3` (Pixal3D, textured; a cutout's alpha is used as the mask, so
   `cutout --prompt "the left cup"` then to3d builds that cup). Each seed gets its own folder with
   `inspect/views.png` (textured row over clay row) and all of them go into `compare.png`, sorted by fidelity —
   the photo's own viewpoint rendered from the mesh vs the cutout (silhouette IoU, DINO). It catches broken shapes
   and front mismatches (a broken mesh scored 0.69 vs 0.97) but cannot see the back: look at the clay row for holes,
   lumps and melted edges on every side, then pick the seed. `--auto` writes `report.md` with the scores and the
   local critic's notes. Budget ~2 min per seed (mesh ~75 s, then cleanup, inspect and fidelity).
   - Boxy hard-surface objects (devices, furniture, buildings): `--hard-edges` gives crisp creases, but curved parts
     (lens barrels, knobs) turn visibly faceted — compare with a default run (`-n` / two runs) before keeping it.
   - `--quality high` (shape cascade 1536): a little more fine detail on detailed objects, lumpier smooth surfaces,
     ~15% slower. Default `standard` is the better choice for smooth objects.
   - Weak back/sides: `--refine-views` renders the first mesh on Pixal3D's multi-view rig, redraws each view in the
     photo's look (Qwen + AnyAngle; a redraw whose silhouette doesn't match its render is retried, then replaced
     by the render), and rebuilds with Pixal3D multi-view (~10 min). Both meshes land in `compare.png`; keep the
     better one — on a simple symmetric object (a mug) the two came out comparable, so use it when the single-view
     back/sides are actually wrong.
   - Glossy or strongly lit photos: `--delight` (Marigold albedo) so highlights don't bake into the texture.
     Specular noise (water drops, glitter) still needs an edit first (`gen "remove the water droplets. Keep
     everything else the same." -i photo.png`).
   - More angles you already have (a turnaround sheet cut into views, or renders):
     `refkit to3d --views front.png,left.png,back.png,right.png`.
   - Pixal3D builds the mesh in the photo's camera frame; cleanup stands it on its base (`levelled_deg` in
     model.json). `--no-level` keeps the camera frame (e.g. to compare with the photo's framing).
   - Shape-only / VRAM tight -> `-m hunyuan3d`. TRELLIS.2 (`-m trellis2`) occasionally returns a shredded mesh:
     the clay row shows it at once, and qa FAILs it (non-manifold > 3%); rerun with another seed.
3. Keep the generated PBR textures (default). Replace materials in Blender only to match the reference/prompt
   (`--material orbitra-*` exists for Orbitra work only).
4. Fix in Blender if needed (bevel hard edges, separate parts, re-material): headless
   `blender -b in.glb -P fix.py` or live via Blender MCP.
5. Web: `model.glb` is meshopt + WebP (smallest download). `--ktx2` -> KTX2 (UASTC normal/ORM, ETC1S colour):
   bigger file, far less GPU memory. three.js: `GLTFLoader` + `setMeshoptDecoder(MeshoptDecoder)` (+ `KTX2Loader`).

## Product turntable / hero render
- Quick look: `refkit render model.glb --frames 1 --res 1200x1200` (still) → view it.
- Final: `refkit render model.glb --frames 144 --res 1600x1600 --samples 256` (6 s loop).
- Own scene with its camera/animation: `refkit render scene.blend --as-is`.
- Lighting: `--look neutral` = studio area lights + Blender's studio HDRI for reflections, AgX base contrast
  (colours stay close to the source photo); match the reference's light by editing the rig (Blender MCP / script).
  `--look orbitra` only for Orbitra work.
- Web delivery: `--transparent` (WebM/AVIF/WebP keep alpha), `--av1` (~20% smaller MP4). qa checks faststart,
  loop seam and the 3 MB hero-loop budget.

## Restyle to a given palette (only when asked)
- Raster: `refkit gen "recolor to <palette from the prompt/reference>, keep everything else" -i in.png`, or
  deterministic: `magick in.png ( palette.png ) -remap out.png` / `-modulate` / `-level`.
- SVG: replace fill hexes directly (text edit), then qa with `--tokens`.

## Textures / tiles
- `refkit gen "seamless tileable brushed satin black metal texture, top-down, even lighting" --size 1024x1024`;
  check tiling: `magick tex.png ( +clone ) +append ( +clone ) -append tile-check.png`; fix seams with offset +
  clone (`magick tex.png -roll +512+512 rolled.png`) and re-generate/inpaint the seam area.

## Local video clip (free, Wan 2.2)
1. Keyframe first: `refkit gen` the opening frame at the clip's shape (landscape 1280x704 or portrait 704x1280).
   Get it right before animating, since motion won't fix a weak frame. View it.
2. Draft the motion: `refkit video "steam rises slowly from the cup, the camera holds still" -m wan-fast --from
   key.png` (14B + 4-step LoRA, 480p, 16 fps, ~75 s for 5 s). Describe only the motion and one camera move;
   the frame already shows the scene.
3. Final: `-m wan` (5B, 720p, 24 fps, ~3.5 min for 5 s; 5 s is the tested length, `--seconds` to change it).
   Without `--from` it is text-to-video. For a like-for-like retry, reuse the seed with `--seed` (it's in the
   sidecar).
4. Finish: `--upscale` (SeedVR2) and/or `--interp 2` (FILM; makes wan-fast's 16 fps smooth). Compare a frame
   with the source: SeedVR2 can invent texture.
5. Limits: first+last frame (`--to`) and extension are Google-only. Text and logos smear in motion, so add them
   in post. qa the MP4.

## Generated video clip (Google, paid: show the estimate)
1. Keyframes locally: `refkit gen` the first frame (and a last frame via a `gen ... -i first.png` edit) at the
   clip's aspect (1280x720 / 720x1280).
2. `refkit video "slow push-in, steam rises. single unbroken scene, no scene cuts." --from first.png --yes`
   (Omni, ~$0.60 for 6 s). First + last frame / extension: `-m veo-fast --from a.png --to b.png --yes`
   (8 s forced, $0.80). Edit an Omni clip: `refkit video "make the steam thicker. Keep everything else the same."
   --continue <interaction id from the .json> --yes`.
3. Finish locally: `--upscale` (SeedVR2 to 1080p) `--interp 2` (FILM to 48 fps), or later
   `refkit video clip.mp4 --finish-only --upscale --interp 2`. SeedVR2 can invent texture on soft/low-quality
   clips: compare a frame before keeping it.
4. qa the MP4 (faststart, size); make a WebM with ffmpeg if the page needs one.

## Troubleshooting
- `refkit status` first. ComfyUI down → it auto-starts; log at `<engine>\comfyui.log`; manual: `comfy`.
- A job takes far longer than the time budget in SKILL.md → `refkit status`: other sessions' jobs share the
  queue (`jobs: N running, M queued`), and switching models between their jobs and yours reloads weights. Wait;
  never kill ComfyUI while jobs run.
- CUDA OOM → close other GPU apps (games, Ollama models: `ollama stop <m>`), retry; to3d already uses 1024
  upsample + 2048 textures; fall back to `-m hunyuan3d`.
- Embedded ComfyUI Python must run with `PYTHONNOUSERSITE=1` (legacy user site has a CPU torch) — shims do it.
- SAM 3 finds one instance → it needs `concept:N`; refkit adds `:50` automatically; lower `--threshold`.
- f3d can't open meshopt GLBs (thumbnail uses the pre-compression mesh); Blender can.
- After a ComfyUI update: `refkit smoke`. It restarts our server onto the new version if the old one is still
  running and idle; it fails with a message rather than interrupt anyone's jobs. Then it re-exports when the
  templates changed, validates every workflow, and runs gen + cutout + to3d + render + one critic call.
  `refkit smoke --force-export` re-exports anyway; `--quick` skips the 3D/render/critic part.
- Is anything out of date? `<repo>\setup\update-tools.ps1 -Part User -Check` (and `-Part Admin -Check`) lists
  what is behind and installs nothing.
- "workflow patch ... matched 0 node(s)" = a template changed shape; re-export, then fix the patch in refkit.
- Two ComfyUIs on one GPU: refkit reuses whatever of ours runs on 8188-8195 (incl. Comfy Desktop); close extras.
- Slow after an update: `refkit bench`, compare with the numbers in `~\.local\bin\comfy.cmd`'s comment.
- Nano Banana / Omni / Veo says "paid call not run": it needs `--yes` after you have shown the cost estimate.
- Reinstall / verify everything: `<repo>\setup\08-visual-tools.ps1`, `09-local-ai.ps1` (ComfyUI models, critic/
  scorer weights, the DINOv2/PickScore cache, the HPSv3++ env), `90-check.ps1 -Deep`.
