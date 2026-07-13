import type { CostEstimate } from "../../types/api";

/** Returns "~N credits" string or null for zero cost — the one phrasing. */
export function costInlineText(cost: CostEstimate | null | undefined): string | null {
  if (!cost || cost.estimate_credits === 0) return null;
  return `~${cost.estimate_credits.toLocaleString()} credits`;
}
