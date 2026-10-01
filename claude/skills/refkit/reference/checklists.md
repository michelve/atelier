# Detail checklists — walk the matching list before calling anything done

Each item is a thing that separates "generated" from "production". `refkit qa` automates the ones marked (qa).

## Everything
- [ ] Matches the reference's composition, perspective, placement and proportions (side-by-side check at 100%).
- [ ] Colours are exactly the reference's / prompt's colours (or the project tokens if those were asked for),
      not "close enough" (qa `--tokens` when a palette is defined; `vectorize --palette` from the analysis).
- [ ] Corner radii, borders, strokes, glow and shadows match the reference/prompt — consistent within the piece,
      no effects added or dropped that the reference doesn't have.
- [ ] No unintended gradient banding; large subtle gradients dithered.
- [ ] Nothing cropped by accident; safe margin around the subject; optical (not just mathematical) centring.
- [ ] Filenames are meaningful (`hero-orb@2x.avif`, not `z-image-123.png`); intermediates stay in `*.refkit/`.
- [ ] A copy of any approved asset kept before replacing it.

## SVG / logo / icon
- [ ] viewBox present, no fixed width/height unless required (qa); scales cleanly from 16 px to 512 px.
- [ ] Path count sane (qa), no specks (qa), no embedded raster (qa), no hidden/empty groups, no editor metadata.
- [ ] Shapes are closed and don't overlap in ways that show hairlines at small sizes; aligned to a pixel grid for
      icons (whole-pixel coordinates at the design size, 1.5/2 px strokes land on half/whole pixels).
- [ ] Curves are smooth (no wobble or lumpy nodes) — re-trace with `--preset clean`, fewer colours, or `--mono`,
      or hand-rebuild simple geometry (circles, rounded rects) as primitives instead of traced paths.
- [ ] Colours use exact hex from the palette/tokens; `currentColor` for single-colour icons meant to inherit.
- [ ] Icon set: consistent stroke width, corner radius, optical size and padding across all icons.
- [ ] Text converted to outlines only if the font can't ship; otherwise keep live text with a web font.
- [ ] Size < 60 KB (qa budget) — `svgo --multipass` already applied; check again after hand edits.
- [ ] Render check: `resvg in.svg out.png -w 1024` and view it; also view at 32 px.

## Web raster (PNG/JPG/WebP/AVIF)
- [ ] Right pixel size for its slot at 1x and 2x (and 3x for mobile hero); even dimensions for video posters.
- [ ] Deliver AVIF + WebP (+ PNG/JPG fallback only if needed): `avifenc -q 60-70 -s 4`, `cwebp -q 80-85`;
      PNGs through `pngquant --quality 70-90` then `oxipng -o 4` (qa: size budgets).
- [ ] sRGB colour space, metadata stripped (`exiftool -all= file`), no embedded thumbnails.
- [ ] No banding in dark gradients (add 1-2 % noise before encoding if needed), no JPEG ringing around edges.
- [ ] Text in images is crisp and spelled right (generated text: `-m qwen`, then `-m banana` for dense copy;
      or overlay real text in HTML).
- [ ] No generator prompt left in the file (qa: embedded prompt/workflow): `oxipng --strip safe` / `exiftool -all=`.

## Cutout (RGBA)
- [ ] No halo / fringe (qa: alpha halo) — refkit decontaminates; for hair/glass, check on black AND white AND a
      brand colour (`magick cut.png -background '#0d0d12' -flatten`).
- [ ] No stray semi-transparent pixels far from the subject (qa); no holes inside the subject.
- [ ] Soft where the original is soft (hair, glass, motion blur), hard where it's hard (product edges).
- [ ] Trimmed to content with consistent padding (`magick cut.png -trim -bordercolor none -border 24 out.png`).

## 3D / GLB
- [ ] Silhouette matches the reference from the reference's camera angle (render a still with that framing).
- [ ] Clean topology after cleanup: no floating islands, normals outward; textured meshes keep their baked
      smooth shading (decimated before baking, so no seams); shape-only meshes get weighted normals; triangle
      count within budget (qa, default 150 k; hero 60 k is plenty for web).
- [ ] Rounded edges (qa: sharp-edge ratio); bevel in Blender if a hard edge reads as "CG".
- [ ] Materials are PBR and plausible: metallic 0 or 1 (not in between), roughness varied, no pure black/white albedo.
- [ ] Textures ≤ 2048 px (qa), webp/KTX2 compressed, meshopt compression; `gltf-transform inspect` shows no
      unused data; origin at base centre, +Y up, 1 unit = 1 m, scale sensible.
- [ ] Loads in the target: three.js/R3F needs `MeshoptDecoder` (and `KTX2Loader` if KTX2).

## Render / video / motion
- [ ] Lighting matches the reference/brief (key direction, softness, rim, background value); no blown
      highlights, no crushed blacks where detail matters. `--look neutral` is only a starting point — edit the
      light rig in Blender to match the reference when it matters.
- [ ] Enough samples: no fireflies or denoiser smear on glass/metal edges (raise `--samples` for finals: 256-512).
- [ ] Turntable loops seamlessly (qa: loop seam; refkit renders frame N+1 == frame 1); constant speed.
- [ ] MP4 H.264 yuv420p + faststart and WebM VP9 both delivered (qa); poster AVIF/WebP from frame 1.
- [ ] Motion pacing and easing match the brief/reference; respects `prefers-reduced-motion`, pauses offscreen.
- [ ] File sizes sane for autoplay (hero loop < 2-3 MB); resolution matches display size ×2 at most.

## Generated video (Omni / Veo)
- [ ] Keyframes made locally and approved before paying for motion; cost estimate shown, spend reported.
- [ ] Motion matches the brief (one clear camera move, no unwanted cuts, no morphing at the end of the clip).
- [ ] On-screen text/logos stay legible and stable through the clip (generators garble text in motion).
- [ ] Upscaled/interpolated output compared frame by frame with the source (SeedVR2 can invent texture).
- [ ] Google outputs carry a SynthID watermark: fine for personal use; mention it if it matters.

## UI graphics / brand consistency
- [ ] Same palette, radius, stroke weight and lighting language as the rest of the product.
- [ ] Works on the actual background it will sit on, in light mode too if the product has one.
- [ ] Contrast of any text ≥ WCAG AA; decorative imagery marked `alt=""`, meaningful imagery has real alt text.

## Handoff
- [ ] List every deliverable with path, dimensions/format, size, and the qa result.
- [ ] Note seeds / prompts / settings used (each `gen` output has a `.json` sidecar; Omni clips store the
      interaction id for edits) so the piece can be regenerated or extended.
- [ ] Report Google spend for the job (`<repo>\gemini-spend.csv`).
- [ ] Say plainly what isn't perfect yet and what would fix it.
