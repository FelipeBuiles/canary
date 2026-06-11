import type { ReactNode } from "react";
import { useCreditBalance } from "../../api/queries";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";

interface ApprovalBarProps {
  /** Plain-language preview of what happens next, without the "Next:" prefix. */
  next: string;
  /** Estimated credits for the primary action (combined across auto-chains). */
  estimateCredits?: number | null;
  primaryLabel: string;
  onPrimary: () => void;
  primaryDisabled?: boolean;
  busy?: boolean;
  /** Quiet secondary action — a re-run verb or "Review N flagged". */
  secondary?: ReactNode;
  /** Optional short status/warning line shown instead of the cost line. */
  note?: string;
}

/**
 * The one standing approval bar: every station ends the same way — what
 * happens next, what it costs, one primary button — fixed to the bottom of
 * the content area (never in the sidebar).
 */
export function ApprovalBar({
  next,
  estimateCredits,
  primaryLabel,
  onPrimary,
  primaryDisabled,
  busy,
  secondary,
  note,
}: ApprovalBarProps) {
  const { t } = useI18n();
  const { data: balance } = useCreditBalance();

  const costLine = note ?? (
    estimateCredits != null && estimateCredits > 0
      ? `~${estimateCredits.toLocaleString()} ${t("credits")}${
          balance ? ` · ${t("you have")} ${balance.balance_credits.toLocaleString()}` : ""
        }`
      : null
  );

  return (
    <div className="sticky bottom-0 z-30 -mx-5 -mb-6 mt-10 md:-mx-10 md:-mb-10">
      <div className="flex min-h-[68px] items-center gap-4 border-t-[2px] border-ink-black bg-bristol px-5 py-3 md:px-10">
        <div className="min-w-0 flex-1">
          <div className="truncate font-body text-[0.9rem] font-bold leading-snug text-ink-black">
            {t("Next:")} {next}
          </div>
          {costLine && (
            <div className="mt-0.5 font-meta text-[0.58rem] tracking-[0.14em] text-ink-black/50">
              {costLine}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {secondary}
          <Button size="md" onClick={onPrimary} disabled={primaryDisabled || busy}>
            {busy ? t("WORKING…") : primaryLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
