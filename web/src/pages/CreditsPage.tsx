import { ArrowUpRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useCreditBalance, useCreditHistory, useCreditPackages, useCreateCheckout, usePricingReference, useProjects } from "../api/queries";
import type { CreditPackage } from "../types/api";
import { Icon } from "../components/ui/Icon";
import { Select } from "../components/ui/Select";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { CreditAmount } from "../components/ui/CreditAmount";
import { Surface } from "../components/ui/Surface";
import { CardGrantOffer } from "../components/CardGrantOffer";
import { EntityCard, SectionHeader } from "../components/composites";
import { CreditHistoryLedger } from "../components/credits/CreditHistoryLedger";
import { groupRunsByDay, matchesLedgerFilter, type LedgerFilter } from "../lib/creditsHistory";
import { useI18n } from "../i18n";
import { trackProductEvent } from "../api/events";

function packageName(pkg: CreditPackage) {
  if (pkg.credits <= 1200) return "Starter";
  if (pkg.credits <= 3000) return "Standard";
  if (pkg.credits <= 7500) return "Creator";
  return "Studio";
}

function perThousand(pkg: CreditPackage) {
  return `$${(pkg.price_cents / 100 / (pkg.credits / 1000)).toFixed(2)} / 1K`;
}


export function CreditsPage() {
  const { t } = useI18n();
  const [activityFilter, setActivityFilter] = useState<LedgerFilter>("all");
  const [searchParams, setSearchParams] = useSearchParams();
  const successParam = searchParams.get("success");
  const cancelledParam = searchParams.get("cancelled");
  const cancelledPackage = searchParams.get("package");
  const qc = useQueryClient();
  const [projectFilter, setProjectFilter] = useState<string | null>(() => searchParams.get("project"));

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
    () => runs.filter((run) => (!projectFilter || run.project_id === projectFilter) && matchesLedgerFilter(run, activityFilter)),
    [runs, projectFilter, activityFilter],
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

      <CardGrantOffer outcome={searchParams.get("card_grant")} />

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
        <SectionHeader variant="underline" title="Add credits" description="One-time packs. No subscription, and purchased credits do not expire." />
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
          Payments processed securely by Stripe. Purchased credits never expire. Purchases
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
              {t("Grouped by day and work session. Open an activity to see what each step and page cost.")}
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Select
              aria-label={t("Filter history by activity")}
              size="sm"
              value={activityFilter}
              onValueChange={(value) => setActivityFilter(value as LedgerFilter)}
              options={[
                { value: "all", label: t("All activity") },
                { value: "charged", label: t("Charges") },
                { value: "held", label: t("Open holds") },
                { value: "failed", label: t("Unsuccessful") },
                { value: "added", label: t("Credits added") },
              ]}
            />
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
        </div>
        <p className="mb-4 font-body text-sm leading-6 text-ink-muted">{t("Open holds are still reserved, including attempts awaiting billing reconciliation. They are separate from final charges.")}</p>
        {historyError && <Surface tone="pulp" padding="md" shadow="none" role="alert" className="mb-4"><p className="font-body text-sm">Credit history could not be refreshed. Any activity shown below was loaded earlier.</p><Button variant="outline" size="sm" className="mt-3" onClick={() => void refetchHistory()}>Retry history</Button></Surface>}
        {historyLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}
          </div>
        ) : historyError && dayGroups.length === 0 ? null : dayGroups.length === 0 ? (
          <div className="space-y-3">
            <div className="border-[2px] border-ink-black/12 bg-surface-container px-5 py-8 font-body text-[0.9rem] font-semibold text-ink-muted">
              {projectFilter || activityFilter !== "all"
                ? t("No matching activity in loaded history. Load older history or change the filters.")
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
            <CreditHistoryLedger groups={dayGroups} projectNameMap={projectNameMap} />
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
