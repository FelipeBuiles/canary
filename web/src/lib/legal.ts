/**
 * Branding + contact info for legal surfaces.
 *
 * Sourced from the public `/api/branding` endpoint (server reads env vars with
 * sensible Scenewright defaults). Falls back to the same defaults client-side
 * so the legal pages render even before the fetch resolves or in local dev.
 */

export interface Branding {
  product_name: string;
  support_email: string;
  legal_email: string;
}

export const DEFAULT_BRANDING: Branding = {
  product_name: "Scenewright",
  support_email: "hello@scenewright.ink",
  legal_email: "legal@scenewright.ink",
};

let cached: Branding | null = null;
let inflight: Promise<Branding> | null = null;

export async function fetchBranding(): Promise<Branding> {
  if (cached) return cached;
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await fetch("/api/branding");
      if (!res.ok) throw new Error(`branding ${res.status}`);
      const data = (await res.json()) as Partial<Branding>;
      cached = {
        product_name: data.product_name || DEFAULT_BRANDING.product_name,
        support_email: data.support_email || DEFAULT_BRANDING.support_email,
        legal_email: data.legal_email || DEFAULT_BRANDING.legal_email,
      };
    } catch {
      cached = DEFAULT_BRANDING;
    }
    return cached;
  })();
  return inflight;
}

export function getCachedBranding(): Branding {
  return cached ?? DEFAULT_BRANDING;
}
