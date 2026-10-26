import type { ReactNode } from "react";
import { useCreditBalance } from "../../api/queries";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";
import { BottomBarPortal } from "../../layout/TopBarSlot";
import { CreditAmount } from "../ui/CreditAmount";
import { ErrorNotice } from "./ErrorNotice";

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
  error?: Error | string | null;
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
      <footer className="relative z-0 flex min-h-shell-footer flex-wrap items-center gap-x-4 gap-y-2 border-t-[2px] border-ink-black bg-bristol px-4 py-2.5 studio-desktop:py-0 studio-desktop:pl-0 studio-desktop:pr-5 xl:pr-6">
        {/* The narrator's caption box: the one gold mark on the bar. */}
        <div className="sr-only studio-desktop:not-sr-only studio-desktop:flex studio-desktop:items-center studio-desktop:self-stretch studio-desktop:bg-narrator-gold studio-desktop:px-4 studio-desktop:font-meta studio-desktop:text-[0.6875rem] studio-desktop:font-bold studio-desktop:uppercase studio-desktop:tracking-[0.12em] studio-desktop:text-ink-black">
          {t("Next:")}
        </div>
        <div className="w-full min-w-0 studio-desktop:w-auto studio-desktop:flex-1">
          <span className="font-body text-[0.8125rem] font-semibold leading-snug text-ink-black">
            {next}
          </span>
          {error ? (
            <ErrorNotice error={error} operation="approve" />
          ) : costLine && (
            <span className="ml-2 font-meta text-xs text-ink-soft">
              {costLine}
            </span>
          )}
        </div>
        <div className="flex w-full min-w-0 flex-wrap items-center justify-end gap-2 max-sm:*:grow sm:ml-auto sm:w-auto studio-desktop:gap-3">
          {secondary}
          <Button size="md" onClick={onPrimary} disabled={primaryDisabled || busy} className="flex-[1_0_10rem] sm:flex-none">
            {busy ? t("WORKING…") : primaryLabel}
          </Button>
        </div>
      </footer>
    </BottomBarPortal>
  );
}
