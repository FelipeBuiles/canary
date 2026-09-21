import { useState } from "react";

import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { groupRunsByActivity, runActivityLabel, type LedgerDayGroup } from "../../lib/creditsHistory";
import type { CreditLedgerRun, CreditTransaction } from "../../types/api";
import { CreditAmount } from "../ui/CreditAmount";
import { Icon } from "../ui/Icon";

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

function transactionLabel(tx: CreditTransaction): string {
  if (tx.amount_credits > 0) return "Credits added";
  if (tx.stage === "draw" && tx.image_count === 1) return "Draw complete page";
  if (tx.stage === "draw" && tx.image_count && tx.image_count > 1) return `Draw ${tx.image_count} pages`;
  if (tx.image_count && tx.image_count > 0) {
    return `Generate ${tx.image_count} image${tx.image_count === 1 ? "" : "s"}`;
  }
  return "Generation charge";
}

function StatusBadge({ status }: { status: CreditLedgerRun["status"] }) {
  const { t } = useI18n();
  if (status === "in_flight") {
    return (
      <span className="bg-narrator-gold px-2 py-1 font-meta text-xs font-bold tracking-[0.08em] text-ink-black">
        {t("Open hold")}
      </span>
    );
  }
  if (status === "complete") return null;
  return (
    <span className="bg-hero-red px-2 py-1 font-meta text-xs font-bold tracking-[0.08em] text-bristol">
      {t("Unsuccessful")}
    </span>
  );
}

function LedgerRunRow({ run, projectName }: { run: CreditLedgerRun; projectName: string | null }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const settled = run.rows.filter((row) => row.status === "settled");
  const detailsId = `ledger-run-${run.run_id}`;
  const isPurchase = run.credits_added > 0;
  const projectLabel = run.project_id ? (projectName ?? t("Project no longer available")) : null;

  return (
    <div className="border-t border-ink-black/10 first:border-t-0">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls={detailsId}
        className="flex w-full flex-wrap items-center gap-3 bg-bristol px-4 py-4 text-left transition-colors hover:bg-pulp-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-hero-red sm:flex-nowrap sm:px-5"
      >
        <span className="shrink-0 text-ink-muted">
          <Icon name="chevron-down" size={16} className={cn("transition-transform", !expanded && "-rotate-90")} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-body text-[0.9rem] font-semibold text-ink-black/82">
            {t(runActivityLabel(run))}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            {projectLabel && <span className="font-body text-sm font-semibold text-ink-muted">{projectLabel}</span>}
            {projectLabel && <span aria-hidden="true" className="text-ink-black/25">·</span>}
            <span className="font-body text-sm font-semibold text-ink-muted">{formatTime(run.started_at)}</span>
            <StatusBadge status={run.status} />
          </div>
        </div>
        <div className="flex basis-full flex-wrap items-baseline justify-start gap-2 pl-7 font-meta tabular-nums sm:ml-auto sm:w-auto sm:basis-auto sm:justify-end sm:pl-0">
          {isPurchase ? (
            <CreditAmount value={run.credits_added} sign="+" className="text-[0.82rem] font-bold text-archive-sage" />
          ) : run.actual_credits > 0 ? (
            <CreditAmount value={run.actual_credits} sign="-" className="text-[0.82rem] font-bold text-ink-black" />
          ) : run.status === "in_flight" ? (
            <span className="text-sm font-bold text-ink-muted"><CreditAmount value={run.estimate_credits} /> {t("held")}</span>
          ) : (
            <span className="text-sm font-bold text-ink-muted">{t("No charge")}</span>
          )}
          {run.status === "in_flight" && run.actual_credits > 0 && (
            <span className="text-sm text-ink-muted"><CreditAmount value={run.estimate_credits} /> {t("held")}</span>
          )}
        </div>
      </button>

      {expanded && (
        <div id={detailsId} className="bg-surface-container">
          {(run.estimate_credits > 0 || run.returned_credits > 0) && (
            <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-ink-black/8 px-5 py-3 pl-14 font-body text-sm font-semibold text-ink-muted">
              <span>{t("Estimated hold")} <CreditAmount value={run.estimate_credits} /></span>
              {run.status !== "in_flight" && <span>{t("Final charge")} <CreditAmount value={run.actual_credits} /></span>}
              {run.returned_credits > 0 && <span>{t("Released")} <CreditAmount value={run.returned_credits} /></span>}
            </div>
          )}
          {settled.map((tx, index) => (
            <div key={tx.id} className="flex items-center gap-3 border-t border-ink-black/8 px-5 py-2">
              <span className="ml-6 font-mono text-xs text-ink-muted">{index < settled.length - 1 ? "├" : "└"}</span>
              <div className="min-w-0 flex-1 font-body text-sm text-ink-muted">{t(transactionLabel(tx))}</div>
              <div className="shrink-0 font-meta text-sm font-bold tabular-nums text-ink-muted">
                <CreditAmount value={Math.abs(tx.amount_credits)} sign={tx.amount_credits > 0 ? "+" : "-"} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CreditHistoryLedger({
  groups,
  projectNameMap,
}: {
  groups: LedgerDayGroup[];
  projectNameMap: Map<string, string>;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <section key={group.key} aria-labelledby={`ledger-day-${group.key}`}>
          <div className="mb-2 flex flex-wrap items-end justify-between gap-3 px-1">
            <div>
              <h3 id={`ledger-day-${group.key}`} className="font-body text-[1rem] font-bold text-ink-black">{formatDay(group.latestAt)}</h3>
              <p className="mt-0.5 font-body text-sm font-semibold text-ink-muted">
                {t(group.runs.length === 1 ? "{count} activity" : "{count} activities").replace("{count}", String(group.runs.length))}
              </p>
            </div>
            <div className="flex w-full flex-wrap justify-start gap-x-4 gap-y-1 font-meta text-xs font-bold tabular-nums text-ink-muted sm:w-auto sm:justify-end">
              {group.actualCredits > 0 && <span><CreditAmount value={group.actualCredits} /> {t("used")}</span>}
              {group.creditsAdded > 0 && <span className="text-archive-sage"><CreditAmount value={group.creditsAdded} sign="+" /> {t("added")}</span>}
            </div>
          </div>
          <div className="border-[2px] border-ink-black/10 bg-surface-container">
            {groupRunsByActivity(group.runs).map((activity) => (
              <details key={activity.key} className="group/activity bg-bristol open:bg-pulp-paper">
                <summary className="flex min-h-16 cursor-pointer list-none flex-wrap items-center gap-3 px-4 py-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red sm:px-5 [&::-webkit-details-marker]:hidden">
                  <Icon name="chevron-down" size={16} className="shrink-0 -rotate-90 text-ink-muted group-open/activity:rotate-0" />
                  <div className="min-w-0 flex-1 basis-40">
                    <p className="font-body font-bold text-ink-black">{t(activity.label)}</p>
                    <p className="mt-1 break-words font-body text-sm text-ink-muted">
                      {activity.projectId ? projectNameMap.get(activity.projectId) ?? t("Project no longer available") : t("Account")}
                    </p>
                    <p className="mt-1 font-body text-sm text-ink-muted">
                      {t(activity.runs.length === 1 ? "{count} activity" : "{count} activities").replace("{count}", String(activity.runs.length))}
                      {activity.heldCount > 0 && ` · ${t(activity.heldCount === 1 ? "{count} open hold" : "{count} open holds").replace("{count}", String(activity.heldCount))}`}
                      {activity.failedCount > 0 && ` · ${t("{count} unsuccessful").replace("{count}", String(activity.failedCount))}`}
                    </p>
                  </div>
                  <div className="flex basis-full flex-wrap gap-x-4 gap-y-1 pl-7 font-body text-sm font-semibold tabular-nums sm:basis-auto sm:justify-end sm:pl-0">
                    {activity.actualCredits > 0 && <span><CreditAmount value={activity.actualCredits} /> {t("charged")}</span>}
                    {activity.heldCredits > 0 && <span className="text-ink-muted"><CreditAmount value={activity.heldCredits} /> {t("held")}</span>}
                    {activity.creditsAdded > 0 && <CreditAmount value={activity.creditsAdded} sign="+" className="text-archive-sage" />}
                    {activity.actualCredits === 0 && activity.heldCredits === 0 && activity.creditsAdded === 0 && <span className="text-ink-muted">{t("No charge")}</span>}
                  </div>
                </summary>
                {activity.runs.map((run) => (
                  <LedgerRunRow key={run.run_id} run={run} projectName={run.project_id ? (projectNameMap.get(run.project_id) ?? null) : null} />
                ))}
              </details>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
