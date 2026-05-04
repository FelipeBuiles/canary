import { useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useCreditBalance, useCreditHistory, useCreditPackages, useCreateCheckout, usePricingReference } from "../api/queries";
import type { CreditPackage, CreditTransaction } from "../types/api";
import { cn } from "../lib/cn";
import { Icon } from "../components/ui/Icon";

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function packageName(pkg: CreditPackage) {
  if (pkg.credits <= 1000) return "Starter";
  if (pkg.credits < 6000) return "Studio";
  return "Production";
}

function perThousand(pkg: CreditPackage) {
  return `$${(pkg.price_cents / 100 / (pkg.credits / 1000)).toFixed(2)} / 1K`;
}

function txLabel(tx: CreditTransaction): string {
  if (tx.description) return tx.description;
  if (tx.stage) return `Model call: ${tx.stage}`;
  return "Credit transaction";
}

function TransactionRow({ tx }: { tx: CreditTransaction }) {
  const isCredit = tx.amount_credits > 0;
  const amount = Math.abs(tx.amount_credits).toLocaleString();
  const isLargeDebit = tx.amount_credits < -20 || tx.status === "reserved";

  return (
    <tr className="border-b border-ink-black/10 bg-bristol/45 odd:bg-bristol">
      <td className="px-5 py-3 font-body text-[0.9rem] font-semibold text-ink-black/82">
        {txLabel(tx)}
      </td>
      <td className="px-5 py-3 font-body text-[0.78rem] font-semibold text-ink-black/46">
        {formatWhen(tx.created_at)}
      </td>
      <td
        className={cn(
          "px-5 py-3 text-right font-meta text-[0.82rem] font-bold tracking-[0.08em] tabular-nums",
          isCredit && "text-archive-sage",
          !isCredit && !isLargeDebit && "text-ink-black/70",
          isLargeDebit && "text-warn-orange",
        )}
      >
        {isCredit ? "+" : "-"}{amount} ◆
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
  const { data: pricingRef } = usePricingReference();
  const checkout = useCreateCheckout();

  const didRefresh = useRef(false);
  useEffect(() => {
    if (successParam && !didRefresh.current) {
      didRefresh.current = true;
      const ids = [500, 2000, 4000].map((delay) =>
        setTimeout(() => {
          qc.invalidateQueries({ queryKey: ["credits"] });
        }, delay),
      );
      return () => ids.forEach(clearTimeout);
    }
  }, [successParam, qc]);

  const credits = balance?.balance_credits ?? 0;
  const transactions = useMemo(() => history?.transactions ?? [], [history?.transactions]);
  const totalUsed = useMemo(
    () =>
      transactions
        .filter((tx) => tx.amount_credits < 0)
        .reduce((sum, tx) => sum + Math.abs(tx.amount_credits), 0),
    [transactions],
  );
  const usageWidth = Math.min(100, Math.round((totalUsed / 1000) * 100));

  function dismissSuccess() {
    searchParams.delete("success");
    setSearchParams(searchParams, { replace: true });
  }

  return (
    <div className="mx-auto w-full max-w-[880px] pb-16 pt-6">
      {successParam === "true" && (
        <div className="mb-8 flex items-center justify-between border-[2px] border-archive-sage bg-chip-sage px-4 py-3">
          <div className="flex items-center gap-3">
            <Icon name="check" size={16} className="text-archive-sage" />
            <span className="font-meta text-[0.72rem] font-bold tracking-[0.08em] text-ink-black/80">
              Payment received -- credits will appear shortly.
            </span>
          </div>
          <button type="button" onClick={dismissSuccess} className="font-meta text-[0.58rem] tracking-[0.12em] text-ink-black/45 hover:text-ink-black">
            DISMISS
          </button>
        </div>
      )}

      <section>
        <div className="font-meta text-[0.66rem] font-bold uppercase tracking-[0.24em] text-ink-black/42">
          Balance
        </div>
        <div className="mt-3 flex items-end gap-5">
          <span className="font-display text-[5.2rem] font-black leading-[0.78] tracking-[-0.04em] text-ink-black">
            {balanceLoading ? "..." : credits.toLocaleString()}
          </span>
          <span className="pb-2 font-meta text-[1rem] font-bold uppercase tracking-[0.18em] text-ink-black/45">
            Credits
          </span>
        </div>
        <p className="mt-6 max-w-[42rem] text-[1rem] font-semibold leading-7 text-ink-black/54">
          Credits power your production pipeline. Each paid stage shows an estimate before you commit. Reserved credits are held while the stage runs and released once it finishes — you're only charged for actual model usage.
        </p>
        <div className="mt-8 flex items-center gap-5">
          <div className="font-meta text-[0.66rem] font-bold uppercase tracking-[0.22em] text-ink-black/42">
            This month
          </div>
          <div className="h-2 flex-1 bg-surface-variant">
            <div className="h-full bg-hero-red" style={{ width: `${usageWidth}%` }} />
          </div>
          <div className="font-body text-[0.8rem] font-bold text-ink-black/68">
            {totalUsed.toLocaleString()} credits used
          </div>
        </div>
      </section>

      <section className="mt-14 border-l-[4px] border-ink-black/45 bg-surface-container px-7 py-5">
        <div className="mb-3 font-meta text-[0.66rem] font-bold uppercase tracking-[0.22em] text-ink-black/45">
          How credits work
        </div>
        <ul className="space-y-2 font-body text-[0.92rem] font-bold leading-6 text-ink-black/68">
          {(pricingRef?.notes ?? [
            "Estimated credits are projected before an action starts, based on your project's current inputs.",
            "Reserved credits are a temporary hold made when a paid stage begins — not a final charge.",
            "Final charges are settled from actual model usage once the stage finishes. Any unused reserved credits are released.",
            "Deterministic steps like Shot Plan layout and prompt assembly have no credit hold.",
            "Panel regeneration is charged from model usage after it completes — no separate hold is made.",
          ]).map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>

      <section className="mt-12">
        <div className="mb-5 font-meta text-[0.66rem] font-bold uppercase tracking-[0.22em] text-ink-black/42">
          Add Credits
        </div>
        <div className="grid gap-6 md:grid-cols-3">
          {packagesLoading
            ? [1, 2, 3].map((i) => <div key={i} className="h-52 animate-pulse bg-ink-black/5" />)
            : (packagesData?.packages ?? []).map((pkg) => {
                const popular = pkg.credits > 1000 && pkg.credits < 6000;
                return (
                  <article
                    key={pkg.id}
                    className={cn(
                      "relative border-[2px] bg-bristol p-6",
                      popular ? "border-hero-red" : "border-ink-black/12",
                    )}
                  >
                    {popular && (
                      <div className="absolute right-5 top-0 -translate-y-1/2 bg-hero-red px-4 py-1 font-meta text-[0.55rem] font-bold uppercase tracking-[0.16em] text-bristol">
                        Most Popular
                      </div>
                    )}
                    <div className="font-meta text-[0.68rem] font-bold uppercase tracking-[0.18em] text-ink-black/42">
                      {packageName(pkg)}
                    </div>
                    <div className="mt-2 font-display text-[3rem] font-black leading-[0.8] tracking-[-0.04em] text-ink-black">
                      {pkg.credits.toLocaleString()}
                    </div>
                    <div className="mt-1 font-meta text-[0.64rem] font-bold uppercase tracking-[0.16em] text-ink-black/42">
                      Credits
                    </div>
                    <div className="mt-5 font-body text-[0.9rem] font-bold text-ink-black/54">
                      {perThousand(pkg)}
                    </div>
                    <button
                      type="button"
                      disabled={checkout.isPending}
                      onClick={() => checkout.mutate({ packageId: pkg.id })}
                      className="mt-5 flex h-11 w-full items-center justify-center bg-ink-black px-4 font-meta text-[0.68rem] font-bold uppercase tracking-[0.2em] text-bristol hover:bg-hero-red disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Buy ${(pkg.price_cents / 100).toLocaleString()}
                    </button>
                  </article>
                );
              })}
        </div>
        <p className="mt-4 font-body text-[0.86rem] font-semibold text-ink-black/46">
          Payments processed securely by Stripe. Credits never expire.
        </p>
      </section>

      <section className="mt-14">
        <div className="mb-5 font-meta text-[0.66rem] font-bold uppercase tracking-[0.22em] text-ink-black/42">
          History
        </div>
        {historyLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => <div key={i} className="h-12 animate-pulse bg-ink-black/5" />)}
          </div>
        ) : transactions.length === 0 ? (
          <p className="font-body text-[0.9rem] font-semibold text-ink-black/42">No transactions yet.</p>
        ) : (
          <table className="w-full border-collapse border-[2px] border-ink-black/10">
            <thead>
              <tr className="bg-bristol">
                <th className="px-5 py-3 text-left font-meta text-[0.58rem] uppercase tracking-[0.16em] text-ink-black/42">Description</th>
                <th className="px-5 py-3 text-left font-meta text-[0.58rem] uppercase tracking-[0.16em] text-ink-black/42">When</th>
                <th className="px-5 py-3 text-right font-meta text-[0.58rem] uppercase tracking-[0.16em] text-ink-black/42">Credits</th>
              </tr>
            </thead>
            <tbody>{transactions.map((tx) => <TransactionRow key={tx.id} tx={tx} />)}</tbody>
          </table>
        )}
      </section>
    </div>
  );
}
