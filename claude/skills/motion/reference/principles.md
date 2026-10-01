# Motion principles

These are the defaults when a project's own docs don't say otherwise. Where they conflict, the project wins.

## What motion is for

Motion explains a change:
- **Origin:** a panel grows out of the button that opened it, and closes back into it.
- **Change:** a number counts to its new value, a bar fills, a line draws on.
- **Selection:** a highlight slides to the chosen day.
- **Liveness:** a listening pulse, a loading indicator, a playhead.

If it explains nothing, leave it out.

Titles and labels stay still. Only the content under a card's title enters, so the user always knows what they're looking at.

Play one entrance per view, when the view first appears. Don't replay it on every re-render or tab switch.

## Ambient motion

Ambient motion is anything that moves without a user action or a state change: idle floats, hero video loops, particle fields, drifting gradients. It's allowed when the project's art direction asks for it, with every guard below:

1. **Off under reduced motion.** Show a still frame, or a poster for video.
2. **Paused when it isn't seen.** Pause when off-screen (IntersectionObserver) and when the tab is hidden (`visibilitychange`).
3. **A visible pause or stop control** if it runs more than 5s next to other content (WCAG 2.2.2 Pause, Stop, Hide).
4. **No flashing** more than 3 times a second, and no large high-contrast flicker (WCAG 2.3.1).
5. **Cheap.** Use compositor-friendly properties only. Canvas and WebGL loops stop rendering while paused (`frameloop="demand"`, or cancel the rAF).

A loop that shows a live state (listening, loading, recording, a playhead) isn't ambient. It stops when the state ends, and under reduced motion it becomes a static indicator.

## Timing scale

Use this when the project has no duration tokens:

| Use | Duration |
| --- | --- |
| Hover, press, focus, colour change | 150–200ms |
| Small UI: toggles, chips, tooltips, menus | 200–300ms |
| Panels, dialogs, drawers, cards entering, state changes | 300–600ms |
| Choreographed morphs and sequences | 400–800ms per step |
| Deliberate reveals (a chart drawing, a hero entrance), once | 800–1500ms |

- **Distance.** Longer distances and bigger areas take longer, but not in proportion: a full-screen panel takes about 450ms, not three times a tooltip's time.
- **Exits.** Exits are 20–30% quicker than entrances. The container opens first and the content comes in after it; on close, the content leaves first.
- **Feedback.** Respond within 100ms of input. Never put a long delay in front of the first visible frame of a response.
- **Small screens.** Use slightly shorter durations: the distances are shorter.

## Easing meaning

| Curve | For | Default |
| --- | --- | --- |
| ease-out (decelerate) | Arriving, entering, settling. The default. | `cubic-bezier(0.22, 1, 0.36, 1)` |
| ease-in-out | Moving from A to B with both ends on screen; wipes and masks | `cubic-bezier(0.65, 0, 0.35, 1)` |
| ease-in (accelerate) | Leaving the screen for good | `cubic-bezier(0.55, 0, 1, 0.45)` |
| Overshoot or spring | Confirmations, pops, chips, something landing | `cubic-bezier(0.34, 1.56, 0.64, 1)` or a `linear()` spring |
| linear | Progress, scrubbing, continuous rotation, anything driven by time or the pointer | `linear` |

- Never use ease-in for an entrance: it feels sluggish.
- When a spring must stay interruptible, use the library's spring (motion/react, react-spring). In CSS, use a `linear()` spring ([recipes](recipes.md#spring-easing-with-linear)).

## Choreography

- **Stagger** each item by 30–90ms, and keep the total stagger to 300–500ms. In long lists, stagger only the first 6–8 visible items.
- **Sequence.** Each step waits for the one that leads: `delay = lag + n × step`. The text rises once the frame has mostly revealed.
- **Focus.** One focal motion at a time. Secondary motion is smaller and comes later.
- **Direction follows cause.** A panel grows from its trigger. A toast comes from where toasts live. Undo goes back the way it came.
- **Interruptible.** Reversible states (hover, open and close, toggles) use transitions, which reverse from wherever they are. One-shot events (ping, pop, draw) use keyframes. To replay a keyframe, remove its class, force a reflow, and add the class back.

## Performance

- Animate `transform`, `translate`, `scale`, `rotate`, `opacity`, `clip-path`, masks, `filter` on small areas, and registered custom properties that drive these.
- Don't animate layout: `width`, `height`, `top`, `left`, `margin`, `padding`, `font-size`, `gap`. Use a transform (with a counter-scale for content), `clip-path` insets, or FLIP instead. The one accepted exception is a small disclosure opened with grid rows (`0fr` to `1fr`) or `interpolate-size`.
- Set `will-change` just before the animation and remove it afterwards, or scope it to `:hover` or `.is-animating`. Never set it on many elements.
- **Per-frame work.** Read layout once (for example `getBoundingClientRect` on `pointerenter`), then only write custom properties. Never read layout after a write in the same frame.
- **Framework state per frame is a bug:** it re-renders 60 times a second. Use refs and CSS variables, or motion values.
- Cancel tweens on unmount, and stop loops when they're off-screen or the tab is hidden.
- Check it on a throttled CPU (DevTools, 4× slowdown).

## Accessibility

- **`prefers-reduced-motion: reduce` removes movement, not meaning.**
  - Drop travel, scaling, rotation, parallax, zoom, auto-scroll and loops.
  - Keep cross-fades, colour changes, instant state changes and the final values.
  - Content must be reachable without waiting for an animation to finish.
- **WCAG criteria:**
  - 2.2.2 Pause, Stop, Hide (A): content that moves on its own for more than 5s can be paused.
  - 2.3.1 Three Flashes (A): no more than 3 flashes a second.
  - 2.3.3 Animation from Interactions (AAA): motion triggered by interaction can be turned off. Honouring reduced motion covers it.
- **Focus.** Panels and morphs move focus into the panel on open and back to the trigger on close. Never animate the focus ring away.
- **Announce changes in text.** Use `aria-live="polite"`. Decorative motion layers get `aria-hidden="true"`.
- **Animated charts** get `role="img"` and an `aria-label` sentence that states the takeaway. Counting numbers expose their final value to screen readers from the start.
- **In-app motion setting.** If the project has one, it overrides the OS preference.
- **Smooth scrolling.** Turn `scroll-behavior: smooth` off under reduced motion.
