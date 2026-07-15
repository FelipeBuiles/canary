import type { CostEstimate } from "../../types/api";
import { CreditAmount } from "../ui/CreditAmount";
import {
  CONFIDENCE_LABELS,
  ESTIMATE_ONLY_HELPER,
  RESERVATION_HELPER,
  ZERO_COST_COPY,
} from "./cost-copy";

interface CostBreakdownProps {
  cost: CostEstimate;
}

export function CostBreakdown({ cost }: CostBreakdownProps) {
  const { estimate_credits, reserved_credits, confidence } = cost;

  const isZeroCost = estimate_credits === 0 && reserved_credits === 0;
  const isEstimateOnly = reserved_credits === null;
  const hasReservation = typeof reserved_credits === "number" && reserved_credits > 0;

  if (isZeroCost) {
    return (
      <div className="mt-4 border-[2px] border-narrator-gold/35 bg-chip-gold/20 p-4">
        <p className="font-meta text-[0.72rem] leading-5 tracking-[0.06em] text-ink-black/60">
          {ZERO_COST_COPY}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 border-[2px] border-narrator-gold/35 bg-chip-gold/20 p-4">
      {estimate_credits > 0 && (
        <div className="flex items-baseline gap-3">
          <span className="font-meta text-[0.58rem] tracking-[0.16em] uppercase text-ink-black/60">
            Cost
          </span>
          <span className="font-display text-[1.1rem] font-bold">
            <CreditAmount value={estimate_credits} approximate />
          </span>
          {hasReservation && (
            <span className="font-meta text-[0.62rem] tracking-[0.06em] text-ink-black/45">
              won&apos;t exceed <CreditAmount value={reserved_credits!} showLabel={false} />
            </span>
          )}
        </div>
      )}

      <p className="mt-2 font-meta text-[0.6rem] leading-4 tracking-[0.06em] text-ink-black/45">
        <span className="mr-2 uppercase">
          {CONFIDENCE_LABELS[confidence]}
        </span>
        ·{" "}
        {isEstimateOnly ? ESTIMATE_ONLY_HELPER : RESERVATION_HELPER}
      </p>
    </div>
  );
}
