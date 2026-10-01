# Audit checklist

`motion-scan.mjs audit` finds candidates. You confirm each one in context, then add the checks the scanner can't make. Report every finding as `file:line — rule — fix`, under Must fix, Should fix or Consider.

The scanner skips any line that contains `stylelint-disable` or `motion-scan-ignore`. Such a comment should say why, like `/* motion-scan-ignore -- scrub follows the pointer */`.

## Scanner rules

| Rule | Severity | What it means | Fix | Usual false positives |
| --- | --- | --- | --- | --- |
| `raw-timing` | Must | A raw `ms`/`s` value or `cubic-bezier()`/`linear()`/`steps()` in a transition or animation, including inside `calc()` (which lint misses) and inline styles | Use a token. For choreography, name a local `--t-*` at the top of the root rule. | Deliberate one-offs that already carry a lint exception (those lines are skipped). In a project with no tokens every hit is real, but propose `/motion init` instead of listing hundreds. |
| `no-reduced-motion` | Must | Moving motion with a custom timing that no reduce handling reaches. Either the file has no reduce block, or its block doesn't cover this rule or this kind of property (an `animation: none` rule doesn't stop a transition). Also GSAP or `motion` `animate()` in a file without a reduced-motion check. | Add the selector to the file's reduce block for the right property, zero the `--t-*` it uses, or move the entrance into `no-preference`. | A transition whose JS trigger already returns early under reduce (a pointer lean). A parent's `.block *` rule that covers a non-BEM child. |
| `state-per-frame` | Must | A framework state setter called from `pointermove`, `scroll`, `wheel`, a self-scheduling rAF loop or `useFrame` | Write a CSS custom property through a ref, or use a motion value or `gsap.quickTo`. Commit state only on pointerup or at the end. | A setter guarded to run once (for example `if (!started) setStarted(true)`). |
| `raf-no-guard` | Must | A self-scheduling `requestAnimationFrame` loop in a file with no reduced-motion check | Route it through the tween helper, or check reduced motion and jump to the end. | Loops that show live data (a playhead, an audio meter). Keep those, and say why. |
| `animate-no-guard` | Must | `element.animate()` in a file with no reduced-motion check | Guard it and apply the end state directly. | jQuery or libraries with their own `.animate` that are already configured for reduced motion. |
| `infinite` | Must | `infinite` animations, `repeat: -1` or `Infinity`, looping autoplay video. The note says whether it still runs under reduce. | A live state (loading, listening) stops when the state ends. Ambient motion needs every guard in [principles.md](principles.md#ambient-motion). | Spinners that only show while something is loading, and are off or static under reduce. |
| `layout-prop` | Must | Transitions or keyframes on width, height, top, left, margin, padding, font-size or gap | Use transform, scale, translate or `clip-path` insets, FLIP, or grid rows for a small disclosure. | A small disclosure that animates `height: auto` deliberately. List it as a known exception. |
| `transition-all` | Should | `transition: all` (or a shorthand with no property) | List the properties that should animate. | None. |
| `will-change` | Should | `will-change` on a resting selector | Set it on `:hover`, `.is-animating` or just before the animation, and remove it afterwards. | A long-lived compositing layer on purpose (a WebGL overlay). |
| `dup-keyframes` | Should | The same `@keyframes` name in more than one global stylesheet | Keep one shared definition, or prefix each with the component name. | CSS modules, and Vue or Svelte scoped styles (the scanner skips these). |
| `tw-arbitrary` | Should | Tailwind `duration-[…]`, `delay-[…]` or `ease-[…]` | Use a theme `--ease-*`, or `duration-(--dur-2)` with a token. | None. |
| `tw-animate-no-reduce` | Should | Tailwind `animate-*` without `motion-safe:` or `motion-reduce:`, and no page-wide rule | Use `motion-safe:animate-…` or add `motion-reduce:animate-none`. | Spinners that stay meaningful under reduce. Make them static instead. |
| `passive-listener` | Should | A `wheel` or `touch*` listener without `{ passive: true }` | Add `passive: true` unless the handler calls `preventDefault()`. | Handlers that do call `preventDefault()`. |
| `motion-no-config` | Should | `motion/react` is used, but the project has no `MotionConfig reducedMotion` and this file has no `useReducedMotion` | Add `<MotionConfig reducedMotion="user">` at the app root. | None. |
| `gsap-no-cleanup` | Should | GSAP tweens in a React component without `useGSAP`, `gsap.context` or `revert`/`kill` | Wrap them in `useGSAP(…, { scope })`. | Module-level tweens that never unmount. |
| `js-timing` | Consider | Two or more timing literals in JS animation options | Put them in one presets module that mirrors the CSS tokens, or read the tokens with `cssMs`. | Options that are already data (from an API or a CMS). |

## Checks by eye

The scanner can't see these. Look for them in the files you audit.

**Must fix**
- **Content hidden until an animation finishes, with no end state under reduce.** For example, `opacity: 0` set outside `no-preference`, waiting for a class that JS only adds when motion is allowed.
- **Focus lost during a morph or panel.** Focus doesn't move in on open or return to the trigger on close, or the focused element animates out of view.
- **Flashing** more than 3 times a second, or large high-contrast flicker.
- **Motion that runs on its own for more than 5s** (carousels, marquees, hero loops) with no pause or stop control.
- **Layout thrash:** layout reads (`getBoundingClientRect`, `offsetWidth`) after style writes, inside a per-frame handler.
- **Blocked input:** `pointer-events: none` during long transitions, or long view transitions that freeze the page.

**Should fix**
- Exits slower than entrances, or content that leaves after its container instead of before it.
- Stagger totals above ~500ms, or a stagger across a whole long list.
- A card title or label that animates in.
- Entrances that replay on re-render, tab switch or data refresh.
- A reversible state (hover, open and close) done with keyframes, so it can't be interrupted.
- JS timing constants that repeat the CSS tokens. Read the tokens with `cssMs()` instead.
- Hover motion without a `(hover: hover)` guard, which leaves sticky hover states on touch.
- An animated chart without `role="img"` and a one-sentence `aria-label`.
- A component's `transition` that replaces a shared component's hover transitions without repeating them.
- An effect that's missing from the project's motion doc, or a doc entry whose timings no longer match the code.

**Consider**
- The easing contradicts what it means: ease-in on an entrance, linear on a UI state change.
- A duration off the scale for its job, such as a 900ms hover.
- `scroll-behavior: smooth` left on under reduced motion.
- A hand-made effect that one of the [recipes](recipes.md), or the project's own library, already covers.

## Report format

```
Must fix
- src/widgets/recovery/recovery.css:567 — no-reduced-motion — the bell ring (--t-bell) still runs under reduce; add `.recovery__bell:hover svg { animation: none; }` to the reduce block at line 614.

Should fix
- …

Consider
- …

Known (from docs/motion.md)
- people-picker.css header fade: listed under Reduced motion gaps.

Dropped 6 scanner candidates as false positives (pointer leans guarded in JS).
Verdict: 5 must, 3 should, 2 consider. Fix the bell ring first: it's a hover animation that users with vestibular disorders trigger constantly.
```
