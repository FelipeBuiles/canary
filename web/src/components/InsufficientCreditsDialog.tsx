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
import { useDialogFocus } from "../hooks/useDialogFocus";
import { useBackdropDismiss } from "../hooks/useBackdropDismiss";
import { useI18n } from "../i18n";

export function InsufficientCreditsDialog() {
  const open = useInsufficientCreditsStore((s) => s.open);
  const hasInfo = useInsufficientCreditsStore((s) => s.info !== null);
  return open && hasInfo ? <OpenInsufficientCreditsDialog /> : null;
}

function OpenInsufficientCreditsDialog() {
  const { t } = useI18n();
  const info = useInsufficientCreditsStore((s) => s.info);
  const actionLabel = useInsufficientCreditsStore((s) => s.actionLabel);
  const onRetry = useInsufficientCreditsStore((s) => s.onRetry);
  const close = useInsufficientCreditsStore((s) => s.close);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const { data: liveBalance } = useCreditBalance();
  const { data: packagesData } = useCreditPackages();
  const qc = useQueryClient();
  const [checkoutPending, setCheckoutPending] = useState<string | null>(null);
  // Checkout stays in a separate tab. A funded balance never authorizes spend.
  const [checkoutUrl, setCheckoutUrl] = useState<string | null>(null);
  const checkout = useMutation({
    mutationFn: ({ packageId }: { packageId: string }) => createCheckout(packageId),
    onMutate: ({ packageId }) => {
      setCheckoutPending(packageId);
      setCheckoutUrl(null);
    },
    onSettled: () => {
      setCheckoutPending(null);
    },
    onSuccess: ({ url }) => {
      setCheckoutUrl(url);
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

  useDialogFocus(dialogRef, { onClose: close });
  const backdrop = useBackdropDismiss(close);

  // While the dialog is open, refresh the balance whenever the tab regains
  // focus (so we pick up the Stripe webhook landing in the background tab).
  useEffect(() => {
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
  }, [qc]);

  if (!info) return null;

  const headline = balance >= required
    ? t("Credits ready — your action is paused")
    : actionLabel
      ? t("{action} needs more credits", { action: actionLabel })
      : t("Not enough credits");

  return (
    <div
      className="fixed inset-0 z-[140] flex items-end justify-center bg-ink-black/70 sm:items-center"
      {...backdrop}
      role="presentation"
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="insufficient-credits-title"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "relative max-h-[calc(100dvh-1rem)] overflow-y-auto w-full max-w-[640px] border-x-[2px] border-t-[2px] border-ink-black bg-pulp-paper text-ink-black sm:border-[2px]",
          "animate-[insufficient-slide_var(--motion-settle)_cubic-bezier(0.2,0.8,0.2,1)]",
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
              <div className="mb-2 inline-flex items-center gap-2 border-[1.5px] border-narrator-gold px-2 py-0.5 font-meta text-xs tracking-[0.1em] uppercase text-on-gold">
                <Icon name="alert" size={14} />
                {t("Add credits")}
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
              aria-label={t("Dismiss")}
              className="inline-flex min-h-11 shrink-0 items-center gap-2 border-[2px] border-ink-black/20 px-3 font-meta text-xs tracking-[0.1em] uppercase text-ink-muted hover:border-ink-black hover:text-ink-black"
            >
              {t("Close")} <ShortcutHint>Esc</ShortcutHint>
            </button>
          </div>

          <p className="mt-4 text-[0.92rem] leading-6 text-ink-fade">
            {t("Top up below, then choose Resume when you are ready. Nothing starts automatically. Unused held credits are released after the action finishes.")}
          </p>

          <div className="mt-4 grid grid-cols-3 gap-4 border-[2px] border-narrator-gold/35 bg-chip-gold/20 p-4">
            <div>
              <div className="font-meta text-xs tracking-[0.08em] uppercase text-ink-muted">
                {t("Balance")}
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums">
                <CreditAmount value={balance} showMark showLabel={false} />
              </div>
            </div>
            <div>
              <div className="font-meta text-xs tracking-[0.08em] uppercase text-ink-muted">
                {t("Needed")}
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums">
                <CreditAmount value={required} showMark showLabel={false} />
              </div>
            </div>
            <div>
              <div className="font-meta text-xs tracking-[0.08em] uppercase text-on-gold">
                {t("Short by")}
              </div>
              <div className="mt-1 font-display text-[1.3rem] font-bold tabular-nums text-on-gold">
                <CreditAmount value={shortfall} showMark showLabel={false} />
              </div>
            </div>
          </div>

          {packages.length > 0 && balance < required && (
            <div className="mt-5">
              <div className="font-meta text-xs font-bold tracking-[0.1em] uppercase text-ink-muted">
                {t("Top up")}
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
                        isRecommended ? "border-on-gold" : "border-ink-black/15",
                      )}
                    >
                      <div className="flex w-full items-center justify-between gap-2">
                        <span className="font-display text-[1.1rem] font-black tabular-nums">
                          <CreditAmount value={pkg.credits} showLabel={false} />
                        </span>
                        {isThisPending ? (
                          <span aria-hidden="true" className="animate-press-blink h-3 w-3 bg-hero-red" />
                        ) : isRecommended ? (
                          <span className="bg-narrator-gold px-1.5 py-0.5 font-meta text-xs font-bold tracking-[0.08em] uppercase text-ink-black">
                            {t("Pick")}
                          </span>
                        ) : null}
                      </div>
                      <span className="font-meta text-xs tracking-[0.08em] uppercase text-ink-muted">
                        {t("Credits")} · ${(pkg.price_cents / 100).toLocaleString()}
                      </span>
                      <span
                        className={cn(
                          "font-meta text-xs tracking-[0.04em]",
                          covers ? "text-ready" : "text-ink-muted",
                        )}
                      >
                        {covers ? t("Covers shortfall") : t("Partial top-up")}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-3 font-body text-sm text-ink-muted">
                {t("Stripe Checkout opens in a new tab. Return here after payment to resume your pending action.")}
              </p>
            </div>
          )}
          {checkout.error && (
            <p role="alert" className="mt-4 font-body text-sm text-hero-red">
              {t("Checkout could not open. Your action is still paused. Try a package again or open billing.")} {checkout.error.message}
            </p>
          )}
          {checkoutUrl && (
            <a href={checkoutUrl} target="_blank" rel="noopener noreferrer" className="mt-4 inline-flex min-h-11 items-center font-body text-sm font-semibold underline underline-offset-4">
              {t("Open secure checkout")}
            </a>
          )}
          {balance >= required && (
            <p role="status" className="mt-4 font-body text-sm text-ready">
              {t("Your balance now covers this action. Resume only when you are ready.")}
            </p>
          )}

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <a
              href="/credits"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-11 items-center font-meta text-xs tracking-[0.08em] uppercase text-ink-muted hover:text-ink-black"
            >
              {t("View billing")} →
            </a>
            <SupportLink
              diagnostics={{
                releaseSha: import.meta.env.VITE_CANARY_VERSION,
                errorCategory: "insufficient_credits",
              }}
              className="inline-flex min-h-11 items-center font-meta text-xs tracking-[0.08em] uppercase text-hero-red hover:text-ink-black"
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="outline" size="md" onClick={close} disabled={checkout.isPending}>
                {t("Not now")}
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
                  {balance < required ? t("Waiting for credits…") : t("Resume {action}", { action: actionLabel ?? t("pending action") })}
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
