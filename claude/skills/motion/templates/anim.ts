/**
 * Small animation helpers. Every JS animation goes through these, so reduced motion is
 * handled in one place: tweens jump straight to their end value.
 */

export const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export type Easing = (t: number) => number;

export const ease = {
  linear: (t: number) => t,
  outCubic: (t: number) => 1 - Math.pow(1 - t, 3),
  outExpo: (t: number) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)),
  inOutCubic: (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
} satisfies Record<string, Easing>;

export type TweenOptions = {
  from?: number;
  to?: number;
  duration?: number;
  delay?: number;
  easing?: Easing;
  onUpdate: (v: number) => void;
  onComplete?: () => void;
};

/**
 * Animate a number from → to and call onUpdate(value) each frame.
 * Returns a cancel function; return it from the effect that started the tween.
 */
export function tween({
  from = 0,
  to = 1,
  duration = 1000,
  delay = 0,
  easing = ease.outCubic,
  onUpdate,
  onComplete,
}: TweenOptions): () => void {
  if (reducedMotion() || duration === 0) {
    onUpdate(to);
    onComplete?.();
    return () => {};
  }

  let raf = 0;
  let start: number | undefined;

  const frame = (now: number) => {
    start ??= now + delay;
    const t = Math.min(Math.max((now - start) / duration, 0), 1);
    onUpdate(from + (to - from) * easing(t));
    if (t < 1) raf = requestAnimationFrame(frame);
    else onComplete?.();
  };

  raf = requestAnimationFrame(frame);
  return () => cancelAnimationFrame(raf);
}

/** Count an element's text up to a number, e.g. countUp(el, 645, { suffix: " h" }). */
export function countUp(
  el: HTMLElement,
  to: number,
  {
    from = 0,
    decimals = 0,
    prefix = "",
    suffix = "",
    ...opts
  }: Omit<Partial<TweenOptions>, "onUpdate"> & { decimals?: number; prefix?: string; suffix?: string } = {}
) {
  return tween({
    from,
    to,
    ...opts,
    onUpdate: (v) => {
      el.textContent = `${prefix}${v.toFixed(decimals)}${suffix}`;
    },
  });
}

/**
 * Make the browser apply pending style changes now, so the next change
 * transitions from them instead of being batched into one jump.
 */
export function reflow(el: Element) {
  el.getBoundingClientRect();
}

/** Replay a CSS animation: drop the class, force a reflow, add it back. */
export function restartClass(el: Element, cls: string) {
  el.classList.remove(cls);
  reflow(el);
  el.classList.add(cls);
}

/** Run cb once, the first time el is at least `threshold` visible. Returns a disconnect. */
export function inView(el: Element, cb: () => void, threshold = 0.35) {
  const io = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        io.disconnect();
        cb();
      }
    },
    { threshold }
  );
  io.observe(el);
  return () => io.disconnect();
}

/** A custom property's value as the page sees it, e.g. an easing token for element.animate(). */
export function cssVar(name: string, el: Element = document.documentElement) {
  return getComputedStyle(el).getPropertyValue(name).trim();
}

/**
 * A time token in milliseconds, so JS runs on the same timings as the CSS (and gets 0 when the
 * token drops to 0ms under reduced motion). Plain values only: a calc() token comes back unresolved.
 */
export function cssMs(name: string, el: Element = document.documentElement) {
  const value = cssVar(name, el);
  const n = parseFloat(value);
  if (Number.isNaN(n)) return 0;
  return value.endsWith("ms") ? n : value.endsWith("s") ? n * 1000 : n;
}
