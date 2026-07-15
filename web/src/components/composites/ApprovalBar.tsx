import type { ReactNode } from "react";
import { useCreditBalance } from "../../api/queries";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";
import { BottomBarPortal } from "../../layout/TopBarSlot";
import { CreditAmount } from "../ui/CreditAmount";

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
 * happens next, what it costs, one primary button. Renders into the shell
 * footer slot so it spans the full content column as a true footer, below
 * the scroll area (never in the sidebar).
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
    estimateCredits != null && estimateCredits > 0 ? (
      <>
        <CreditAmount value={estimateCredits} approximate label={t("credits")} />
        {balance && (
          <span> · {t("you have")} <CreditAmount value={balance.balance_credits} showLabel={false} label={t("credits")} /></span>
        )}
      </>
    ) : null
  );

  return (
    <BottomBarPortal>
      <footer className="relative flex min-h-shell-footer flex-wrap items-center gap-x-4 gap-y-2 border-t-[3px] border-ink-black bg-bristol px-4 py-3 shadow-[0_-4px_0_0_var(--color-ghost-shadow)] md:py-0 md:pl-0 md:pr-6">
        <div className="hidden self-stretch bg-narrator-gold px-5 font-meta text-[0.54rem] font-bold uppercase tracking-[0.14em] text-ink-black md:flex md:items-center">
          {t("Next:")}
        </div>
        <div className="w-full min-w-0 md:w-auto md:flex-1">
          <div className="font-body text-[0.88rem] font-bold leading-snug text-ink-black md:truncate md:text-[0.92rem]">
            <span className="mr-2 font-meta text-[0.55rem] font-bold uppercase tracking-[0.12em] text-hero-red md:hidden">
              {t("Next:")}
            </span>
            {next}
          </div>
          {costLine && (
            <div className="mt-1 font-meta text-[0.6rem] font-semibold tracking-[0.08em] text-ink-black/65">
              {costLine}
            </div>
          )}
        </div>
        <div className="ml-auto flex shrink-0 flex-wrap items-center justify-end gap-2 md:gap-3">
          {secondary}
          <Button size="md" onClick={onPrimary} disabled={primaryDisabled || busy}>
            {busy ? t("WORKING…") : primaryLabel}
          </Button>
        </div>
      </footer>
    </BottomBarPortal>
  );
}
