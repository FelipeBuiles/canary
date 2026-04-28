import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useCreditBalance, useCreditHistory, useCreditPackages, useCreateCheckout } from "../api/queries";
import type { CreditTransaction } from "../types/api";
import { cn } from "../lib/cn";
import { Icon } from "../components/ui/Icon";

function formatCredits(credits: number): string {
  return `${Math.abs(credits).toLocaleString()} credits`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function txLabel(tx: CreditTransaction): string {
  if (tx.description) return tx.description;
  if (tx.stage) return `Stage: ${tx.stage}`;
  return "Transaction";
}

function txBadge(tx: CreditTransaction) {
  if (tx.status === "reserved") return { label: "RESERVED", cls: "text-narrator-gold/80 bg-narrator-gold/10" };
  if (tx.status === "released") return { label: "RELEASED", cls: "text-bristol/40 bg-bristol/8" };
  return null;
}

function TransactionRow({ tx }: { tx: CreditTransaction }) {
  const isCredit = tx.amount_credits > 0;
  const badge = txBadge(tx);

  return (
    <tr className="border-b border-ink-black/6 transition-colors hover:bg-ink-black/[0.02]">
      <td className="py-3 pr-4">
        <span className="font-body text-[0.88rem] text-ink-black/80">{txLabel(tx)}</span>
        {badge && (
          <span className={cn("ml-2 rounded-none px-1.5 py-0.5 font-meta text-[0.48rem] tracking-[0.1em]", badge.cls)}>
            {badge.label}
          </span>
        )}
      </td>
      <td className="py-3 pr-4 font-meta text-[0.62rem] tracking-[0.06em] text-ink-black/40">
        {formatDate(tx.created_at)}
      </td>
      <td className={cn(
        "py-3 text-right font-meta text-[0.78rem] tabular-nums font-medium",
        isCredit ? "text-archive-sage" : "text-ink-black/65",
      )}>
        {isCredit ? "+" : "−"}{formatCredits(tx.amount_credits)}
      </td>
    </tr>
  );
}

export function CreditsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const successParam = searchParams.get("success");
  const qc = useQueryClient();

  const { data: balance, isLoading: balanceLoading } = useCreditBalance();
  const { data: history, isLoading: historyLoading } = useCreditHistory();
  const { data: packagesData, isLoading: packagesLoading } = useCreditPackages();
  const checkout = useCreateCheckout();

  const didRefresh = useRef(false);
  useEffect(() => {
    if (successParam && !didRefresh.current) {
      didRefresh.current = true;
      // Stripe webhook may take a moment — poll balance a few times
      const ids = [500, 2000, 4000].map((delay) =>
        setTimeout(() => {
          qc.invalidateQueries({ queryKey: ["credits"] });
        }, delay),
      );
      return () => ids.forEach(clearTimeout);
    }
  }, [successParam, qc]);

  function dismissSuccess() {
    searchParams.delete("success");
    setSearchParams(searchParams, { replace: true });
  }

  const credits = balance?.balance_credits ?? 0;
  const isLow = credits < 500;

  const packages = packagesData?.packages ?? [];
  const transactions = history?.transactions ?? [];

  return (
    <div className="mx-auto w-full max-w-[760px] space-y-10">
      {/* Success banner */}
      {successParam === "true" && (
        <div className="flex items-center justify-between border-[2px] border-archive-sage bg-archive-sage/10 px-4 py-3">
          <div className="flex items-center gap-3">
            <Icon name="check" size={16} className="shrink-0 text-archive-sage" />
            <span className="font-meta text-[0.74rem] tracking-[0.08em] text-ink-black/80">
              Payment received — credits will appear shortly.
            </span>
          </div>
          <button
            type="button"
            onClick={dismissSuccess}
            className="ml-4 font-meta text-[0.6rem] tracking-[0.1em] text-ink-black/40 hover:text-ink-black"
          >
            DISMISS
          </button>
        </div>
      )}

      {/* Balance hero */}
      <section>
        <h1 className="font-meta text-[0.62rem] tracking-[0.2em] text-ink-black/40">BALANCE</h1>
        <div className="mt-2 flex items-baseline gap-3">
          {balanceLoading ? (
            <span className="font-display text-[3rem] font-black leading-none text-ink-black/20">—</span>
          ) : (
            <span className={cn(
              "font-display text-[3.5rem] font-black leading-none tracking-[-0.04em]",
              isLow ? "text-hero-red" : "text-ink-black",
            )}>
              {credits.toLocaleString()}
            </span>
          )}
          {isLow && !balanceLoading && (
            <span className="font-meta text-[0.62rem] tracking-[0.14em] text-hero-red/80">LOW BALANCE</span>
          )}
        </div>
        <p className="mt-2 font-body text-[0.88rem] text-ink-black/45">
          Credits are consumed by model calls. Unused reservations are returned when an action finishes, resets, or fails.
        </p>
      </section>

      {/* Purchase packages */}
      <section>
        <h2 className="font-meta text-[0.62rem] tracking-[0.2em] text-ink-black/40">ADD CREDITS</h2>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {packagesLoading
            ? [1, 2, 3].map((i) => (
                <div key={i} className="h-40 animate-pulse bg-ink-black/5" />
              ))
            : packages.map((pkg) => (
                <div
                  key={pkg.id}
                  className="flex flex-col border-[2px] border-ink-black/12 bg-white p-5 transition-shadow hover:shadow-md"
                >
                  <span className="font-display text-[2rem] font-black leading-none tracking-[-0.04em] text-ink-black">
                    {pkg.label}
                  </span>
                  <span className="mt-2 font-meta text-[0.64rem] tracking-[0.1em] text-ink-black/50">
                    {pkg.credits.toLocaleString()} CREDITS
                  </span>
                  <button
                    type="button"
                    disabled={checkout.isPending}
                    onClick={() => checkout.mutate({ packageId: pkg.id })}
                    className="mt-auto flex items-center justify-center gap-2 border-[2px] border-ink-black/80 bg-hero-red px-3 py-2.5 font-meta text-[0.66rem] tracking-[0.16em] text-bristol shadow-ink-sm transition-colors hover:bg-hero-red/90 disabled:cursor-not-allowed disabled:opacity-50 mt-6"
                  >
                    {checkout.isPending && checkout.variables?.packageId === pkg.id && (
                      <Icon name="loader" size={12} className="animate-spin" />
                    )}
                    BUY {pkg.label}
                  </button>
                </div>
              ))}
        </div>
        <p className="mt-3 font-meta text-[0.54rem] tracking-[0.08em] text-ink-black/30">
          Payments processed securely by Stripe. Credits are non-refundable.
        </p>
      </section>

      {/* Transaction history */}
      <section>
        <h2 className="font-meta text-[0.62rem] tracking-[0.2em] text-ink-black/40">HISTORY</h2>
        <div className="mt-4">
          {historyLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-10 animate-pulse bg-ink-black/5" />
              ))}
            </div>
          ) : transactions.length === 0 ? (
            <p className="font-body text-[0.88rem] text-ink-black/35">No transactions yet.</p>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b-[2px] border-ink-black/15">
                  <th className="pb-2 text-left font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/40">DESCRIPTION</th>
                  <th className="pb-2 text-left font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/40">DATE</th>
                  <th className="pb-2 text-right font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/40">AMOUNT</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx) => (
                  <TransactionRow key={tx.id} tx={tx} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
