# Stacks: rules for each library, and reduced-motion strategies

Pick the sections that match the profile's Stack and Reduced motion lines. For deep API questions, the installed library skills cover the API: `core-3d-animation:motion-framer`, `core-3d-animation:gsap-scrolltrigger`, `core-3d-animation:react-three-fiber`, `animation-components:lottie-animations`, `animation-components:react-spring-physics`. This file covers the parts they don't: project conventions, reduced motion, cleanup and per-frame work.

## Reduced-motion strategies

Work inside the strategy the project already uses. Don't add a second one.

| Strategy | Profile shows | What it covers | What you still add |
| --- | --- | --- | --- |
| **Token override**: duration tokens set to `0ms` in `@media (prefers-reduced-motion: reduce) :root` | `Under reduced motion: --dur-1: 0ms …` | Anything timed with tokens | Custom timings (`--t-*`), raw delays and `calc()` delays need the component's own reduce block. JS needs its own check. |
| **Page-wide rule**: `*, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; }` | `global rule at …` | Every CSS animation and transition | JS animation (tweens, WAAPI, GSAP, motion, canvas) still needs a check. End states that depend on the animation finishing must still be correct. |
| **Per-component block** | `@media (reduce) blocks in N files` | That component only | A block next to every new custom timing, covering the same kind of property: an `animation: none` rule doesn't stop a transition. |
| **no-preference wrap**: the entrance only exists inside `@media (prefers-reduced-motion: no-preference)` | `no-preference blocks` | That entrance. Under reduce the end state shows. | Nothing for that entrance. Keep the start state (`opacity: 0`) inside the wrap too. |
| **JS check**: `reducedMotion()`, `useReducedMotion()`, `matchMedia` | `JS: …` | JS-driven motion | Use the project's own check. For long-lived components, listen for changes (`use-reduced-motion.ts`). |
| **Library config**: `MotionConfig reducedMotion="user"`, `gsap.matchMedia()` | `MotionConfig …` | That library's animations | Nothing, once it's configured at the root. |

**Completion events.** A 0ms transition fires no `transitionend`, and a 0ms animation's `animationend` can't be relied on. Under reduce:
- call the completion path directly, or
- use a near-zero duration (`1ms` or `0.01ms`) with the lint exception comment the project already uses, saying why.

**End states.** `animation-fill-mode: both` makes a 0ms animation land on its last frame. A start state set outside `no-preference` (for example `opacity: 0` waiting for a class that JS adds only when motion is allowed) leaves content hidden under reduce.

## Plain CSS with tokens

- **Tokens:**
  - Duration and easing custom properties go on `:root`, with the reduce override next to them ([templates/motion-tokens.css](../templates/motion-tokens.css)).
  - Choreography timings go on the component's root rule as `--t-*`.
  - A local easing (such as `--morph`) is fine when one piece needs its own curve.
- **`@property`** registers the custom properties you transition (colours, mask percentages, numbers). Put it at the top of the file, outside other at-rules.
- **Cascade layers:** the component's motion CSS goes in the same layer as the rest of its CSS.
- **Keyframes** are global in plain stylesheets, so prefix them with the component name. Define shared ones (`check-draw`) once.

## CSS modules and Next.js

- Tokens live in the global stylesheet (`app/globals.css`); modules use `var()`. Keyframes inside modules are scoped, so repeated names are fine.
- Server components can't hold refs. Pointer, scroll and in-view motion belong in a `"use client"` component.
- A reduced-motion hook must be SSR-safe: it returns `false` on the server and follows changes ([templates/use-reduced-motion.ts](../templates/use-reduced-motion.ts)).
- Route transitions: View Transitions ([recipes](recipes.md#view-transitions)), or the framework's own support if the project uses it.

## Tailwind v4

- **Easing and animation tokens** go in `@theme`:
  - `--ease-*` becomes the `ease-*` utilities.
  - `--animate-*` plus `@keyframes` inside `@theme` becomes the `animate-*` utilities.
  - Overriding `--ease-out` changes the built-in `ease-out` utility too.
- **Durations** have no theme namespace; `duration-<number>` is in ms. Keep duration tokens as plain custom properties on `:root` with the reduce override, and use them with `duration-(--dur-2)` and `delay-(--t-lag)` ([templates/motion-theme.css](../templates/motion-theme.css)).
- **No arbitrary timings.** `ease-[cubic-bezier(…)]` or `duration-[250ms]` repeat a value that belongs in the theme; the scanner flags them.
- **Reduced motion:**
  - With a page-wide rule, CSS needs nothing more.
  - Without one, pair motion utilities with `motion-safe:` (`motion-safe:animate-spin`), or add `motion-reduce:transition-none` / `motion-reduce:animate-none`.
  - `motion-reduce:hover:translate-y-0` undoes a hover lift.
- **tw-animate-css** (`animate-in fade-in slide-in-from-bottom-2`) needs the same reduce handling. Its durations come from `duration-*` utilities.

## motion/react (Framer Motion)

- **Reduced motion:** `<MotionConfig reducedMotion="user">` at the app root. Under reduce, transform and layout animations are skipped, while opacity and colour still animate. Use `useReducedMotion()` only for bespoke choices, such as swapping a slide for a fade.
- **One presets module** mirrors the CSS tokens (motion takes seconds):
  ```ts
  export const ease = { out: [0.22, 1, 0.36, 1], inOut: [0.65, 0, 0.35, 1] } as const;
  export const transitions = {
    fast: { duration: 0.2, ease: ease.out },
    enter: { duration: 0.6, ease: ease.out },
    spring: { type: "spring", stiffness: 400, damping: 30 },
  } as const;
  ```
  Use `transition={transitions.enter}`, not inline `ease: [...]` arrays. The scanner reports inline timings as `js-timing`.
- **Per-frame values:** `useMotionValue`, `useTransform`, `useSpring`, `useScroll`, and `style={{ x }}`. Never `useState` from a pointer or scroll handler.
- **Presence:**
  - `AnimatePresence` with stable `key`s
  - `mode="wait"` for content swaps
  - `initial={false}` to skip the entrance on first render
- **Layout animations:** `layout` and `layoutId` do FLIP for you. `layout="position"` avoids stretching text. Group related ones in `LayoutGroup`.
- **Imports:** the package is `motion`, imported from `motion/react`; `framer-motion` is the older name. Use whichever the project already imports.

## GSAP

- **Cleanup in React:** `useGSAP(() => { … }, { scope: ref })` from `@gsap/react` reverts everything on unmount. Without it, create a `gsap.context(() => { … }, ref)` and call `ctx.revert()` in the effect cleanup.
- **Reduced motion:**
  ```js
  const mm = gsap.matchMedia();
  mm.add({ motion: "(prefers-reduced-motion: no-preference)", reduce: "(prefers-reduced-motion: reduce)" }, (ctx) => {
    const { reduce } = ctx.conditions;
    gsap.from(".card", { y: reduce ? 0 : 40, autoAlpha: 0, duration: reduce ? 0 : 0.6, stagger: reduce ? 0 : 0.06 });
  });
  // revert with mm.revert() (useGSAP and gsap.context do it for you)
  ```
- **ScrollTrigger:**
  - Killed by the context on cleanup.
  - Call `ScrollTrigger.refresh()` after late layout changes (fonts, images).
  - Under reduce: no scrub pinning or scroll-jacking; show the end state.
- **Pointer:** `const x = gsap.quickTo(el, "x", { duration: 0.4, ease: "power3" })` once, then `x(value)` on every move. Don't create a tween per event.
- **Timings:** one presets object in seconds that mirrors the CSS tokens. Don't sprinkle numbers.

## React Three Fiber and three.js

- **Animate in `useFrame((state, delta) => …)`** by mutating refs. Use `THREE.MathUtils.damp(current, target, lambda, delta)`, which is frame-rate independent, rather than a lerp per frame. Never `setState` in `useFrame`.
- **Idle:** use `frameloop="demand"` and call `invalidate()` on change. Pause when the canvas is off-screen (IntersectionObserver on its container) or the tab is hidden.
- **Reduced motion:**
  - Read it reactively ([templates/use-reduced-motion.ts](../templates/use-reduced-motion.ts)). A single read at mount misses later changes.
  - Render a still frame, and stop auto-rotation, floating and camera drift.
  - Direct manipulation (drag to rotate) stays, because the user drives it.
- **Springs** (`class Spring { step(target, dt) }`) must be `dt`-based and clamp large `dt` after a tab switch.

## WAAPI (`element.animate`)

- **Guard it:** `if (reducedMotion()) { applyEndState(); return; }`.
- **Keep the end state:**
  - `fill: "both"`, or
  - `anim.finished.then(() => { anim.commitStyles(); anim.cancel(); })`
- **Cancel on unmount.** Keep a `WeakMap<Element, Animation>` to cancel a running animation before starting another on the same element.
- **Timings from the CSS tokens:** `cssMs("--dur-2", el)` and `cssVar("--ease-out", el)` ([templates/anim.ts](../templates/anim.ts)). No separate JS constants that repeat the CSS values.

## Canvas and rAF loops

- **Time-based:** move by `dt`, not per frame.
- **Start and stop:** start when visible (IntersectionObserver), and stop on `visibilitychange` (hidden) and when off-screen. Prefer one loop per page.
- **Under reduce:** draw one still frame and don't start the loop.
- **Live data** (a playhead, an audio meter) can keep running under reduce. It's information, not decoration.

## Lottie, Rive and video

- **Lottie:**
  - `autoplay: !reduce`
  - `loop` only for live states
  - under reduce, `goToAndStop(lastFrame, true)` shows the final frame
- **Rive:** drive the state-machine inputs from state, and pause when off-screen.
- **Background or hero video:**
  - `autoplay muted loop playsinline`, with a `poster`
  - pause when off-screen
  - under reduce, don't mount it at all (show the poster), or pause it and remove `autoplay`

## Tests

- **Vitest or Jest with jsdom.** jsdom has no `matchMedia`, so mock it once in the test setup:
  ```ts
  let reduce = false;
  export const setReducedMotion = (on: boolean) => {
    reduce = on;
  };
  window.matchMedia = (query: string) =>
    ({
      matches: query.includes("prefers-reduced-motion: reduce") && reduce,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
  ```
  A reduced-motion test sets `setReducedMotion(true)`, triggers the change, and asserts two things: the final value is rendered at once, and completion callbacks ran without waiting for `animationend`.
- **Playwright:** projects that already run e2e tests can use `page.emulateMedia({ reducedMotion: "reduce" })`. This skill itself never opens a browser.

## Lint

Stylelint with `stylelint-declaration-strict-value` makes durations and delays come from tokens (the fitmatch setup):

```js
export default {
  plugins: ["stylelint-declaration-strict-value"],
  rules: {
    "scale-unlimited/declaration-strict-value": [
      ["/^(transition|animation)-(duration|delay)$/"],
      { expandShorthand: true, ignoreValues: ["0", "0ms", "none", "inherit", "initial", "unset"], disableFix: true },
    ],
  },
  overrides: [{ files: ["src/styles/tokens.css"], rules: { "scale-unlimited/declaration-strict-value": null } }],
};
```

It doesn't check easings or values inside `calc()`; the scanner's `raw-timing` rule catches those. A value that is deliberately off the scale gets a `stylelint-disable-line` comment saying why, and the scanner skips that line too.
