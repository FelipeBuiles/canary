const RELOAD_MARKER = "scenewright:chunk-reload-at";
const RELOAD_COOLDOWN_MS = 60_000;

interface ChunkLoadRecoveryOptions {
  target?: EventTarget;
  storage?: Pick<Storage, "getItem" | "setItem">;
  reload?: () => void;
  now?: () => number;
}

/**
 * Recover when an open tab requests a hashed Vite chunk removed by a deploy.
 * The cooldown prevents a bad deployment or proxy cache from causing a reload
 * loop when refreshing cannot make the requested module available.
 */
export function installChunkLoadRecovery({
  target = window,
  storage = window.sessionStorage,
  reload = () => window.location.reload(),
  now = Date.now,
}: ChunkLoadRecoveryOptions = {}): void {
  target.addEventListener("vite:preloadError", (event) => {
    event.preventDefault();

    const currentTime = now();
    const previousValue = storage.getItem(RELOAD_MARKER);
    if (previousValue !== null) {
      const previousTime = Number(previousValue);
      if (Number.isFinite(previousTime) && currentTime - previousTime < RELOAD_COOLDOWN_MS) {
        return;
      }
    }

    storage.setItem(RELOAD_MARKER, String(currentTime));
    reload();
  });
}
