import { useEffect, useState } from "react";

let inflight: Promise<string> | null = null;

/**
 * Cloudflare Turnstile site key, from the server's `CANARY_TURNSTILE_SITE_KEY`
 * setting; empty where the signup bot check is not configured.
 */
export function turnstileSiteKey(): Promise<string> {
  inflight ??= (async () => {
    try {
      const response = await fetch("/api/public-config");
      if (!response.ok) throw new Error(`public-config ${response.status}`);
      const data = (await response.json()) as { turnstile_site_key?: unknown };
      return typeof data.turnstile_site_key === "string" ? data.turnstile_site_key.trim() : "";
    } catch {
      // Ask again on the next call; sign-in stays usable where no check is enforced.
      inflight = null;
      return "";
    }
  })();
  return inflight;
}

/** The site key once known; empty until then and where no bot check is configured. */
export function useTurnstileSiteKey(): string {
  const [siteKey, setSiteKey] = useState("");
  useEffect(() => {
    let active = true;
    void turnstileSiteKey().then((key) => { if (active) setSiteKey(key); });
    return () => { active = false; };
  }, []);
  return siteKey;
}
