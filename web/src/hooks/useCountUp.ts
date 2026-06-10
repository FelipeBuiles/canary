import { useEffect, useRef, useState } from "react";

const TWEEN_DURATION_MS = 600;

// Ease-out cubic interpolation between two counts at progress t ∈ [0, 1].
export function easeOutCount(from: number, to: number, t: number): number {
  const eased = 1 - Math.pow(1 - t, 3);
  return Math.round(from + (to - from) * eased);
}

// Animates a numeric display value toward `value` over ~600ms — but only on
// increases. Decreases (spend) and reduced-motion users get the new value
// instantly.
export function useCountUp(value: number): number {
  const [display, setDisplay] = useState(value);
  const displayRef = useRef(value);

  useEffect(() => {
    const from = displayRef.current;
    if (value === from) return;

    // Only increases animate; decreases (spend) and reduced-motion users
    // snap to the new value on the next frame.
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const animate = value > from && !reducedMotion;
    const start = performance.now();
    let raf = requestAnimationFrame(function tick(now: number) {
      const t = animate ? Math.min(1, (now - start) / TWEEN_DURATION_MS) : 1;
      const next = easeOutCount(from, value, t);
      displayRef.current = next;
      setDisplay(next);
      if (t < 1) raf = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return display;
}
