import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useCreditBalance, useCreditHistory, useCreditPackages, useCreateCheckout, usePricingReference, useProjects } from "../api/queries";
import type { CreditLedgerRun, CreditPackage, CreditTransaction } from "../types/api";
import { cn } from "../lib/cn";
import { useShowDevContent } from "../lib/devContent";
import { Icon } from "../components/ui/Icon";
import { Select } from "../components/ui/Select";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { CreditAmount } from "../components/ui/CreditAmount";
import { SectionHeader } from "../components/composites";
import { groupRunsByStage, type StageLedgerGroup } from "../lib/creditsHistory";
import { trackProductEvent } from "../api/events";

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
  const feature = (tx.description ?? "").replace(/^Model call(?: \w+)?:\s*/i, "").trim();
  const labels: Record<string, string> = {
    "prompt.visual_brief": "Compose panel image instruction",
    "prompt.layout": "Plan panel regions",
    "style.sample": "Render style proof",
    "draw.panel_image": "Draw panel",
  };
  if (labels[feature]) return labels[feature];
  if (feature) return feature.replaceAll(".", " ");
  if (tx.image_count && tx.image_count > 0) {
    return `Generate ${tx.image_count} image${tx.image_count === 1 ? "" : "s"}`;
  }
  return tx.operation === "text" ? "Text model call" : "Model call";
}

function StatusBadge({ status }: { status: CreditLedgerRun["status"] }) {
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

function LedgerRunRow({
  run,
  projectName,
  showDevContent,
}: {
  run: CreditLedgerRun;
  projectName: string | null;
  showDevContent: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const settled = run.rows.filter((row) => row.status === "settled");
  const detailsId = `ledger-run-${run.run_id}`;

  return (
    <div className="border-t border-ink-black/10 first:border-t-0">
      {/* Summary row */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls={detailsId}
        className="flex w-full flex-wrap items-start gap-3 bg-bristol px-4 py-4 text-left transition-colors hover:bg-pulp-paper sm:flex-nowrap sm:px-5"
      >
        {/* Chevron */}
        <span className="mt-0.5 shrink-0 text-ink-muted">
          {expanded ? "▼" : "▶"}
        </span>

        {/* Label block */}
        <div className="min-w-0 flex-1">
          <div className="font-body text-[0.9rem] font-semibold text-ink-black/82">
            {projectName ?? (run.credits_added > 0 ? "Credit purchase" : "Account activity")}
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="font-body text-[0.72rem] font-semibold text-ink-muted">
              {formatWhen(run.started_at)}
            </span>
            <StatusBadge status={run.status} />
          </div>
        </div>

        {/* Credit columns */}
        <div className="flex w-full shrink-0 items-center justify-between gap-3 border-t border-ink-black/10 pt-3 font-meta text-[0.7rem] tabular-nums text-ink-muted sm:w-auto sm:justify-start sm:border-0 sm:pt-0">
          {run.estimate_credits > 0 && (
            <span>
              <span className="text-[0.54rem] font-bold tracking-[0.06em] text-ink-muted">HELD </span>
              <CreditAmount value={run.estimate_credits} showMark showLabel={false} />
            </span>
          )}
          {run.credits_added > 0 ? (
            <span className="font-bold text-archive-sage">
              <span className="text-[0.54rem] font-bold tracking-[0.06em]">ADDED </span>
              <CreditAmount value={run.credits_added} sign="+" showMark showLabel={false} />
            </span>
          ) : run.status !== "in_flight" ? (
            <span className={cn(run.actual_credits > 0 ? "font-bold text-ink-black" : "text-ink-muted")}>
              <span className="text-[0.54rem] font-bold tracking-[0.06em] text-ink-muted">USED </span>
              {run.actual_credits > 0 ? <CreditAmount value={run.actual_credits} showMark showLabel={false} /> : "—"}
            </span>
          ) : (
            <span className="text-ink-muted">
              <span className="text-[0.54rem] font-bold tracking-[0.06em]">USED </span>—
            </span>
          )}
          {run.returned_credits > 0 && (
            <span className="text-archive-sage">
              <span className="text-[0.54rem] font-bold tracking-[0.06em]">RETURNED </span>
              <CreditAmount value={run.returned_credits} showMark showLabel={false} />
            </span>
          )}
        </div>
      </button>

      {/* Expanded child rows */}
      {expanded && settled.length > 0 && (
        <div id={detailsId} className="bg-surface-container">
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
                <div>{childRowLabel(tx)}</div>
                {showDevContent && (
                  <div className="mt-0.5 font-mono text-[0.62rem] text-ink-black/45">
                    {[tx.provider_model ?? tx.model, tx.input_tokens ? `${tx.input_tokens.toLocaleString()} in` : null, tx.output_tokens ? `${tx.output_tokens.toLocaleString()} out` : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                )}
              </div>
              <div className="shrink-0 font-meta text-[0.72rem] font-bold tabular-nums text-ink-muted">
                <CreditAmount
                  value={Math.abs(tx.amount_credits)}
                  sign={tx.amount_credits > 0 ? "+" : "-"}
                  showMark
                  showLabel={false}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StageLedgerSection({
  group,
  projectNameMap,
  showDevContent,
}: {
  group: StageLedgerGroup;
  projectNameMap: Map<string, string>;
  showDevContent: boolean;
}) {
  return (
    <section className="border-[2px] border-ink-black/10 bg-surface-container">
      <div className="flex flex-wrap items-baseline justify-between gap-3 bg-ink-black px-5 py-3 text-bristol">
        <div>
          <h3 className="font-body text-[0.9rem] font-bold">{group.label}</h3>
          <p className="mt-0.5 font-body text-[0.68rem] font-semibold text-bristol/65">
            {group.runs.length} {group.runs.length === 1 ? "run" : "runs"}
          </p>
        </div>
        <div className="font-meta text-[0.68rem] font-bold tracking-[0.06em] tabular-nums">
          {group.creditsAdded > 0 ? "ADDED " : "USED "}
          <CreditAmount
            value={group.creditsAdded > 0 ? group.creditsAdded : group.actualCredits}
            sign={group.creditsAdded > 0 ? "+" : undefined}
            showMark
            showLabel={false}
            className="ml-1"
          />
        </div>
      </div>
      <div>
        {group.runs.map((run) => (
          <LedgerRunRow
            key={run.run_id}
            run={run}
            projectName={run.project_id ? (projectNameMap.get(run.project_id) ?? run.project_id.slice(0, 8)) : null}
            showDevContent={showDevContent}
          />
        ))}
      </div>
    </section>
  );
}

export function CreditsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const successParam = searchParams.get("success");
  const cancelledParam = searchParams.get("cancelled");
  const cancelledPackage = searchParams.get("package");
  const qc = useQueryClient();
  const [projectFilter, setProjectFilter] = useState<string | null>(null);

  const { data: balance, isLoading: balanceLoading } = useCreditBalance();
  const {
    data: history,
    isLoading: historyLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useCreditHistory();
  const { data: packagesData, isLoading: packagesLoading } = useCreditPackages();
  const { data: pricingRef } = usePricingReference();
  const { data: projects } = useProjects();
  const checkout = useCreateCheckout();
  const [showDevContent] = useShowDevContent();

  const didRefresh = useRef(false);
  const didTrackCancellation = useRef(false);
  useEffect(() => {
    if (cancelledParam && !didTrackCancellation.current) {
      didTrackCancellation.current = true;
      void trackProductEvent("checkout_cancelled", {
        properties: { package_id: cancelledPackage ?? "unknown" },
      });
    }
  }, [cancelledPackage, cancelledParam]);

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

  const runs = useMemo(
    () => history?.pages.flatMap((page) => Array.isArray(page?.runs) ? page.runs.filter(Boolean) : []) ?? [],
    [history?.pages],
  );
  const filterProjectIds = useMemo(
    () => (projects ?? []).map((project) => project.id),
    [projects],
  );
  const visibleRuns = useMemo(
    () => projectFilter ? runs.filter((run) => run.project_id === projectFilter) : runs,
    [runs, projectFilter],
  );
  const stageGroups = useMemo(() => groupRunsByStage(visibleRuns), [visibleRuns]);

  const credits = balance?.balance_credits ?? 0;

  const totalUsed = history?.pages[0]?.month_used_credits ?? 0;

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
              {balanceLoading ? "—" : <CreditAmount value={credits} showMark showLabel={false} />}
            </div>
            <div className="mt-2 font-meta text-[0.68rem] font-bold uppercase tracking-[0.1em]">Credits</div>
          </div>
          <div className="mt-8 border-t-[2px] border-ink-black pt-4">
            <div className="flex items-center justify-between font-body text-[0.78rem] font-bold">
              <span>This month</span>
              <span><CreditAmount value={totalUsed} showMark showLabel={false} /> used</span>
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
                      <CreditAmount value={pkg.credits} showMark showLabel={false} />
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
        ) : stageGroups.length === 0 ? (
          <div className="space-y-3">
            <div className="border-[2px] border-ink-black/12 bg-surface-container px-5 py-8 font-body text-[0.9rem] font-semibold text-ink-muted">
              {projectFilter
                ? "No loaded history for this project. Load older history to keep looking."
                : "No transactions yet. Your first hold and final charge will appear here after you run a paid stage."}
            </div>
            {hasNextPage && (
              <Button
                variant="outline"
                size="sm"
                fullWidth
                disabled={isFetchingNextPage}
                onClick={() => fetchNextPage()}
              >
                {isFetchingNextPage ? "Loading history…" : "Load older history"}
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-5">
            {stageGroups.map((group) => (
              <StageLedgerSection
                key={group.key}
                group={group}
                projectNameMap={projectNameMap}
                showDevContent={showDevContent}
              />
            ))}
            {hasNextPage && (
              <Button
                variant="outline"
                size="sm"
                fullWidth
                disabled={isFetchingNextPage}
                onClick={() => fetchNextPage()}
              >
                {isFetchingNextPage ? "Loading history…" : "Load older history"}
              </Button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
