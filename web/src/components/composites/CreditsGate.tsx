import { useState } from "react";
import { Button } from "../ui/Button";
import { useCreditBalance, useStageEstimate } from "../../api/queries";
import { useRecommendedPackage, useBuyCredits, packageMeetsShortfall } from "../../lib/creditsPurchase";
import { useRunAction } from "../../hooks/useRunAction";
import type { StageName } from "../../types/api";
import { CreditAmount } from "../ui/CreditAmount";
import { CostBreakdown } from "../cost/CostBreakdown";
import { ConfirmDrawer } from "./ConfirmDrawer";
import { useI18n } from "../../i18n";

interface CreditsGateProps {
  project: string;
  stage: StageName;
  stageLabel: string;
  balance: number;
  required: number;
  shortfall: number;
  reason: "persisted" | "heuristic";
}

/** Funding never authorizes work. Heuristic gates yield to the parent's Start
 * action; persisted credit failures stay here for deliberate, non-destructive recovery. */
export function CreditsGate({ project, stage, stageLabel, balance, required, reason }: CreditsGateProps) {
  const { t, language } = useI18n();
  const balanceQuery = useCreditBalance();
  const estimate = useStageEstimate(project, stage);
  const available = balanceQuery.data?.balance_credits ?? balance;
  const needed = estimate.data?.reserved_credits ?? estimate.data?.estimate_credits ?? required;
  const shortfall = Math.max(0, needed - available);
  const { pkg, isLoading: packagesLoading } = useRecommendedPackage(shortfall);
  const buyCredits = useBuyCredits();
  const { handleRun, isPending } = useRunAction();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const funded = shortfall === 0 && balanceQuery.data != null && !balanceQuery.isError;
  const unavailable = !funded || !estimate.data || estimate.isError || estimate.isFetching || isPending;
  const actionLabel = t("Resume {action}").replace("{action}", stageLabel);

  function confirmResume() {
    if (unavailable) return;
    setStartError(null);
    handleRun(project, stage, {
      rerun: false,
      actionLabel,
      onSuccess: () => setConfirmOpen(false),
      onError: (error) => {
        setStartError(error.message);
        setConfirmOpen(false);
      },
    });
  }

  return (
    <div className="flex min-h-[50vh] items-center justify-center px-4 py-8 sm:px-6">
      <div className="w-full max-w-[640px] border-[2px] border-ink-black bg-pulp-paper p-6 text-ink-black sm:p-8">
        <h2 className="break-words font-display text-[1.6rem] leading-tight tracking-[-0.02em] uppercase sm:text-[1.85rem]">
          {t("{action} is paused").replace("{action}", stageLabel)}
        </h2>
        <p className="mt-4 font-body text-base leading-6 text-ink-muted">
          {t("Adding credits does not start work. Review the estimate and confirm when you are ready.")}
        </p>
        <dl className="mt-5 grid gap-4 bg-surface-container p-4 sm:grid-cols-3">
          <div>
            <dt className="font-meta text-xs uppercase text-ink-muted">{t("Balance")}</dt>
            <dd className="mt-1 font-display text-xl tabular-nums">
              {balanceQuery.data ? <CreditAmount value={available} /> : t("Loading balance…")}
            </dd>
          </div>
          <div>
            <dt className="font-meta text-xs uppercase text-ink-muted">{t("Needed")}</dt>
            <dd className="mt-1 font-display text-xl tabular-nums"><CreditAmount value={needed} /></dd>
          </div>
          <div>
            <dt className="font-meta text-xs uppercase text-ink-muted">{t("Short by")}</dt>
            <dd className="mt-1 font-display text-xl tabular-nums"><CreditAmount value={shortfall} /></dd>
          </div>
        </dl>
        {balanceQuery.isError && (
          <div role="alert" className="mt-4 font-body text-sm">
            <p>{t("Your balance could not be loaded. Retry before resuming.")}</p>
            <Button variant="outline" className="mt-2 min-h-11" disabled={balanceQuery.isFetching} onClick={() => void balanceQuery.refetch()}>{t("Refresh balance")}</Button>
          </div>
        )}
        {estimate.isError ? (
          <div role="alert" className="mt-4 font-body text-sm">
            <p>{t("The estimate could not be loaded. No work has started.")}</p>
            <Button variant="outline" className="mt-2 min-h-11" disabled={estimate.isFetching} onClick={() => void estimate.refetch()}>{t("Retry estimate")}</Button>
          </div>
        ) : estimate.data ? <CostBreakdown cost={estimate.data} /> : (
          <p role="status" className="mt-4 font-body text-sm">{t("Loading estimate…")}</p>
        )}
        {!funded && (
          <div className="mt-5 space-y-3">
            {packagesLoading ? <p role="status" className="font-body text-sm">{t("Loading credit packages…")}</p> : pkg ? (
              <>
                <p className="font-meta text-xs uppercase text-ink-muted">{t("Recommended")}</p>
                <Button className="min-h-11 h-auto whitespace-normal py-3" disabled={buyCredits.isPending} onClick={() => buyCredits.mutate({ packageId: pkg.id })}>
                  {t("Buy")} <CreditAmount value={pkg.credits} /> · {new Intl.NumberFormat(language, { style: "currency", currency: "USD" }).format(pkg.price_cents / 100)}
                </Button>
                <p className="font-body text-sm text-ink-muted">{packageMeetsShortfall(pkg, shortfall) ? t("Covers shortfall") : t("Partial top-up")}</p>
                <p className="font-body text-sm text-ink-muted">{t("Stripe Checkout opens in a new tab. Return here after payment to resume your pending action.")}</p>
              </>
            ) : <p className="font-body text-sm">{t("Credit packages are unavailable here. Open billing to try again.")}</p>}
          </div>
        )}
        {buyCredits.error && <p role="alert" className="mt-4 font-body text-sm text-hero-red">{t("Checkout could not open. Your action is still paused. Try a package again or open billing.")} {buyCredits.error.message}</p>}
        {buyCredits.data?.url && <a href={buyCredits.data.url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex min-h-11 items-center font-body text-sm font-semibold underline underline-offset-4">{t("Open secure checkout")}</a>}
        <div className="mt-5 flex flex-wrap items-center gap-4">
          {reason === "persisted" && <Button className="min-h-11" disabled={unavailable} onClick={() => setConfirmOpen(true)}>{isPending ? t("Starting…") : actionLabel}</Button>}
          <a href="/credits" className="inline-flex min-h-11 items-center font-body text-sm font-semibold underline underline-offset-4">{t("Open billing")}</a>
        </div>
        {startError && <p role="alert" className="mt-4 font-body text-sm text-hero-red">{startError}</p>}
        <ConfirmDrawer
          open={confirmOpen}
          title={actionLabel}
          body={t("Resume this stage without discarding completed work. Unused held credits are released when the action finishes.")}
          cost={estimate.data}
          confirmLabel={actionLabel}
          busy={unavailable}
          onClose={() => setConfirmOpen(false)}
          onConfirm={confirmResume}
        />
      </div>
    </div>
  );
}
