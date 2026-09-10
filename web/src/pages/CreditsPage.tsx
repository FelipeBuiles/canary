import { ArrowUpRight } from "lucide-react";
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
import { Surface } from "../components/ui/Surface";
import { EntityCard, SectionHeader } from "../components/composites";
import { groupRunsByDay, runActivityLabel, type LedgerDayGroup } from "../lib/creditsHistory";
import { trackProductEvent } from "../api/events";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDay(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDifference = Math.round((startOfToday.getTime() - startOfDate.getTime()) / 86_400_000);
  if (dayDifference === 0) return "Today";
  if (dayDifference === 1) return "Yesterday";
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
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
    "style.sample": "Render style proof",
    "draw.complete_page": "Draw complete page",
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
      <span className="bg-narrator-gold px-2 py-1 font-meta text-xs font-bold tracking-[0.08em] text-ink-black">
        IN FLIGHT
      </span>
    );
  }
  if (status === "complete") return null;
  return (
    <span className="bg-hero-red px-2 py-1 font-meta text-xs font-bold tracking-[0.08em] text-bristol">
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
  const isPurchase = run.credits_added > 0;
  const projectLabel = run.project_id ? (projectName ?? "Project no longer available") : null;

  return (
    <div className="border-t border-ink-black/10 first:border-t-0">
      {/* Summary row */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls={detailsId}
        className="flex w-full flex-wrap items-center gap-3 bg-bristol px-4 py-4 text-left transition-colors hover:bg-pulp-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-hero-red sm:flex-nowrap sm:px-5"
      >
        {/* Chevron */}
        <span className="shrink-0 text-ink-muted">
          <Icon name="chevron-down" size={16} className={cn("transition-transform", !expanded && "-rotate-90")} />
        </span>

        {/* Label block */}
        <div className="min-w-0 flex-1">
          <div className="font-body text-[0.9rem] font-semibold text-ink-black/82">
            {runActivityLabel(run)}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            {projectLabel && (
              <span className="font-body text-sm font-semibold text-ink-muted">
                {projectLabel}
              </span>
            )}
            {projectLabel && <span aria-hidden="true" className="text-ink-black/25">·</span>}
            <span className="font-body text-sm font-semibold text-ink-muted">
              {formatTime(run.started_at)}
            </span>
            <StatusBadge status={run.status} />
          </div>
        </div>

        {/* Net credit change is the primary accounting fact. */}
        <div className="flex basis-full items-baseline justify-start gap-2 pl-7 font-meta tabular-nums sm:ml-auto sm:w-auto sm:basis-auto sm:justify-end sm:pl-0">
          {isPurchase ? (
            <CreditAmount value={run.credits_added} sign="+" className="text-[0.82rem] font-bold text-archive-sage" />
          ) : run.actual_credits > 0 ? (
            <CreditAmount value={run.actual_credits} sign="-" className="text-[0.82rem] font-bold text-ink-black" />
          ) : run.status === "in_flight" ? (
            <span className="text-sm font-bold text-ink-muted">
              <CreditAmount value={run.estimate_credits} /> held
            </span>
          ) : (
            <span className="text-sm font-bold text-ink-muted">No charge</span>
          )}
        </div>
      </button>

      {/* Expanded child rows */}
      {expanded && (
        <div id={detailsId} className="bg-surface-container">
          {(run.estimate_credits > 0 || run.returned_credits > 0) && (
            <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-ink-black/8 px-5 py-3 pl-14 font-body text-sm font-semibold text-ink-muted">
              <span>Estimated hold <CreditAmount value={run.estimate_credits} /></span>
              {run.status !== "in_flight" && <span>Final charge <CreditAmount value={run.actual_credits} /></span>}
              {run.returned_credits > 0 && <span>Released <CreditAmount value={run.returned_credits} /></span>}
            </div>
          )}
          {settled.map((tx, i) => (
            <div
              key={tx.id}
              className={cn(
                "flex items-center gap-3 border-t border-ink-black/8 px-5 py-2",
                i === settled.length - 1 ? "border-b-0" : "",
              )}
            >
              <span className="ml-6 font-mono text-xs text-ink-muted">
                {i < settled.length - 1 ? "├" : "└"}
              </span>
              <div className="min-w-0 flex-1 font-body text-sm text-ink-muted">
                <div>{childRowLabel(tx)}</div>
                {showDevContent && (
                  <div className="mt-0.5 font-mono text-xs text-ink-black/45">
                    {[tx.provider_model ?? tx.model, tx.input_tokens ? `${tx.input_tokens.toLocaleString()} in` : null, tx.output_tokens ? `${tx.output_tokens.toLocaleString()} out` : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                )}
              </div>
              <div className="shrink-0 font-meta text-sm font-bold tabular-nums text-ink-muted">
                <CreditAmount
                  value={Math.abs(tx.amount_credits)}
                  sign={tx.amount_credits > 0 ? "+" : "-"}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DayLedgerSection({
  group,
  projectNameMap,
  showDevContent,
}: {
  group: LedgerDayGroup;
  projectNameMap: Map<string, string>;
  showDevContent: boolean;
}) {
  return (
    <section aria-labelledby={`ledger-day-${group.key}`}>
      <div className="mb-2 flex flex-wrap items-end justify-between gap-3 px-1">
        <div>
          <h3 id={`ledger-day-${group.key}`} className="font-body text-[1rem] font-bold text-ink-black">
            {formatDay(group.latestAt)}
          </h3>
          <p className="mt-0.5 font-body text-sm font-semibold text-ink-muted">
            {group.runs.length} {group.runs.length === 1 ? "activity" : "activities"}
          </p>
        </div>
        <div className="flex w-full flex-wrap justify-start gap-x-4 gap-y-1 font-meta text-xs font-bold tabular-nums text-ink-muted sm:w-auto sm:justify-end">
          {group.actualCredits > 0 && <span><CreditAmount value={group.actualCredits} /> used</span>}
          {group.creditsAdded > 0 && (
            <span className="text-archive-sage"><CreditAmount value={group.creditsAdded} sign="+" /> added</span>
          )}
        </div>
      </div>
      <div className="border-[2px] border-ink-black/10 bg-surface-container">
        {group.runs.map((run) => (
          <LedgerRunRow
            key={run.run_id}
            run={run}
            projectName={run.project_id ? (projectNameMap.get(run.project_id) ?? null) : null}
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

  const { data: balance, isLoading: balanceLoading, isError: balanceError, refetch: refetchBalance } = useCreditBalance();
  const {
    data: history,
    isLoading: historyLoading,
    isError: historyError,
    refetch: refetchHistory,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useCreditHistory();
  const { data: packagesData, isLoading: packagesLoading, isError: packagesError, refetch: refetchPackages } = useCreditPackages();
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
      map.set(p.id, p.project_name);
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
  const dayGroups = useMemo(() => groupRunsByDay(visibleRuns), [visibleRuns]);

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
          <button type="button" onClick={dismissSuccess} className="min-h-11 px-2 font-meta text-xs font-bold tracking-[0.08em] text-ink-muted hover:text-ink-black">
            DISMISS
          </button>
        </div>
      )}

      <Surface tone="ink" shadow="paper" className="grid overflow-hidden md:grid-cols-[minmax(0,1fr)_320px]">
        <div className="px-6 py-8 text-bristol sm:px-9 sm:py-10">
          <h1 className="font-display text-[2.4rem] sm:text-[3.2rem] font-black uppercase leading-[0.88] tracking-[-0.035em] text-bristol">
            Credits
          </h1>
          <p className="mt-5 max-w-[42rem] font-body text-[0.95rem] font-semibold leading-7 text-bristol/75">
            Add credits when you need them, and see where every credit goes.
          </p>
          <nav aria-label="Credit sections" className="mt-6 flex flex-wrap gap-3 font-body text-sm font-semibold">
            <a href="#credit-packs" className="inline-flex min-h-11 items-center bg-bristol px-4 text-ink-black hover:bg-narrator-gold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-bristol">Add credits <ArrowUpRight size={16} aria-hidden="true" className="ml-3" /></a>
            <a href="#credit-history" className="inline-flex min-h-11 items-center px-3 text-bristol underline underline-offset-4 hover:text-narrator-gold">View history</a>
          </nav>
        </div>

        <div className="relative flex flex-col justify-between bg-narrator-gold px-6 py-8 text-ink-black sm:px-8">
          <div aria-hidden="true" className="absolute right-0 top-0 h-6 w-6 bg-ink-black [clip-path:polygon(100%_0,100%_100%,0_0)]" />
          <div>
            <div className="font-meta text-xs font-bold uppercase tracking-[0.12em] text-ink-muted">Available now</div>
            <div className="mt-3 font-display text-[3.3rem] font-black leading-[0.82] tracking-[-0.035em]">
              {balanceLoading || balanceError || !balance ? "—" : <CreditAmount value={credits} showMark showLabel={false} />}
            </div>
            <div className="mt-2 font-meta text-xs font-bold uppercase tracking-[0.1em]">Credits</div>
            {balanceError && <div role="alert" className="mt-3 font-body text-sm"><p>Balance unavailable.</p><button type="button" onClick={() => void refetchBalance()} className="min-h-11 font-semibold underline underline-offset-4">Retry balance</button></div>}
          </div>
          <div className="mt-8 border-t-[2px] border-ink-black pt-4">
            <div className="flex items-center justify-between font-body text-sm font-bold">
              <span>This month</span>
              <span>{historyLoading || historyError || !history ? "Unavailable" : <><CreditAmount value={totalUsed} showMark showLabel={false} /> used</>}</span>
            </div>
          </div>
        </div>
      </Surface>

      <section tabIndex={-1} id="credit-packs" className="mt-10 scroll-mt-6">
        <SectionHeader variant="underline" title="Add credits" description="One-time packs. No subscription, and your credits do not expire." />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {packagesLoading
            ? [1, 2, 3].map((i) => <Skeleton key={i} className="h-60" />)
            : packagesError ? <Surface tone="pulp" shadow="none" padding="md" className="sm:col-span-2 lg:col-span-3" role="alert"><p className="font-body text-sm">Credit packs could not be loaded.</p><Button variant="outline" size="sm" className="mt-3" onClick={() => void refetchPackages()}>Retry credit packs</Button></Surface>
            : (packagesData?.packages ?? []).map((pkg) => {
                return (
                  <EntityCard key={pkg.id} padding="tight" className="min-h-64">
                    <div className="font-meta text-xs font-bold uppercase tracking-[0.1em] text-ink-muted">
                      {packageName(pkg)}
                    </div>
                    <div className="mt-2 font-display text-[3rem] font-black leading-[0.8] tracking-[-0.04em] text-ink-black">
                      <CreditAmount value={pkg.credits} showMark showLabel={false} />
                    </div>
                    <div className="mt-1 font-meta text-xs font-bold uppercase tracking-[0.1em] text-ink-muted">
                      Credits
                    </div>
                    <div className="mt-5 font-body text-[0.9rem] font-bold text-ink-muted">
                      {perThousand(pkg)}
                    </div>
                    <Button
                      variant="primary"
                      size="sm"
                      fullWidth
                      disabled={checkout.isPending}
                      onClick={() => checkout.mutate({ packageId: pkg.id })}
                      className="mt-6"
                    >
                      Buy ${(pkg.price_cents / 100).toLocaleString()}
                    </Button>
                  </EntityCard>
                );
              })}
        </div>
        {!packagesLoading && !packagesError && packagesData?.packages.length === 0 && <p role="status" className="font-body text-sm text-ink-muted">No credit packs are available right now.</p>}
        {checkout.isError && <p role="alert" className="mt-4 font-body text-sm text-hero-red">Checkout could not be opened. Please choose your pack again to retry.</p>}
        {cancelledParam && <p role="status" className="mt-4 font-body text-sm text-ink-muted">Checkout was cancelled. You can choose a pack when you're ready.</p>}
        <p className="mt-5 font-body text-[0.86rem] font-semibold text-ink-muted">
          Payments processed securely by Stripe. Credits never expire. Purchases
          are subject to our{" "}
          <Link to="/legal/terms" className="text-ink-black underline underline-offset-2">
            Terms
          </Link>
          .
        </p>
      </section>

      <details className="mt-8 border-y border-ink-black/15">
        <summary className="cursor-pointer px-1 py-4 font-body text-base font-semibold text-ink-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red">
          How credits work
        </summary>
        <ul className="grid gap-x-8 gap-y-3 px-5 py-5 font-body text-[0.88rem] font-semibold leading-6 text-ink-muted md:grid-cols-2 md:px-7">
          {(pricingRef?.notes ?? [
            "Estimated credits are projected before an action starts, based on your project's current inputs.",
            "Reserved credits are a temporary hold made when a paid stage begins — not a final charge.",
            "Final charges are settled from actual model usage once the stage finishes. Any unused reserved credits are released.",
          ]).map((note) => (
            <li key={note} className="flex gap-3">
              <span aria-hidden="true" className="mt-2 h-2 w-2 shrink-0 bg-hero-red" />
              <span>{note}</span>
            </li>
          ))}
        </ul>
      </details>

      <section tabIndex={-1} id="credit-history" className="mt-10 scroll-mt-6">
        <div className="mb-4 flex flex-col items-stretch justify-between gap-3 border-b-[3px] border-ink-black pb-4 sm:flex-row sm:items-end">
          <div>
            <h2 className="font-display text-[1.9rem] font-black uppercase leading-none tracking-[-0.035em] text-ink-black">
              History
            </h2>
            <p className="mt-1.5 font-body text-sm font-semibold text-ink-muted">
              Newest first. Open an activity to see how its charge was calculated.
            </p>
          </div>
          {filterProjectIds.length > 0 && (
            <Select
              aria-label="Filter history by project"
              size="sm"
              value={projectFilter ?? ""}
              onValueChange={(value) => setProjectFilter(value || null)}
              className="w-full sm:w-auto"
              options={[
                { value: "", label: "All projects" },
                ...filterProjectIds.map((id) => ({ value: id, label: projectNameMap.get(id) ?? "Project no longer available" })),
              ]}
            />
          )}
        </div>
        {historyError && <Surface tone="pulp" padding="md" shadow="none" role="alert" className="mb-4"><p className="font-body text-sm">Credit history could not be refreshed. Any activity shown below was loaded earlier.</p><Button variant="outline" size="sm" className="mt-3" onClick={() => void refetchHistory()}>Retry history</Button></Surface>}
        {historyLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}
          </div>
        ) : historyError && dayGroups.length === 0 ? null : dayGroups.length === 0 ? (
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
            {dayGroups.map((group) => (
              <DayLedgerSection
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
