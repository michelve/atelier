# Motion

<!-- The /motion skill reads this file. Keep the section names: it looks for "Effects library", "Known exceptions" and "Reduced motion gaps". -->

Motion explains a change: where a panel came from, what just updated, which value is selected, that something is live. It is never decoration. <!-- or: which ambient motion the art direction allows, and its guards -->

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--dur-1` | 200ms | Hover, press, focus, colour changes |
| `--dur-2` | 600ms | Entrances, state changes, panels |
| `--dur-3` | 1200ms | Deliberate reveals such as a chart drawing |
| `--ease-out` | `cubic-bezier(0.22, 1, 0.36, 1)` | Anything arriving or settling. The default. |
| `--ease-in-out` | `cubic-bezier(0.65, 0, 0.35, 1)` | Moving between two positions, wipes, masks |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | A small overshoot for things that land or are confirmed |

Defined in `<token file>`. Under `prefers-reduced-motion: reduce`, only the duration tokens drop to 0ms; easings, keyframes and custom `--t-*` timings keep running unless the component turns them off.

## Rules

1. Start from the tokens. A choreographed piece may use its own timings: name them `--t-*` at the top of its root rule, never raw `ms` in a transition, and give it a reduced-motion block next to it.
2. JavaScript tweens go through `<helper module>`, which jumps to the end value under reduced motion.
3. Anything that changes every frame (pointer lean, counters, scrubbing, morphs) writes CSS custom properties through a ref. Framework state is never updated per frame.
4. Animate transform, translate, scale, opacity, clip-path and masks, not layout properties.
5. No infinite loops except live states that stop when the state ends.

## Reduced motion

Strategy: <token override | page-wide rule | per-component blocks | no-preference wraps | library config>.

- Token durations: nothing to do.
- Custom `transition` or `animation`: add it to the file's reduced-motion block (same kind of property), or put the entrance inside `no-preference`.
- `element.animate()` and other JS animation: guard with `<check>`.
- Anything that waits for `animationend`: call the completion path directly under reduced motion.

## Effects library

Reuse these before inventing a new effect.

| Effect | Where | How | Reduced motion |
| --- | --- | --- | --- |
| <Staggered entrance> | `<path>` | <keyframe on --dur-2, delay by --i> | <token drops to 0> |

## Helpers

- `<path to anim module>`: <exports>
- `<path to hooks>`: <useInView, useReducedMotion>
- Tests: `<setup file>` mocks `matchMedia`; `<setReducedMotion(true)>` turns reduced motion on.

## Known exceptions

Deliberate departures from the rules, so audits don't report them again.

| What | Where | Why |
| --- | --- | --- |
| <raw 70ms stagger inside calc()> | `<file>` | <reason> |

## Reduced motion gaps

Animations that still run, or misbehave, under reduced motion. Remove a row when it's fixed.

| Animation | File | Problem |
| --- | --- | --- |

## Catalogue

Timings as they stand in code. "Custom" means the value isn't a token, so it must be in the file's reduced-motion handling.

### <Area or component>

| Element | Trigger | Properties | Duration | Easing |
| --- | --- | --- | --- | --- |

## Checks

- `<lint>`, `<build>`, `<test>`
- In the browser: desktop and about 390px, reduced motion on and off, keyboard only, loops paused when scrolled away or the tab is hidden.
