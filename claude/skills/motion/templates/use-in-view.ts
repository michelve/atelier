import { useEffect, useRef, type RefObject } from "react";
import { inView } from "./anim"; // wherever the project keeps anim.ts

/**
 * Run `onEnter` once, the first time `ref` is at least `threshold` visible.
 * `onEnter` may return a cleanup (e.g. a tween's cancel); it runs on unmount.
 */
export function useInView(ref: RefObject<Element | null>, onEnter: () => void | (() => void), threshold = 0.35) {
  const cb = useRef(onEnter);
  cb.current = onEnter;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cleanup: void | (() => void);
    const stop = inView(el, () => (cleanup = cb.current()), threshold);
    return () => {
      stop();
      cleanup?.();
    };
  }, [ref, threshold]);
}
