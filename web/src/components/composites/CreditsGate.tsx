import { useEffect, useRef } from "react";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { cn } from "../../lib/cn";
import { useCreditBalance } from "../../api/queries";
import {
  useRecommendedPackage,
  useBuyCredits,
} from "../../lib/creditsPurchase";
import { useRunAction } from "../../hooks/useRunAction";
import type { StageName } from "../../types/api";

interface CreditsGateProps {
  project: string;
  stage: StageName;
  stageLabel: string;
  balance: number;
  required: number;
  shortfall: number;
  reason: "persisted" | "heuristic";
}

/**
 * In-room panel shown when a stage is blocked on credits, replacing the
 * misleading "waiting for pipeline" placeholder. Shows the balance/shortfall,
 * a recommended package, and a Buy CTA. Once the live balance clears the
 * requirement, it auto-starts the stage (once).
 */
export function CreditsGate({
  project,
  stage,
  stageLabel,
  balance,
  required,
  shortfall,
  reason,
}: CreditsGateProps) {
  const { data: liveBalance } = useCreditBalance();
  const { pkg, packages, isLoading: packagesLoading } = useRecommendedPackage(shortfall);
  const buyCredits = useBuyCredits();
  const { handleRun } = useRunAction();
  const ranOnce = useRef(false);

  // Auto-start the stage once the user has topped up. The optimistic write is
  // suppressed on low credits (queries.ts), so the user sees the genuine
  // running state only once GET /status confirms it — at which point this
  // panel unmounts.
  useEffect(() => {
    if (ranOnce.current) return;
    const live = liveBalance?.balance_credits;
    if (typeof live === "number" && live >= required && required > 0) {
      ranOnce.current = true;
      handleRun(project, stage);
    }
  }, [liveBalance, required, project, stage, handleRun]);

  const subhead =
    reason === "persisted"
      ? "You ran out of credits mid-stage. Buy more to resume."
      : "You don't have enough credits to start this stage yet.";

  const autoRunNote =
    reason === "persisted"
      ? "After buying, this stage resumes automatically."
      : "After buying, this stage starts automatically.";

  return (
    <div className="flex min-h-[50vh] items-center justify-center px-6">
      <div className="w-full max-w-[640px] border-x-[2px] border-t-[2px] border-ink-black bg-pulp-paper text-ink-black sm:border-[2px]"
           style={{ borderTop: "4px solid var(--color-narrator-gold)" }}>
        <div className="px-6 pt-5 pb-6 sm:px-8">
          <div className="mb-2 inline-flex items-center gap-2 border-[1.5px] border-narrator-gold px-2 py-0.5 font-meta text-[0.58rem] tracking-[0.2em] uppercase text-narrator-gold">
            <Icon name="alert" size={11} />
            Add credits
          </div>
          <h2 className="font-display text-[1.6rem] leading-[0.95] tracking-[-0.02em] uppercase sm:text-[1.85rem]">
            {stageLabel} needs credits
          </h2>
          <p className="mt-4 text-[0.92rem] leading-6 text-ink-fade">
            {subhead}
          </p>

          {/* Balance / Needed / Shortfall */}
          <div
            className="mt-4 grid grid-cols-3 gap-4 bg-bristol p-4"
            style={{ borderLeft: "3px solid var(--color-narrator-gold)" }}
          >
            <div>
              <div className="font-meta text-[0.54rem] tracking-[0.16em] uppercase text-ink-black/50">
                Balance
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums">
                {balance.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="font-meta text-[0.54rem] tracking-[0.16em] uppercase text-ink-black/50">
                Needed
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums">
                ~{required.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="font-meta text-[0.54rem] tracking-[0.16em] uppercase text-narrator-gold">
                Short by
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums text-narrator-gold">
                {shortfall.toLocaleString()}
              </div>
            </div>
          </div>

          {/* Recommended package */}
          {packagesLoading ? null : pkg ? (
            <div className="mt-5">
              <div className="font-meta text-[0.6rem] font-bold tracking-[0.16em] uppercase text-ink-black/45">
                Recommended
              </div>
              <button
                type="button"
                disabled={buyCredits.isPending}
                onClick={() => buyCredits.mutate({ packageId: pkg.id })}
                className={cn(
                  "mt-2 flex w-full items-center justify-between gap-3 border-[2px] bg-bristol px-4 py-3 text-left transition-colors hover:bg-pulp-paper disabled:cursor-not-allowed disabled:opacity-50",
                  "border-hero-red",
                )}
              >
                <div>
                  <div className="font-display text-[1.1rem] font-black tabular-nums">
                    {pkg.credits.toLocaleString()} credits
                  </div>
                  <div className="font-meta text-[0.56rem] tracking-[0.14em] uppercase text-ink-black/50">
                    ${(pkg.price_cents / 100).toLocaleString()}
                  </div>
                </div>
                {buyCredits.isPending && buyCredits.variables?.packageId === pkg.id ? (
                  <Icon name="loader" size={14} className="animate-spin text-ink-black/60" />
                ) : (
                  <span className="bg-hero-red px-2 py-1 font-meta text-[0.5rem] font-bold tracking-[0.14em] uppercase text-bristol">
                    Buy
                  </span>
                )}
              </button>
              {packages.length > 1 && (
                <a
                  href="/credits"
                  className="mt-3 inline-block font-meta text-[0.62rem] tracking-[0.14em] uppercase text-ink-black/55 hover:text-ink-black"
                >
                  See all packages →
                </a>
              )}
            </div>
          ) : null}

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="font-body text-[0.74rem] text-ink-black/45">
              {autoRunNote}
            </p>
            {pkg && (
              <Button
                size="md"
                disabled={buyCredits.isPending}
                onClick={() => buyCredits.mutate({ packageId: pkg.id })}
              >
                Buy credits
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
