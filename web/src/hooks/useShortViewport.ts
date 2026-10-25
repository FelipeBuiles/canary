import { useSyncExternalStore } from "react";

/** Keep in sync with the short variant in index.css. */
export const SHORT_VIEWPORT_QUERY = "(height < 55rem)";

function subscribe(onChange: () => void) {
  const query = window.matchMedia(SHORT_VIEWPORT_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** Match short in index.css: laptop-height windows where full-page flows tighten. */
export function useShortViewport() {
  return useSyncExternalStore(subscribe, () => window.matchMedia(SHORT_VIEWPORT_QUERY).matches, () => false);
}
