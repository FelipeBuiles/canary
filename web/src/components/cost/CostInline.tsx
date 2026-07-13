import type { CostEstimate } from "../../types/api";

interface CostInlineProps {
  cost: CostEstimate | null | undefined;
}

/** Compact CTA fragment. Returns null for zero-cost estimates. */
export function CostInline({ cost }: CostInlineProps) {
  if (!cost || cost.estimate_credits === 0) return null;
  return <>~{cost.estimate_credits.toLocaleString()} credits</>;
}
