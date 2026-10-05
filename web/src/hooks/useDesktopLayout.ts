import { useSyncExternalStore } from "react";

const QUERY = "(min-width: 768px) and (min-height: 512px), (min-width: 1024px)";

function subscribe(onChange: () => void) {
  const query = window.matchMedia(QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** Match studio-desktop in index.css, including short phone landscapes. */
export function useDesktopLayout() {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => true);
}
