import { useSyncExternalStore } from "react";

/** Keep in sync with the studio-desktop variant in index.css. */
export const DESKTOP_LAYOUT_QUERY = "(min-width: 1024px)";

function subscribe(onChange: () => void) {
  const query = window.matchMedia(DESKTOP_LAYOUT_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** Match studio-desktop in index.css. */
export function useDesktopLayout() {
  return useSyncExternalStore(subscribe, () => window.matchMedia(DESKTOP_LAYOUT_QUERY).matches, () => true);
}
