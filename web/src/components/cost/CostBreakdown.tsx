import type { CostEstimate } from "../../types/api";
import { CreditAmount } from "../ui/CreditAmount";
import { useI18n } from "../../i18n";
import { fundingLabel } from "../../modelFunding";
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
  const { t } = useI18n();
  const { estimate_credits, reserved_credits, confidence } = cost;

  const isZeroCost = estimate_credits === 0 && reserved_credits === 0;
  const isEstimateOnly = reserved_credits === null;
  const hasReservation = typeof reserved_credits === "number" && reserved_credits > 0;

  if (isZeroCost) {
    return (
      <div className="mt-4 border-[2px] border-narrator-gold/35 bg-chip-gold/20 p-4">
        <p className="font-meta text-xs leading-5 tracking-[0.04em] text-ink-muted">
          {cost.funding && cost.funding !== "api"
            ? t("Included in your {plan}", { plan: t(fundingLabel(cost.funding)) })
            : t(ZERO_COST_COPY)}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 border-[2px] border-narrator-gold/35 bg-chip-gold/20 p-4">
      {estimate_credits > 0 && (
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="font-meta text-xs tracking-[0.08em] uppercase text-ink-muted">
            {t("Estimated cost")}
          </span>
          <span className="font-display text-[1.1rem] font-bold">
            <CreditAmount value={estimate_credits} approximate />
          </span>
          {hasReservation && (
            <span className="font-meta text-xs tracking-[0.04em] text-ink-muted">
              {t("Temporary hold")}: <CreditAmount value={reserved_credits!} />
            </span>
          )}
        </div>
      )}

      <p className="mt-2 font-meta text-xs leading-5 tracking-[0.04em] text-ink-muted">
        <span className="mr-2 uppercase">
          {t(CONFIDENCE_LABELS[confidence])}
        </span>
        ·{" "}
        {t(isEstimateOnly ? ESTIMATE_ONLY_HELPER : RESERVATION_HELPER)}
      </p>
    </div>
  );
}
