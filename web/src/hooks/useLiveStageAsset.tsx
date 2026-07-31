import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Retry delays for assets that the running cast stage has not written yet.
 * Keeping the retry local to each asset avoids turning the status poll into a
 * cache-busting request for every large PNG on the page.
 */
const LIVE_STAGE_ASSET_RETRY_DELAYS_MS = [5_000, 10_000, 20_000, 30_000] as const;

export function useLiveStageAsset(src: string, timestamp: number, stageRegenerating: boolean) {
  const key = `${src}|${stageRegenerating ? "running" : "idle"}`;
  const [probeState, setProbeState] = useState(() => ({
    key,
    loaded: false,
    token: stageRegenerating ? String(timestamp) : null,
  }));
  const retryTimer = useRef<number | null>(null);
  const retryAttempt = useRef(0);
  const clearRetry = useCallback(() => {
    if (retryTimer.current !== null) {
      window.clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
  }, []);

  useEffect(() => {
    clearRetry();
    retryAttempt.current = 0;
    return clearRetry;
  }, [clearRetry, src, stageRegenerating]);

  // Derive a fresh probe during a stage/source transition instead of setting
  // state from an effect. This also keeps a parent status poll from replacing
  // the current request.
  const current = probeState.key === key
    ? probeState
    : {
        key,
        loaded: false,
        token: stageRegenerating ? String(timestamp) : null,
      };

  const handleLoad = () => {
    clearRetry();
    setProbeState({ key, loaded: true, token: null });
  };

  const handleError = () => {
    if (!stageRegenerating || retryTimer.current !== null) return;
    const delay = LIVE_STAGE_ASSET_RETRY_DELAYS_MS[
      Math.min(retryAttempt.current, LIVE_STAGE_ASSET_RETRY_DELAYS_MS.length - 1)
    ];
    retryAttempt.current += 1;
    retryTimer.current = window.setTimeout(() => {
      retryTimer.current = null;
      setProbeState({
        key,
        loaded: false,
        token: `${timestamp}-${retryAttempt.current}`,
      });
    }, delay);
  };

  const probe = stageRegenerating && !current.loaded && current.token ? (
    <img
      src={`${src}?t=${encodeURIComponent(current.token)}`}
      loading="lazy"
      width={1}
      height={1}
      className="absolute h-px w-px opacity-0"
      onLoad={handleLoad}
      onError={handleError}
      alt=""
      aria-hidden="true"
    />
  ) : null;

  return { hasImage: stageRegenerating && current.loaded, probe };
}
