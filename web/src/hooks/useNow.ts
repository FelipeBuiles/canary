import { useEffect, useState } from "react";

/**
 * A clock that ticks on an interval, for UI that ages out of date on its own.
 *
 * Reading `Date.now()` during render is impure and — worse — wouldn't re-render
 * when nothing else changes, so a stage whose stream went quiet would keep
 * looking healthy until the next event arrived.
 *
 * Pass `active: false` to stop the timer when nothing on screen needs it.
 */
export function useNow(intervalMs: number, active = true): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs, active]);

  return now;
}
