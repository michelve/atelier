# Motion recipes

Reuse one of these before inventing an effect. The code uses this skill's default names (`--dur-1/2/3`, `--ease-out`, `--ease-in-out`, `--ease-spring`, local `--t-*`); swap in the project's own tokens, prefix, layers and class naming. JS helpers (`tween`, `ease`, `countUp`, `reducedMotion`, `reflow`, `restartClass`, `inView`, `cssMs`, `cssVar`) are in [templates/anim.ts](../templates/anim.ts) if the project has none.

Every recipe below says:
- what the effect explains
- how it's built
- how it behaves under reduced motion
- the pitfalls

**Contents**
- **Entrances:** [Staggered entrance](#staggered-entrance) · [Text rise](#text-rise) · [Fade-wave reveal](#fade-wave-reveal) · [Frame unwipe](#frame-unwipe) · [Scroll-driven reveal](#scroll-driven-reveal)
- **Opening and closing:** [Clip-path morph from the trigger](#clip-path-morph-from-the-trigger) · [Dialog and popover entry and exit](#dialog-and-popover-entry-and-exit) · [Disclosure height](#disclosure-height) · [View Transitions](#view-transitions) · [FLIP layout change](#flip-layout-change)
- **Pointer:** [Pointer lean with depth](#pointer-lean-with-depth) · [Pointer-proximity field](#pointer-proximity-field)
- **Feedback and state:** [One-shot replay: ping, pop, bump](#one-shot-replay-ping-pop-bump) · [Check draw](#check-draw) · [State cross-fade with registered colours](#state-cross-fade-with-registered-colours)
- **Values and data:** [Tweened number or bar](#tweened-number-or-bar) · [Chart draw and scrub](#chart-draw-and-scrub) · [Odometer digits](#odometer-digits)
- **Easing:** [Spring easing with linear()](#spring-easing-with-linear)

## Staggered entrance

**Explains:** the items of a list or grid arrived together, in reading order.

```css
.list { --t-stagger: 70ms; }

.list > * {
  animation: list-rise-in var(--dur-2) var(--ease-out) both;
  animation-delay: calc(min(var(--i, 0), 8) * var(--t-stagger));
}

@keyframes list-rise-in {
  from { opacity: 0; translate: 0 1rem; }
}

@media (prefers-reduced-motion: reduce) {
  .list > * { animation-delay: 0ms; }
}
```

Set `--i` per item (`style={{ "--i": index }}`, or `:nth-child` rules).

**Reduced motion:** the duration token drops to 0ms, but the delay doesn't, so the reduce block clears it. Without that, items still pop in one by one.

**Pitfalls:**
- Cap the index (`min(var(--i), 8)`) so long lists don't take seconds.
- Use `both` as the fill mode, so items stay hidden during their delay and keep their end state.
- Trigger the entrance on mount or in-view, never on data refresh.

## Text rise

**Explains:** the content arrived after its container. It's the second beat of an entrance.

```css
.card {
  --t-text-in: 1000ms;
  --t-text-lag: 400ms;   /* waits for what leads: the art, a ring, a photo */
  --t-text-step: 140ms;
}

@media (prefers-reduced-motion: no-preference) {
  .card__body > * {
    transition:
      opacity var(--t-text-in) var(--ease-out) calc(var(--t-text-lag) + var(--n, 0) * var(--t-text-step)),
      translate var(--t-text-in) var(--ease-out) calc(var(--t-text-lag) + var(--n, 0) * var(--t-text-step));
  }
  .card:not(.is-shown) .card__body > * { opacity: 0; translate: 0 0.25rem; }
}
```

Set `--n` for the 2nd, 3rd, … child. Add `.is-shown` once the card is in view (`useInView` or `inView`).

**Reduced motion:** the whole entrance lives in `no-preference`, so under reduce the text is simply there.

**Pitfalls:**
- Keep the rise small: 4px, not 20px.
- The card title never animates in.
- An element that also has its own hover transitions (a button) must list them in the same `transition`, because this one replaces them.

## Fade-wave reveal

**Explains:** artwork appearing from its light source. A soft edge sweeps across it.

```css
/* Registered so it can be transitioned; outside any other at-rule. The initial value shows the art in full. */
@property --reveal {
  syntax: "<percentage>";
  inherits: false;
  initial-value: 140%;
}

.art { --t-reveal: 2400ms; --t-reveal-lag: 300ms; }

@media (prefers-reduced-motion: no-preference) {
  .art {
    mask-image: linear-gradient(to top left, #000 calc(var(--reveal) - 40%), transparent var(--reveal));
    transition: --reveal var(--t-reveal) var(--ease-in-out) var(--t-reveal-lag);
  }
  .card:not(.is-shown) .art { --reveal: 0%; }
}
```

**Reduced motion:** the entrance lives in `no-preference`, and the initial value shows everything.

**Pitfalls:**
- If two files register the same `@property`, keep them identical: the last registration wins.
- The 40% gap is the width of the soft edge.
- `#000` in a mask only means "opaque", so a no-hex lint rule should exempt mask properties.

## Frame unwipe

**Explains:** layered outlines appearing one after another, nearest the source first.

```css
.frames > span { --t-frame: 1100ms; --t-frame-lag: 700ms; --t-frame-step: 280ms; }

@media (prefers-reduced-motion: no-preference) {
  .frames > span {
    clip-path: inset(0);
    transition:
      clip-path var(--t-frame) var(--ease-in-out) calc(var(--t-frame-lag) + (var(--d) - 1) * var(--t-frame-step)),
      opacity var(--t-frame) var(--ease-out) calc(var(--t-frame-lag) + (var(--d) - 1) * var(--t-frame-step));
  }
  .card:not(.is-shown) .frames > span { clip-path: inset(100% 0 0 100%); opacity: 0; }
}
```

`--d` is each frame's distance from the source (1, 2, 3 …). `inset(100% 0 0 100%)` hides the frame towards its bottom-left corner; pick the corner nearest the source.

**Reduced motion:** the entrance lives in `no-preference`.

## Scroll-driven reveal

**Explains:** a section arriving as it scrolls into view, tied to the scroll position.

```css
@keyframes section-reveal {
  from { opacity: 0; translate: 0 2rem; }
}

@supports (animation-timeline: view()) {
  @media (prefers-reduced-motion: no-preference) {
    .reveal {
      animation: section-reveal linear both;
      animation-timeline: view();            /* after the shorthand, which resets it */
      animation-range: entry 10% cover 30%;
    }
  }
}
```

Where `animation-timeline` isn't supported, fall back to an in-view class: `inView(el, () => el.classList.add("is-shown"))` plus a `.reveal:not(.is-shown)` start state inside `@supports not (animation-timeline: view())`.

**Reduced motion:** everything sits in `no-preference`.

**Pitfalls:**
- The scroll is the easing, so the timing function is `linear`.
- Don't scrub text people are trying to read.
- Pinning and scroll-jacking stay off under reduce.

## Clip-path morph from the trigger

**Explains:** a panel grew out of the button that opened it, and goes back into it.

```css
.panel {
  --t-open: 460ms;
  --t-close: 380ms;              /* closing is quicker */
  --t-content-in: 240ms;
  --t-content-out: 100ms;
  --t-content-lag: 170ms;
  --morph: cubic-bezier(0.65, 0, 0.2, 1);
  clip-path: inset(var(--from-t, 0) var(--from-r, 0) var(--from-b, 0) var(--from-l, 0) round var(--r-pill));
  transition: clip-path var(--t-close) var(--morph);
}

.panel.is-open {
  clip-path: inset(0 round var(--r-md));
  transition: clip-path var(--t-open) var(--morph);
}

/* once open, drop the clip so the shadow can show */
.panel.is-settled { clip-path: none; box-shadow: var(--shadow-menu); }

/* content leaves first and arrives last */
.panel__content > * {
  opacity: 0;
  translate: 0 0.5rem;
  transition: opacity var(--t-content-out) var(--ease-out), translate var(--t-content-out) var(--ease-out);
}
.panel.is-open .panel__content > * {
  opacity: 1;
  translate: 0 0;
  transition: opacity var(--t-content-in) var(--ease-out), translate var(--t-content-in) var(--ease-out);
  transition-delay: var(--t-content-lag);
}

@media (prefers-reduced-motion: reduce) {
  .panel, .panel * { transition-duration: 0ms !important; transition-delay: 0ms !important; }
}
```

```ts
// Where the trigger sits inside the panel, as clip-path insets.
function measureFrom(panel: HTMLElement, trigger: HTMLElement) {
  const p = panel.getBoundingClientRect();
  const t = trigger.getBoundingClientRect();
  panel.style.setProperty("--from-t", `${t.top - p.top}px`);
  panel.style.setProperty("--from-r", `${p.right - t.right}px`);
  panel.style.setProperty("--from-b", `${p.bottom - t.bottom}px`);
  panel.style.setProperty("--from-l", `${t.left - p.left}px`);
}

function open(panel: HTMLElement, trigger: HTMLElement) {
  measureFrom(panel, trigger);   // the panel is laid out but clipped to the trigger
  reflow(panel);                 // commit the start clip before changing it
  panel.classList.add("is-open");
  const settle = () => panel.classList.add("is-settled");
  if (reducedMotion()) settle();  // no transitionend at 0ms
  else panel.addEventListener("transitionend", settle, { once: true });
  panel.querySelector<HTMLElement>("[autofocus], button, [href], input")?.focus();
}
```

**Reduced motion:** the reduce block zeroes every duration and delay, including the content's. The panel just appears.

**Pitfalls:**
- `clip-path` also clips the shadow, which is why `.is-settled` drops the clip.
- Remove `.is-settled` before closing, and re-measure on resize.
- Match `round` to the trigger's radius.
- Return focus to the trigger on close.
- On a `<dialog>`, reset the browser's margins and max sizes.
- Keep the panel's `transform` and `translate` separate, and check the CSS minifier doesn't merge them.

## Dialog and popover entry and exit

**Explains:** a dialog or popover arrived, and leaves the same way. It works with `display: none` toggling and the top layer.

```css
dialog,
[popover] {
  opacity: 1;
  translate: 0 0;
  transition:
    opacity var(--dur-2) var(--ease-out),
    translate var(--dur-2) var(--ease-out),
    display var(--dur-2) allow-discrete,
    overlay var(--dur-2) allow-discrete;
}

dialog:not([open]),
[popover]:not(:popover-open) {
  opacity: 0;
  translate: 0 0.5rem;
}

/* the state to animate from when it first renders; after the open rules */
@starting-style {
  dialog[open],
  [popover]:popover-open {
    opacity: 0;
    translate: 0 0.5rem;
  }
}

dialog::backdrop {
  background: var(--c-scrim);
  transition: opacity var(--dur-2) var(--ease-out), display var(--dur-2) allow-discrete, overlay var(--dur-2) allow-discrete;
}
@starting-style { dialog[open]::backdrop { opacity: 0; } }
```

**Reduced motion:** the duration tokens drop to 0ms, so it opens and closes instantly.

**Pitfalls:**
- `@starting-style` must come after the rules it overrides, with the same specificity.
- Browsers without `overlay` or `allow-discrete` just skip the exit animation, which is fine.
- Don't animate `display` without `allow-discrete`.

## Disclosure height

**Explains:** a section expanding in place. It's the one layout animation that's accepted, and only for small disclosures.

```css
.disclosure {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows var(--dur-2) var(--ease-out);
}
.disclosure.is-open { grid-template-rows: 1fr; }
.disclosure > .disclosure__inner { overflow: hidden; min-height: 0; }
```

In browsers that support it, `interpolate-size: allow-keywords` on `:root` also lets `height: auto` transition. Use it only on small panels.

**Reduced motion:** the duration token drops to 0ms.

**Pitfalls:**
- The scanner flags `height` transitions but not grid rows. List a deliberate `height: auto` transition as a known exception in the project's doc.
- Don't use this for large content or whole pages.

## View Transitions

**Explains:** a shared element carrying across a state change (a list item becomes the detail view), or a cross-fade between two whole states.

```ts
export function withTransition(change: () => void) {
  if (!document.startViewTransition || reducedMotion()) return change();
  document.startViewTransition(change);        // in React: () => flushSync(change)
}
```

```css
.card[data-id="42"] { view-transition-name: card-42; }   /* unique on the page at any moment */

::view-transition-old(root),
::view-transition-new(root) {
  animation-duration: var(--dur-2);
  animation-timing-function: var(--ease-out);
}

@media (prefers-reduced-motion: reduce) {
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) { animation: none; }
}
```

For page navigations, add `@view-transition { navigation: auto; }` to both pages (same-origin, in browsers that support it).

**Reduced motion:** skip `startViewTransition`, or turn the pseudo-element animations off.

**Pitfalls:**
- The page doesn't respond to input during the transition, so keep it short.
- Two elements with the same `view-transition-name` abort the transition.
- Text in a shared element that changes size can stretch. Give the text its own name, or use `object-fit`-style containers.

## FLIP layout change

**Explains:** an element moved to its new place (a list reorder, a card changing size) instead of jumping there.

```ts
// First, Last, Invert, Play: measure, change, then animate from the old box to the new one with a transform.
export function flip(el: HTMLElement, change: () => void) {
  const first = el.getBoundingClientRect();
  change();
  const last = el.getBoundingClientRect();
  const dx = first.left - last.left;
  const dy = first.top - last.top;
  const sx = first.width / last.width;
  const sy = first.height / last.height;
  if (reducedMotion() || (!dx && !dy && sx === 1 && sy === 1)) return;
  el.animate(
    [
      { transformOrigin: "top left", transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` },
      { transformOrigin: "top left", transform: "none" },
    ],
    { duration: cssMs("--dur-2", el), easing: cssVar("--ease-out", el) || "ease-out" }
  );
}
```

With motion/react, use `layout` or `layoutId`. With GSAP, use the Flip plugin.

**Reduced motion:** the guard skips the animation. The layout change still happens.

**Pitfalls:**
- Scaling distorts text and borders. Counter-scale the children, or use `layout="position"` in motion/react.
- Measure every element before changing any of them.

## Pointer lean with depth

**Explains:** layered artwork has depth. It drifts after the pointer rather than tracking it.

```css
.layers { --lean: 0.125rem; --lx: 0; --ly: 0; --t-lean: 1200ms; }

.layers > * {
  transform: translate(calc(var(--lx) * var(--d) * var(--lean)), calc(var(--ly) * var(--d) * var(--lean)));
  transition: transform var(--t-lean) var(--ease-out);
}
```

```ts
// Written as CSS variables through a ref, so the framework never re-renders on pointer moves.
const lean = (x: number, y: number) => {
  layers.style.setProperty("--lx", String(x));
  layers.style.setProperty("--ly", String(y));
};
const onPointerMove = (e: PointerEvent) => {
  if (reducedMotion() || e.pointerType !== "mouse") return;
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  lean((e.clientX - r.left) / r.width - 0.5, (e.clientY - r.top) / r.height - 0.5);
};
const onPointerLeave = () => lean(0, 0);
```

`--d` is each layer's depth: farther layers move more, and a negative value leans the front layer the other way.

**Reduced motion:** the handler returns early, so the transition never has anything to move. The scanner can't see that, so say so when an audit flags it.

**Pitfalls:**
- A long `--t-lean` (about 1s) makes it drift. A short one makes it twitch.
- For many elements, measure on `pointerenter`, not on every move.

## Pointer-proximity field

**Explains:** the pointer's position over a dot or halftone field. The dots swell near it.

```css
.field { --px: 9; --py: 9; --t-swell: 600ms; }    /* 9: far away, nothing swells */

.field circle {
  --near: max(0, 0.25 - hypot(var(--px) - var(--x, 0), var(--py) - var(--y, 0)));
  transform-box: fill-box;
  transform-origin: center;
  scale: calc(1 + var(--near) * 1.6);
  transition: scale var(--t-swell) var(--ease-out);
}
```

```ts
// Once: each dot's own position, 0–1 across the field.
field.querySelectorAll("circle").forEach((dot) => {
  dot.style.setProperty("--x", String(Number(dot.getAttribute("cx")) / SIZE));
  dot.style.setProperty("--y", String(Number(dot.getAttribute("cy")) / SIZE));
});
// On pointermove (after the reducedMotion() guard): the pointer's position in the same units.
field.style.setProperty("--px", String((e.clientX - r.left) / r.width));
field.style.setProperty("--py", String((e.clientY - r.top) / r.height));
```

**Reduced motion:** the handler returns early, so `--px` and `--py` stay far away.

**Pitfalls:**
- `hypot()` needs a current browser.
- Keep it under a few hundred elements. Beyond that, use canvas.
- Add a ripple by replaying a keyframe whose delay comes from `--x` and `--y` (see the next recipe).

## One-shot replay: ping, pop, bump

**Explains:** "that worked": something was added, confirmed or updated.

```ts
// Drop the class, force a reflow, add it back: the animation plays again.
export function restartClass(el: Element, cls: string) {
  el.classList.remove(cls);
  void el.getBoundingClientRect();
  el.classList.add(cls);
}
```

```css
.chip { --t-pop: 420ms; }

@media (prefers-reduced-motion: no-preference) {
  .chip.is-popped { animation: chip-pop var(--t-pop) var(--ease-spring); }
}

@keyframes chip-pop {
  40% { scale: 1.12; }   /* only the peak: it starts and ends at the element's own value */
}
```

**Reduced motion:** the rule only exists under `no-preference`, so the state still changes, just without the pop.

**Pitfalls:**
- A framework that owns `className` wipes a transient class on the next render. Call `restartClass` on a ref. Persistent state goes in `data-state`.
- Give keyframes a component prefix; global names collide.
- If JS waits for `animationend`, call the completion path directly under reduce.

## Check draw

**Explains:** a confirmation arriving: the tick draws on.

```tsx
<svg viewBox="0 0 24 24" aria-hidden="true">
  <path className="check" pathLength={1} d="M5 12.5l4.5 4.5L19 7.5" />
</svg>
```

```css
.check {
  fill: none;
  stroke: currentColor;
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  transition: stroke-dashoffset var(--dur-2) var(--ease-out);
}
[data-checked="true"] .check { stroke-dashoffset: 0; }
```

`pathLength={1}` sets the path's length to 1, so one dash rule works for any path.

**Reduced motion:** the duration token drops to 0ms; the tick still appears.

**Pitfalls:**
- As a keyframe, define `@keyframes check-draw` once in a shared file, not once per component.
- Use `animation-fill-mode: both`.

## State cross-fade with registered colours

**Explains:** a component changed state (idle, listening, thinking, speaking), and its whole look blends from one state to the next.

```css
@property --orb-core { syntax: "<color>"; inherits: true; initial-value: transparent; }
@property --orb-glow { syntax: "<color>"; inherits: true; initial-value: transparent; }

.orb {
  --t-morph: 700ms;
  background: radial-gradient(circle, var(--orb-core), var(--orb-glow) 60%, transparent 70%);
  transition: --orb-core var(--t-morph) var(--ease-in-out), --orb-glow var(--t-morph) var(--ease-in-out);
}
.orb[data-state="idle"]      { --orb-core: var(--c-surface); --orb-glow: var(--c-soft); }
.orb[data-state="listening"] { --orb-core: var(--c-live);    --orb-glow: var(--c-live-soft); }
```

Gradients can't transition, but registered colours inside them can.

**Reduced motion:** colour cross-fades are fine under reduce, so keep them. Zero any movement or loops the states add (`animation: none`).

**Pitfalls:**
- Unregistered custom properties jump; register every one you transition.
- Put the state in `data-state`, not in a class a framework rewrites.

## Tweened number or bar

**Explains:** a value arrived at its current level.

```ts
useInView(ref, () =>
  tween({
    duration: cssMs("--dur-3"),
    easing: ease.outCubic,
    onUpdate: (v) => {
      bar.style.setProperty("--fill", String(v * share));       // share: 0–1
      label.textContent = `${Math.round(v * share * 100)}%`;
    },
  })
); // tween returns its cancel function; useInView runs it on unmount
```

```css
.bar__fill { scale: var(--fill, 0) 1; transform-origin: left; }
.bar__label { font-variant-numeric: tabular-nums; }
```

**Reduced motion:** `tween()` calls `onUpdate(to)` at once.

**Pitfalls:**
- Screen readers must get the final value from the start: set `aria-valuenow` to the final value, or add visually-hidden final text, and `aria-hidden` on the counting text.
- Use tabular numbers so the width doesn't jitter.
- Scale the fill, don't animate its `width`.

## Chart draw and scrub

**Explains:** the data unfolds in the order it happened. A marker then follows the pointer.

```css
.chart__plot { clip-path: inset(-10% calc(100% - var(--draw, 0) * 100%) -10% -1%); }

/* The track spans the plot, so a percentage translate is a percentage of the plot. */
.chart__track { position: absolute; inset: 0; translate: calc(var(--mx, 50) * 1%) 0; }
.chart__marker { translate: -50% calc(var(--my, 50) * 1%); }

/* Settle back when the pointer leaves; no transition while scrubbing. */
.chart:not(.is-scrubbing) .chart__track { transition: translate var(--dur-2) var(--ease-out); }
```

```ts
useInView(chartRef, () => tween({ duration: cssMs("--dur-3"), easing: ease.inOutCubic, onUpdate: (v) => svg.style.setProperty("--draw", String(v)) }));
```

```html
<figure role="img" aria-label="Mobility rose from 40% to 72% over six weeks, peaking in week 5.">…</figure>
```

**Reduced motion:** the tween jumps to 1. The scrub follows the pointer directly, because it's user-driven.

**Pitfalls:**
- Don't move the marker with `left` or `top`; that's the layout trap.
- Write the scrub position with `setProperty`, never with state.

## Odometer digits

**Explains:** a number rolled to its value, like a counter.

```tsx
// Each digit is a strip [blank, 0–9, 0–9] inside a one-digit window; the ones digit takes an extra lap so it lands last.
const CELLS = ["", ..."01234567890123456789"];
<span className="odo" aria-hidden="true">
  {digits.map((d, i) => (
    <span key={i} className="odo__digit">
      <span className="odo__strip" style={{ "--i": i, "--cells": CELLS.length, "--to": rolled ? 1 + d + (i === digits.length - 1 ? 10 : 0) : 0 } as CSSProperties}>
        {CELLS.map((c, k) => <span key={k}>{c}</span>)}
      </span>
    </span>
  ))}
</span>
<span className="visually-hidden">{value}</span>
```

```css
.odo { --t-roll: 1500ms; --t-roll-step: 450ms; }
.odo__digit { display: inline-block; height: 1lh; overflow: hidden; }
.odo__strip {
  display: flex;
  flex-direction: column;
  translate: 0 calc(var(--to) * -100% / var(--cells));
  transition: translate calc(var(--t-roll) + var(--i) * var(--t-roll-step)) var(--ease-out);
}
@media (prefers-reduced-motion: reduce) { .odo__strip { transition: none; } }
```

**Reduced motion:** the reduce block removes the transition, so the digits land at once. The `calc()` duration is a custom timing; tokens wouldn't cover it.

## Spring easing with linear()

**Explains:** landing with a natural overshoot and settle, without a JS spring.

```css
:root {
  --ease-spring-soft: cubic-bezier(0.34, 1.56, 0.64, 1);   /* fallback */
}
@supports (transition-timing-function: linear(0, 1)) {
  :root {
    /* a spring sampled as points; generate your own with a linear() easing generator */
    --ease-spring-soft: linear(0, 0.009, 0.035 2.1%, 0.141, 0.281 6.7%, 0.723 12.9%, 0.938 16.7%, 1.017, 1.077, 1.121, 1.149 24.3%, 1.159, 1.163, 1.161, 1.154 29.9%, 1.129 32.8%, 1.051 39.6%, 1.017 43.1%, 0.991, 0.977 51%, 0.974 53.8%, 0.975 57.1%, 0.997 69.8%, 1.003 76.9%, 1.004 83.8%, 1);
  }
}
```

Make the duration match the time the spring takes to settle (usually 600–900ms).

**Reduced motion:** it's an easing, so it goes wherever the duration goes.

**Pitfalls:**
- A CSS spring restarts from zero velocity when interrupted. For springs that are dragged or reversed often, use a JS spring (motion/react `type: "spring"`, react-spring).
