import { useCallback, useSyncExternalStore } from "react";

/**
 * Cache tokens for images whose file can be rewritten at the same path.
 *
 * A token changes only when the image may have changed (a redraw landed, a
 * version was restored), never on mount. Every view of one asset — roster,
 * stage, sheet — shares its token, and leaving and returning to a room keeps
 * the URL, so the browser reuses the image it already has. Tokens start at 0
 * on each page load: a stable URL then revalidates against the server's
 * validator instead of downloading the image again.
 */
const tokens = new Map<string, number>();
const listeners = new Set<() => void>();
let version = 0;
const pending = new Set<string>();

/** Called after any token changes: an image may have been rewritten. */
export function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

const snapshot = () => version;

/**
 * Give `key` a new token. Several views reacting to one event in the same
 * commit coalesce into one change, so the image is fetched once.
 */
export function refreshImageToken(key: string) {
  if (pending.has(key)) return;
  pending.add(key);
  queueMicrotask(() => {
    pending.delete(key);
    tokens.set(key, (tokens.get(key) ?? 0) + 1);
    version += 1;
    for (const listener of listeners) listener();
  });
}

export const imageToken = (key: string) => tokens.get(key) ?? 0;

/** Read tokens and re-render when any changes. */
export function useImageTokens(): (key: string) => number {
  useSyncExternalStore(subscribe, snapshot, snapshot);
  return imageToken;
}

/** One asset's token and the action that renews it. */
export function useImageToken(key: string): [number, () => void] {
  const read = useImageTokens();
  const refresh = useCallback(() => refreshImageToken(key), [key]);
  return [read(key), refresh];
}

/** Test-only reset between cases. */
export function resetImageTokens() {
  tokens.clear();
  pending.clear();
  version += 1;
}
