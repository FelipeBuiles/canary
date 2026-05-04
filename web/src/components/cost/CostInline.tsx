import type { CostEstimate } from "../../types/api";

interface CostInlineProps {
  cost: CostEstimate | null | undefined;
}

/** Compact CTA fragment. Returns null for zero-cost estimates. */
export function CostInline({ cost }: CostInlineProps) {
  if (!cost || cost.estimate_credits === 0) return null;
  return <>{cost.estimate_credits.toLocaleString()} credits</>;
}

/** Returns "Est. N credits" string or null for zero cost. */
export function costInlineText(cost: CostEstimate | null | undefined): string | null {
  if (!cost || cost.estimate_credits === 0) return null;
  return `Est. ${cost.estimate_credits.toLocaleString()} credits`;
}
