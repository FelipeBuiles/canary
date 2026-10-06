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
  /** Why the primary action was refused, shown beside the button that caused it. */
  error?: string | null;
}

/**
 * The one standing approval bar: every station ends the same way — what
 * happens next, what it costs, one primary button. Renders into the shell
 * footer slot on desktop and taller tablets. Phone actions scroll after
 * their review content.
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
  error,
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
      <footer className="relative z-0 flex min-h-shell-footer flex-wrap items-center gap-x-4 gap-y-2 border-t-[3px] border-ink-black bg-bristol px-4 py-3 shadow-[0_-4px_0_0_var(--color-ghost-shadow)] studio-desktop:py-0 studio-desktop:pl-0 studio-desktop:pr-6">
        <div className="hidden self-stretch bg-narrator-gold px-5 font-meta text-xs font-bold uppercase tracking-[0.1em] text-ink-black studio-desktop:flex studio-desktop:items-center">
          {t("Next:")}
        </div>
        <div className="w-full min-w-0 studio-desktop:w-auto studio-desktop:flex-1">
          <span className="mb-2 inline-flex bg-narrator-gold px-2 py-1 font-meta text-[0.62rem] font-bold uppercase leading-none tracking-[0.1em] text-ink-black studio-desktop:hidden">
            {t("Next:")}
          </span>
          <div className="font-body text-sm font-bold leading-snug text-ink-black">
            {next}
          </div>
          {error ? (
            <p role="alert" className="mt-1 font-body text-xs font-semibold leading-snug text-hero-red">
              {error}
            </p>
          ) : costLine && (
            <div className="mt-1 font-meta text-xs font-semibold tracking-[0.04em] text-ink-muted">
              {costLine}
            </div>
          )}
        </div>
        <div className="flex w-full min-w-0 flex-wrap items-center justify-end gap-2 sm:ml-auto sm:w-auto studio-desktop:gap-3">
          {secondary}
          <Button size="md" onClick={onPrimary} disabled={primaryDisabled || busy} className="flex-1 sm:flex-none">
            {busy ? t("WORKING…") : primaryLabel}
          </Button>
        </div>
      </footer>
    </BottomBarPortal>
  );
}
