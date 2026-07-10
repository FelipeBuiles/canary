import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useCreditBalance, useCreditHistory, useCreditPackages, useCreateCheckout, usePricingReference, useProjects } from "../api/queries";
import type { CreditPackage, CreditTransaction } from "../types/api";
import { cn } from "../lib/cn";
import { Icon } from "../components/ui/Icon";
import { Select } from "../components/ui/Select";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { SectionHeader } from "../components/composites";
import { stageLabel } from "../lib/stageLabels";

interface LedgerGroup {
  job_id: string;
  stage: string | null;
  project_id: string | null;
  startedAt: string;
  estimate_credits: number;
  actual_credits: number;
  returned_credits: number;
  status: "in_flight" | "complete" | "failed";
  rows: CreditTransaction[];
}

function groupTransactions(txs: CreditTransaction[]): LedgerGroup[] {
  const byJob = new Map<string, CreditTransaction[]>();
  const ungrouped: CreditTransaction[] = [];

  for (const tx of txs) {
    if (tx.job_id) {
      const existing = byJob.get(tx.job_id) ?? [];
      existing.push(tx);
      byJob.set(tx.job_id, existing);
    } else {
      ungrouped.push(tx);
    }
  }

  const groups: LedgerGroup[] = [];

  for (const [job_id, rows] of byJob.entries()) {
    const reservation = rows.find((r) => r.status === "reserved" || r.status === "released");
    const settled = rows.filter((r) => r.status === "settled");
    const estimate = reservation ? Math.abs(reservation.amount_credits) : 0;
    const actual = settled.reduce((s, r) => s + Math.abs(r.amount_credits), 0);
    const isReleased = !reservation || reservation.status === "released";
    const returned = isReleased ? Math.max(0, estimate - actual) : 0;
    const status: LedgerGroup["status"] =
      !isReleased ? "in_flight" : actual > 0 ? "complete" : "failed";
    const startedAt = rows.reduce(
      (earliest, r) => (r.created_at < earliest ? r.created_at : earliest),
      rows[0].created_at,
    );
    groups.push({
      job_id,
      stage: reservation?.stage ?? settled[0]?.stage ?? null,
      project_id: reservation?.project_id ?? settled[0]?.project_id ?? null,
      startedAt,
      estimate_credits: estimate,
      actual_credits: actual,
      returned_credits: returned,
      status,
      rows,
    });
  }

  for (const tx of ungrouped) {
    groups.push({
      job_id: tx.id,
      stage: tx.stage,
      project_id: tx.project_id,
      startedAt: tx.created_at,
      estimate_credits: 0,
      actual_credits: Math.max(0, -tx.amount_credits),
      returned_credits: 0,
      status: "complete",
      rows: [tx],
    });
  }

  return groups.sort((a, b) => b.startedAt.localeCompare(a.startedAt));
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function packageName(pkg: CreditPackage) {
  if (pkg.credits <= 1200) return "Starter";
  if (pkg.credits <= 3000) return "Standard";
  if (pkg.credits <= 7500) return "Creator";
  return "Studio";
}

function perThousand(pkg: CreditPackage) {
  return `$${(pkg.price_cents / 100 / (pkg.credits / 1000)).toFixed(2)} / 1K`;
}

function childRowLabel(tx: CreditTransaction): string {
  const parts: string[] = [];
  if (tx.model) parts.push(tx.model);
  if (tx.operation) parts.push(tx.operation);
  if (tx.image_count && tx.image_count > 0) parts.push(`${tx.image_count} image${tx.image_count !== 1 ? "s" : ""}`);
  return parts.join(" · ") || (tx.description ?? "Model call");
}

function StatusBadge({ status }: { status: LedgerGroup["status"] }) {
  if (status === "in_flight") {
    return (
      <span className="bg-narrator-gold px-2 py-1 font-meta text-[0.5rem] font-bold tracking-[0.08em] text-ink-black">
        IN FLIGHT
      </span>
    );
  }
  if (status === "complete") {
    return (
      <span className="bg-archive-sage px-2 py-1 font-meta text-[0.5rem] font-bold tracking-[0.08em] text-bristol">
        COMPLETE
      </span>
    );
  }
  return (
    <span className="bg-hero-red px-2 py-1 font-meta text-[0.5rem] font-bold tracking-[0.08em] text-bristol">
      FAILED
    </span>
  );
}

function LedgerGroupRow({
  group,
  projectName,
  isGrouped,
}: {
  group: LedgerGroup;
  projectName: string | null;
  isGrouped: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const settled = group.rows.filter((r) => r.status === "settled");

  if (!isGrouped) {
    // Ungrouped / legacy single-row display
    const tx = group.rows[0];
    const isCredit = tx.amount_credits > 0;
    const amount = Math.abs(tx.amount_credits).toLocaleString();
    return (
      <div className="flex flex-wrap items-center gap-3 border-b border-ink-black/10 bg-bristol/45 px-5 py-3 odd:bg-bristol">
        <div className="min-w-0 flex-1 font-body text-[0.9rem] font-semibold text-ink-black/82">
          {tx.description ?? (tx.stage ? `Model call: ${tx.stage}` : "Credit transaction")}
        </div>
        <div className="shrink-0 font-body text-[0.78rem] font-semibold text-ink-muted">
          {formatWhen(tx.created_at)}
        </div>
        <div
          className={cn(
            "shrink-0 text-right font-meta text-[0.82rem] font-bold tracking-[0.08em] tabular-nums",
            isCredit ? "text-archive-sage" : "text-ink-black/70",
          )}
        >
          {isCredit ? "+" : "-"}{amount} ◆
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-ink-black/10">
      {/* Summary row */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-wrap items-start gap-3 bg-bristol/45 px-4 py-4 text-left transition-colors hover:bg-bristol sm:flex-nowrap sm:px-5"
      >
        {/* Chevron */}
        <span className="mt-0.5 shrink-0 text-ink-muted">
          {expanded ? "▼" : "▶"}
        </span>

        {/* Label block */}
        <div className="min-w-0 flex-1">
          <div className="font-body text-[0.9rem] font-semibold text-ink-black/82">
            {stageLabel(group.stage)}
            {projectName && (
              <span className="ml-2 font-body text-[0.78rem] font-semibold text-ink-muted">
                · {projectName}
              </span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="font-body text-[0.72rem] font-semibold text-ink-muted">
              {formatWhen(group.startedAt)}
            </span>
            <StatusBadge status={group.status} />
          </div>
        </div>

        {/* Credit columns */}
        <div className="flex w-full shrink-0 items-center justify-between gap-3 border-t border-ink-black/10 pt-3 font-meta text-[0.7rem] tabular-nums text-ink-muted sm:w-auto sm:justify-start sm:border-0 sm:pt-0">
          {group.estimate_credits > 0 && (
            <span>
              <span className="text-[0.54rem] font-bold tracking-[0.06em] text-ink-muted">HELD </span>
              {group.estimate_credits.toLocaleString()}
            </span>
          )}
          {group.status !== "in_flight" ? (
            <span className={cn(group.actual_credits > 0 ? "font-bold text-ink-black" : "text-ink-muted")}>
              <span className="text-[0.54rem] font-bold tracking-[0.06em] text-ink-muted">USED </span>
              {group.actual_credits > 0 ? group.actual_credits.toLocaleString() : "—"}
            </span>
          ) : (
            <span className="text-ink-muted">
              <span className="text-[0.54rem] font-bold tracking-[0.06em]">USED </span>—
            </span>
          )}
          {group.returned_credits > 0 && (
            <span className="text-archive-sage">
              <span className="text-[0.54rem] font-bold tracking-[0.06em]">RETURNED </span>
              {group.returned_credits.toLocaleString()}
            </span>
          )}
        </div>
      </button>

      {/* Expanded child rows */}
      {expanded && settled.length > 0 && (
        <div className="bg-surface-container">
          {settled.map((tx, i) => (
            <div
              key={tx.id}
              className={cn(
                "flex items-center gap-3 border-t border-ink-black/8 px-5 py-2",
                i === settled.length - 1 ? "border-b-0" : "",
              )}
            >
              <span className="ml-6 font-mono text-[0.6rem] text-ink-muted">
                {i < settled.length - 1 ? "├" : "└"}
              </span>
              <div className="min-w-0 flex-1 font-body text-[0.78rem] text-ink-muted">
                {childRowLabel(tx)}
              </div>
              <div className="shrink-0 font-meta text-[0.72rem] font-bold tabular-nums text-ink-muted">
                {Math.abs(tx.amount_credits).toLocaleString()} ◆
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CreditsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const successParam = searchParams.get("success");
  const qc = useQueryClient();
  const [projectFilter, setProjectFilter] = useState<string | null>(null);

  const { data: balance, isLoading: balanceLoading } = useCreditBalance();
  const { data: history, isLoading: historyLoading } = useCreditHistory();
  const { data: packagesData, isLoading: packagesLoading } = useCreditPackages();
  const { data: pricingRef } = usePricingReference();
  const { data: projects } = useProjects();
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

  const projectNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of projects ?? []) {
      map.set(p.id, p.name);
    }
    return map;
  }, [projects]);

  const transactions = useMemo(() => history?.transactions ?? [], [history?.transactions]);

  const allGroups = useMemo(() => groupTransactions(transactions), [transactions]);

  const filterProjectIds = useMemo(() => {
    const ids = new Set<string>();
    for (const g of allGroups) {
      if (g.project_id) ids.add(g.project_id);
    }
    return [...ids];
  }, [allGroups]);

  const visibleGroups = useMemo(() => {
    if (!projectFilter) return allGroups;
    return allGroups.filter((g) => g.project_id === projectFilter);
  }, [allGroups, projectFilter]);

  const credits = balance?.balance_credits ?? 0;

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
    <div className="mx-auto w-full max-w-[1040px] pb-16 pt-2">
      {successParam === "true" && (
        <div role="status" className="animate-register-stamp mb-8 flex items-center justify-between border-[3px] border-ink-black bg-chip-sage px-4 py-3 shadow-paper-sm">
          <div className="flex items-center gap-3">
            <Icon name="check" size={16} className="text-archive-sage" />
            <span className="font-body text-[0.84rem] font-bold text-ink-black">
              Payment received -- credits will appear shortly.
            </span>
          </div>
          <button type="button" onClick={dismissSuccess} className="min-h-11 px-2 font-meta text-[0.58rem] font-bold tracking-[0.08em] text-ink-muted hover:text-ink-black">
            DISMISS
          </button>
        </div>
      )}

      <section className="grid overflow-hidden border-[3px] border-ink-black bg-ink-black shadow-paper md:grid-cols-[minmax(0,1fr)_320px]">
        <div className="px-6 py-8 text-bristol sm:px-9 sm:py-10">
          <div className="inline-flex bg-hero-red px-3 py-1.5 font-meta text-[0.58rem] font-bold uppercase tracking-[0.12em] text-bristol">
            Credits & billing
          </div>
          <h1 className="mt-5 font-display text-[3.2rem] font-black uppercase leading-[0.88] tracking-[-0.035em] text-bristol">
            Credit ledger
          </h1>
          <p className="mt-5 max-w-[42rem] font-body text-[0.95rem] font-semibold leading-7 text-bristol/75">
            Every paid action shows its cost before it runs. A temporary hold covers the work in progress; the ledger settles only the credits actually used.
          </p>
        </div>

        <div className="relative flex flex-col justify-between bg-narrator-gold px-6 py-8 text-ink-black sm:px-8">
          <div aria-hidden="true" className="absolute right-0 top-0 h-6 w-6 bg-ink-black [clip-path:polygon(100%_0,100%_100%,0_0)]" />
          <div>
            <div className="font-meta text-[0.58rem] font-bold uppercase tracking-[0.12em] text-ink-muted">Available now</div>
            <div className="mt-3 font-display text-[3.3rem] font-black leading-[0.82] tracking-[-0.035em]">
              {balanceLoading ? "—" : credits.toLocaleString()}
            </div>
            <div className="mt-2 font-meta text-[0.68rem] font-bold uppercase tracking-[0.1em]">Credits</div>
          </div>
          <div className="mt-8 border-t-[2px] border-ink-black pt-4">
            <div className="flex items-center justify-between font-body text-[0.78rem] font-bold">
              <span>This month</span>
              <span>{totalUsed.toLocaleString()} used</span>
            </div>
            <div className="mt-2 h-2 border-[2px] border-ink-black bg-pulp-paper">
              <div className="h-full bg-hero-red" style={{ width: `${usageWidth}%` }} />
            </div>
          </div>
        </div>
      </section>

      <section className="mt-10 border-[2px] border-ink-black bg-surface-container shadow-paper-sm">
        <div className="bg-narrator-gold px-5 py-3 font-meta text-[0.62rem] font-bold uppercase tracking-[0.1em] text-ink-black">
          How credits work
        </div>
        <ul className="grid gap-x-8 gap-y-3 px-5 py-5 font-body text-[0.88rem] font-semibold leading-6 text-ink-muted md:grid-cols-2 md:px-7">
          {(pricingRef?.notes ?? [
            "Estimated credits are projected before an action starts, based on your project's current inputs.",
            "Reserved credits are a temporary hold made when a paid stage begins — not a final charge.",
            "Final charges are settled from actual model usage once the stage finishes. Any unused reserved credits are released.",
            "Deterministic steps like Shot Plan layout and prompt assembly have no credit hold.",
            "Panel regeneration is charged from model usage after it completes — no separate hold is made.",
          ]).map((note) => (
            <li key={note} className="flex gap-3">
              <span aria-hidden="true" className="mt-2 h-2 w-2 shrink-0 bg-hero-red" />
              <span>{note}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-12">
        <SectionHeader variant="underline" title="Add credits" description="One-time packs. No subscription, and your credits do not expire." />
        <div className="grid gap-6 md:grid-cols-3">
          {packagesLoading
            ? [1, 2, 3].map((i) => <Skeleton key={i} className="h-60" />)
            : (packagesData?.packages ?? []).map((pkg) => {
                const popular = pkg.credits === 3000;
                return (
                  <article
                    key={pkg.id}
                    className={cn(
                      "relative flex min-h-64 flex-col border-[2px] bg-bristol p-6 shadow-paper-sm",
                      popular ? "-translate-y-1 border-ink-black shadow-ink" : "border-ink-black/18",
                    )}
                  >
                    {popular && (
                      <div className="absolute right-5 top-0 -translate-y-1/2 bg-hero-red px-4 py-1 font-meta text-[0.55rem] font-bold uppercase tracking-[0.16em] text-bristol">
                        Most Popular
                      </div>
                    )}
                    <div className="font-meta text-[0.64rem] font-bold uppercase tracking-[0.1em] text-ink-muted">
                      {packageName(pkg)}
                    </div>
                    <div className="mt-2 font-display text-[3rem] font-black leading-[0.8] tracking-[-0.04em] text-ink-black">
                      {pkg.credits.toLocaleString()}
                    </div>
                    <div className="mt-1 font-meta text-[0.64rem] font-bold uppercase tracking-[0.1em] text-ink-muted">
                      Credits
                    </div>
                    <div className="mt-5 font-body text-[0.9rem] font-bold text-ink-muted">
                      {perThousand(pkg)}
                    </div>
                    <Button
                      variant={popular ? "primary" : "outline"}
                      size="sm"
                      fullWidth
                      disabled={checkout.isPending}
                      onClick={() => checkout.mutate({ packageId: pkg.id })}
                      className="mt-auto"
                    >
                      Buy ${(pkg.price_cents / 100).toLocaleString()}
                    </Button>
                  </article>
                );
              })}
        </div>
        <p className="mt-5 font-body text-[0.86rem] font-semibold text-ink-muted">
          Payments processed securely by Stripe. Credits never expire. Purchases
          are subject to our{" "}
          <Link to="/legal/terms" className="text-ink-black underline underline-offset-2">
            Terms
          </Link>
          .
        </p>
      </section>

      <section className="mt-14">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3 border-b-[3px] border-ink-black pb-4">
          <h2 className="font-display text-[1.9rem] font-black uppercase leading-none tracking-[-0.035em] text-ink-black">
            History
          </h2>
          {filterProjectIds.length > 0 && (
            <Select
              aria-label="Filter history by project"
              size="sm"
              value={projectFilter ?? ""}
              onValueChange={(value) => setProjectFilter(value || null)}
              options={[
                { value: "", label: "ALL PROJECTS" },
                ...filterProjectIds.map((id) => ({ value: id, label: projectNameMap.get(id) ?? id.slice(0, 8) })),
              ]}
            />
          )}
        </div>
        {historyLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}
          </div>
        ) : visibleGroups.length === 0 ? (
          <div className="border-[2px] border-ink-black/12 bg-surface-container px-5 py-8 font-body text-[0.9rem] font-semibold text-ink-muted">
            No transactions yet. Your first hold and final charge will appear here after you run a paid stage.
          </div>
        ) : (
          <div className="border-[2px] border-ink-black/10">
            {visibleGroups.map((g) => {
              const isGrouped = g.rows.some((r) => r.job_id != null);
              return (
                <LedgerGroupRow
                  key={g.job_id}
                  group={g}
                  projectName={g.project_id ? (projectNameMap.get(g.project_id) ?? g.project_id.slice(0, 8)) : null}
                  isGrouped={isGrouped}
                />
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
