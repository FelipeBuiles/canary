import { operatorFetch, type OperatorConnection } from "./operator";
import type { MarketingSnapshot, MarketingTransition } from "../types/marketing";

const BASE = "/api/ops/backoffice/marketing";

export function fetchMarketingSnapshot(connection: OperatorConnection, signal?: AbortSignal) {
  return operatorFetch<MarketingSnapshot>(`${BASE}/snapshot`, connection, { signal });
}

export function transitionMarketingDraft(
  connection: OperatorConnection,
  input: { path: string; revision: string; transition: MarketingTransition },
  signal?: AbortSignal,
) {
  return operatorFetch<MarketingSnapshot>(`${BASE}/transition`, connection, {
    method: "POST", body: JSON.stringify(input), signal,
  });
}

export function localMarketingAvailable(baseUrl: string, hostname = window.location.hostname): boolean {
  const local = new Set(["localhost", "127.0.0.1", "[::1]"]);
  if (!import.meta.env.DEV || !local.has(hostname)) return false;
  try {
    const target = new URL(baseUrl || window.location.origin);
    return local.has(target.hostname) && ["http:", "https:"].includes(target.protocol);
  } catch { return false; }
}
