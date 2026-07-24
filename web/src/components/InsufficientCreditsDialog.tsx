import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";
import { ShortcutHint } from "./ui/ShortcutHint";
import { cn } from "../lib/cn";
import { createCheckout } from "../api/billing";
import {
  useCreditBalance,
  useCreditPackages,
} from "../api/queries";
import {
  packageMeetsShortfall,
  pickRecommendedPackage,
} from "../lib/creditsPurchase";
import { useInsufficientCreditsStore } from "../store/insufficientCredits";
import { CreditAmount } from "./ui/CreditAmount";
import { SupportLink } from "./SupportLink";

export function InsufficientCreditsDialog() {
  const open = useInsufficientCreditsStore((s) => s.open);
  const info = useInsufficientCreditsStore((s) => s.info);
  const actionLabel = useInsufficientCreditsStore((s) => s.actionLabel);
  const onRetry = useInsufficientCreditsStore((s) => s.onRetry);
  const close = useInsufficientCreditsStore((s) => s.close);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const { data: liveBalance } = useCreditBalance();
  const { data: packagesData } = useCreditPackages();
  const qc = useQueryClient();
  const [checkoutPending, setCheckoutPending] = useState<string | null>(null);
  // Open Stripe Checkout in a new tab so the dialog (and the user's pending
  // action) stays mounted. We poll the balance on focus and auto-retry once
  // the webhook lands.
  const checkout = useMutation({
    mutationFn: ({ packageId }: { packageId: string }) => createCheckout(packageId),
    onMutate: ({ packageId }) => {
      setCheckoutPending(packageId);
    },
    onSettled: () => {
      setCheckoutPending(null);
    },
    onSuccess: ({ url }) => {
      window.open(url, "_blank", "noopener,noreferrer");
    },
  });

  const balance = liveBalance?.balance_credits ?? info?.balance_credits ?? 0;
  const required = info?.required_credits ?? 0;
  const shortfall = Math.max(0, required - balance);
  const packages = useMemo(() => packagesData?.packages ?? [], [packagesData?.packages]);
  const recommended = useMemo(
    () => (info ? pickRecommendedPackage(packages, shortfall) : undefined),
    [packages, shortfall, info],
  );

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, close]);

  // While the dialog is open, refresh the balance whenever the tab regains
  // focus (so we pick up the Stripe webhook landing in the background tab).
  useEffect(() => {
    if (!open) return;
    qc.invalidateQueries({ queryKey: ["credits", "balance"] });
    function onFocus() {
      qc.invalidateQueries({ queryKey: ["credits", "balance"] });
    }
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    const interval = window.setInterval(onFocus, 5000);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
      window.clearInterval(interval);
    };
  }, [open, qc]);

  // Auto-close once the user has enough credits (e.g. webhook landed) AND
  // they have a retry callback waiting.
  useEffect(() => {
    if (!open || !info) return;
    if (balance >= info.required_credits && onRetry) {
      const retry = onRetry;
      close();
      retry();
    }
  }, [open, info, balance, onRetry, close]);

  if (!open || !info) return null;

  const headline = actionLabel
    ? `${actionLabel} needs more credits`
    : "Not enough credits";

  return (
    <div
      className="fixed inset-0 z-[140] flex items-end justify-center bg-ink-black/70 sm:items-center"
      onClick={close}
      role="presentation"
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="insufficient-credits-title"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "relative w-full max-w-[640px] border-x-[2px] border-t-[2px] border-ink-black bg-pulp-paper text-ink-black sm:border-[2px]",
          "animate-[insufficient-slide_320ms_cubic-bezier(0.2,0.8,0.2,1)]",
        )}
        style={{ borderTop: "4px solid var(--color-narrator-gold)" }}
      >
        <style>{`
          @keyframes insufficient-slide {
            from { transform: translateY(40px); opacity: 0.4; }
            to   { transform: translateY(0);    opacity: 1; }
          }
        `}</style>

        <div className="px-6 pt-5 pb-6 sm:px-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="mb-2 inline-flex items-center gap-2 border-[1.5px] border-narrator-gold px-2 py-0.5 font-meta text-[0.58rem] tracking-[0.2em] uppercase text-narrator-gold">
                <Icon name="alert" size={11} />
                Add credits
              </div>
              <h2
                id="insufficient-credits-title"
                className="font-display text-[1.6rem] leading-[0.95] tracking-[-0.02em] uppercase sm:text-[1.85rem]"
              >
                {headline}
              </h2>
            </div>
            <button
              type="button"
              onClick={close}
              aria-label="Dismiss"
              className="inline-flex min-h-11 shrink-0 items-center gap-2 border-[2px] border-ink-black/20 px-3 font-meta text-[0.62rem] tracking-[0.12em] uppercase text-ink-black/60 hover:border-ink-black hover:text-ink-black"
            >
              Close <ShortcutHint>Esc</ShortcutHint>
            </button>
          </div>

          <p className="mt-4 text-[0.92rem] leading-6 text-ink-fade">
            You're a bit short on credits to start this action. Top up below — we'll
            release any unused portion of the hold once it finishes.
          </p>

          <div className="mt-4 grid grid-cols-3 gap-4 border-[2px] border-narrator-gold/35 bg-chip-gold/20 p-4">
            <div>
              <div className="font-meta text-[0.54rem] tracking-[0.16em] uppercase text-ink-black/50">
                Balance
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums">
                <CreditAmount value={balance} showMark showLabel={false} />
              </div>
            </div>
            <div>
              <div className="font-meta text-[0.54rem] tracking-[0.16em] uppercase text-ink-black/50">
                Needed
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums">
                <CreditAmount value={required} showMark showLabel={false} />
              </div>
            </div>
            <div>
              <div className="font-meta text-[0.54rem] tracking-[0.16em] uppercase text-narrator-gold">
                Short by
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums text-narrator-gold">
                <CreditAmount value={shortfall} showMark showLabel={false} />
              </div>
            </div>
          </div>

          {packages.length > 0 && (
            <div className="mt-5">
              <div className="font-meta text-[0.6rem] font-bold tracking-[0.16em] uppercase text-ink-black/45">
                Top up
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                {packages.map((pkg) => {
                  const covers = packageMeetsShortfall(pkg, shortfall);
                  const isRecommended = recommended?.id === pkg.id;
                  const isThisPending = checkoutPending === pkg.id;
                  return (
                    <button
                      key={pkg.id}
                      type="button"
                      disabled={checkout.isPending}
                      onClick={() => checkout.mutate({ packageId: pkg.id })}
                      className={cn(
                        "flex flex-col items-start gap-1 border-[2px] bg-bristol px-3 py-3 text-left transition-colors hover:bg-pulp-paper disabled:cursor-not-allowed disabled:opacity-50",
                        isRecommended ? "border-hero-red" : "border-ink-black/15",
                      )}
                    >
                      <div className="flex w-full items-center justify-between gap-2">
                        <span className="font-display text-[1.1rem] font-black tabular-nums">
                          <CreditAmount value={pkg.credits} showLabel={false} />
                        </span>
                        {isThisPending ? (
                          <span aria-hidden="true" className="animate-press-blink h-3 w-3 bg-hero-red" />
                        ) : isRecommended ? (
                          <span className="bg-hero-red px-1.5 py-0.5 font-meta text-[0.48rem] font-bold tracking-[0.14em] uppercase text-bristol">
                            Pick
                          </span>
                        ) : null}
                      </div>
                      <span className="font-meta text-[0.56rem] tracking-[0.14em] uppercase text-ink-black/50">
                        Credits · ${(pkg.price_cents / 100).toLocaleString()}
                      </span>
                      <span
                        className={cn(
                          "font-meta text-[0.56rem] tracking-[0.06em]",
                          covers ? "text-archive-sage" : "text-ink-black/40",
                        )}
                      >
                        {covers ? "Covers shortfall" : "Partial top-up"}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-3 font-body text-[0.74rem] text-ink-black/45">
                Stripe Checkout opens in a new tab. Once payment lands this prompt
                will close automatically.
              </p>
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <a
              href="/credits"
              className="font-meta text-[0.62rem] tracking-[0.14em] uppercase text-ink-black/55 hover:text-ink-black"
            >
              View billing →
            </a>
            <SupportLink
              diagnostics={{
                releaseSha: import.meta.env.VITE_CANARY_VERSION,
                errorCategory: "insufficient_credits",
              }}
              className="font-meta text-[0.62rem] tracking-[0.14em] uppercase text-hero-red hover:text-ink-black"
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="outline" size="md" onClick={close} disabled={checkout.isPending}>
                Not now
              </Button>
              {onRetry && (
                <Button
                  size="md"
                  disabled={balance < required || checkout.isPending}
                  onClick={() => {
                    const retry = onRetry;
                    close();
                    retry();
                  }}
                >
                  {balance < required ? "Waiting for credits…" : "Retry"}
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
