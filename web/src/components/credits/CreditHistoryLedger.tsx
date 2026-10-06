import { useI18n } from "../../i18n";
import type { Translator } from "../../locales/messages";
import {
  chargeBreakdown,
  formatPageRanges,
  groupRunsIntoSessions,
  type ChargeLine,
  type LedgerDayGroup,
  type LedgerSession,
} from "../../lib/creditsHistory";
import type { CreditLedgerRun } from "../../types/api";
import { CreditAmount } from "../ui/CreditAmount";
import { Icon } from "../ui/Icon";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTimeRange(start: string, end: string): string {
  const from = formatTime(start);
  const to = formatTime(end);
  return from === to ? from : `${from} – ${to}`;
}

function formatDay(iso: string, t: Translator): string {
  const date = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDifference = Math.round((startOfToday.getTime() - startOfDate.getTime()) / 86_400_000);
  if (dayDifference === 0) return t("Today");
  if (dayDifference === 1) return t("Yesterday");
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Say what the author did, in the tense of where it stands. */
function sessionTitle(session: LedgerSession, t: Translator): string {
  if (session.purchase) return t("Credit purchase");
  if (session.action) return t(session.action);
  const running = session.inFlight;
  switch (session.stage) {
    case "extract": return running ? t("Analyzing story") : t("Analyzed story");
    case "brief": return running ? t("Setting adaptation brief") : t("Set adaptation brief");
    case "style": return running ? t("Creating art style") : t("Created art style");
    case "cast": return running ? t("Creating characters and places") : t("Created characters and places");
    case "adapt": return running ? t("Adapting story") : t("Adapted story");
    case "plan": return running ? t("Planning pages") : t("Planned pages");
    case "finish": return running ? t("Finishing book") : t("Finished book");
    case "draw": {
      if (running) return t("Drawing pages");
      if (session.pageNumbers.length === 1) return t("Drew page {number}", { number: session.pageNumbers[0] });
      return t("{count, plural, one {Drew # page} other {Drew # pages}}", { count: session.pageNumbers.length || session.runs.length });
    }
    default: return t("Account adjustment");
  }
}

/** Name a run that ended without a charge. */
function unfinishedTitle(run: CreditLedgerRun, t: Translator): string {
  if (run.action) return t(run.action);
  if (run.stage === "draw" && run.page_number !== null) return t("Page {number}", { number: run.page_number });
  switch (run.stage) {
    case "extract": return t("Story analysis");
    case "brief": return t("Adaptation brief");
    case "style": return t("Art style");
    case "cast": return t("Characters and places");
    case "adapt": return t("Story adaptation");
    case "plan": return t("Page plan");
    case "draw": return t("Page drawing");
    case "finish": return t("Book finishing");
    default: return t("Account adjustment");
  }
}

function lineTitle(line: ChargeLine, t: Translator): string {
  if (line.pages.length > 1) return t("Pages {pages}", { pages: formatPageRanges(line.pages) });
  if (line.pages.length === 1) return t("Page {number}", { number: line.pages[0] });
  return t(line.label);
}

function lineDetail(line: ChargeLine, t: Translator): string | null {
  if (line.pages.length > 1) {
    return t("{credits, plural, one {# credit each} other {# credits each}}", { credits: line.credits / line.pages.length });
  }
  if (line.pages.length === 1) {
    const steps = line.details.map((label) => t(label)).join(", ");
    return line.steps > 1 ? t("{steps} · drawn {count} times", { steps, count: line.steps }) : steps;
  }
  return line.steps > 1 ? t("{count, plural, one {# step} other {# steps}}", { count: line.steps }) : null;
}

function HoldMeter({ used, reserved }: { used: number; reserved: number }) {
  const { t } = useI18n();
  const percent = reserved > 0 ? Math.min(100, Math.round((used / reserved) * 100)) : 0;
  return (
    <div className="mt-3">
      <div
        role="meter"
        aria-label={t("Reserved credits used")}
        aria-valuemin={0}
        aria-valuemax={reserved}
        aria-valuenow={Math.min(used, reserved)}
        className="h-2 overflow-hidden border border-ink-black/15 bg-surface-container"
      >
        <div className="h-full bg-ink-black/70 transition-[width]" style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-1.5 font-body text-xs font-semibold text-ink-muted">
        {used < reserved
          ? t("{used} of {reserved} reserved credits used so far. The rest returns to your balance when it finishes.", { used, reserved })
          // Each model call can extend the hold, so use may pass the first reservation.
          : t("{used} credits used so far. The hold grows with each step while it runs.", { used })}
      </p>
    </div>
  );
}

function SessionAmount({ session }: { session: LedgerSession }) {
  const { t } = useI18n();
  if (session.purchase) {
    return <CreditAmount value={session.creditsAdded} sign="+" className="font-bold text-archive-sage" />;
  }
  if (session.chargedCredits > 0) return <CreditAmount value={session.chargedCredits} className="font-bold text-ink-black" />;
  if (session.inFlight) {
    return <span className="font-semibold text-ink-muted"><CreditAmount value={session.openReservedCredits} /> {t("reserved")}</span>;
  }
  return <span className="font-semibold text-ink-muted">{t("No charge")}</span>;
}

function SessionRow({ session, projectName }: { session: LedgerSession; projectName: string | null }) {
  const { t } = useI18n();
  const lines = session.purchase ? [] : chargeBreakdown(session);
  const repeatRuns = session.stage !== "draw" && session.runs.length > 1;
  const hasDetails = lines.length > 0 || session.returnedCredits > 0;

  const summary = (
    <>
      <span className="mt-1 w-4 shrink-0 text-ink-muted">
        {hasDetails && <Icon name="chevron-down" size={16} className="-rotate-90 transition-transform group-open/session:rotate-0" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <p className="flex flex-wrap items-center gap-2 font-body font-bold text-ink-black">
            {sessionTitle(session, t)}
            {session.inFlight && (
              <span className="bg-narrator-gold px-2 py-0.5 font-meta text-[0.68rem] font-bold tracking-[0.08em] text-ink-black">
                {t("In progress")}
              </span>
            )}
          </p>
          <span className="font-meta text-sm tabular-nums"><SessionAmount session={session} /></span>
        </div>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-body text-sm font-semibold text-ink-muted">
          {projectName && <><span className="break-words">{projectName}</span><span aria-hidden="true" className="text-ink-black/25">·</span></>}
          <span>{formatTimeRange(session.startedAt, session.endedAt)}</span>
          {repeatRuns && <><span aria-hidden="true" className="text-ink-black/25">·</span><span>{t("{count, plural, one {# run} other {# runs}}", { count: session.runs.length })}</span></>}
        </p>
        {session.inFlight && session.openReservedCredits > 0 && (
          <HoldMeter used={session.openUsedCredits} reserved={session.openReservedCredits} />
        )}
      </div>
    </>
  );

  if (!hasDetails) {
    return <div className="flex gap-3 border-t border-ink-black/10 bg-bristol px-4 py-4 first:border-t-0 sm:px-5">{summary}</div>;
  }

  return (
    <details className="group/session border-t border-ink-black/10 bg-bristol first:border-t-0 open:bg-pulp-paper">
      <summary className="flex cursor-pointer list-none gap-3 px-4 py-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-hero-red sm:px-5 [&::-webkit-details-marker]:hidden">
        {summary}
      </summary>
      <div className="pb-3 pl-11 pr-4 sm:pl-12 sm:pr-5">
        {lines.length > 0 && (
          <ul className="border-t border-ink-black/10">
            {lines.map((line) => {
              const detail = lineDetail(line, t);
              return (
                <li key={line.key} className="flex items-baseline justify-between gap-4 border-b border-ink-black/8 py-2 font-body text-sm">
                  <span className="min-w-0">
                    <span className="font-semibold text-ink-black/82">{lineTitle(line, t)}</span>
                    {detail && <span className="text-ink-muted"> · {detail}</span>}
                  </span>
                  <CreditAmount value={line.credits} className="shrink-0 font-meta font-bold text-ink-muted" />
                </li>
              );
            })}
          </ul>
        )}
        {session.returnedCredits > 0 && (
          <p className="pt-2 font-body text-xs font-semibold text-ink-muted">
            {t("Reserved {reserved}, charged {charged}, {returned} returned to your balance.", {
              reserved: session.settledReservedCredits,
              charged: session.chargedCredits - session.openUsedCredits,
              returned: session.returnedCredits,
            })}
          </p>
        )}
      </div>
    </details>
  );
}

function UnfinishedRow({ runs }: { runs: CreditLedgerRun[] }) {
  const { t } = useI18n();
  return (
    <details className="group/session border-t border-ink-black/10 bg-surface-container first:border-t-0">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-hero-red sm:px-5 [&::-webkit-details-marker]:hidden">
        <Icon name="chevron-down" size={16} className="shrink-0 -rotate-90 text-ink-muted transition-transform group-open/session:rotate-0" />
        <span className="min-w-0 flex-1 font-body text-sm font-semibold text-ink-muted">
          {t("{count, plural, one {# attempt didn't finish} other {# attempts didn't finish}}", { count: runs.length })}
        </span>
        <span className="font-meta text-sm font-semibold text-ink-muted">{t("No charge")}</span>
      </summary>
      <ul className="pb-3 pl-11 pr-4 sm:pl-12 sm:pr-5">
        {runs.map((run) => (
          <li key={run.run_id} className="flex items-baseline justify-between gap-4 border-t border-ink-black/8 py-2 font-body text-sm text-ink-muted">
            <span>{unfinishedTitle(run, t)} · {formatTime(run.started_at)}</span>
            {run.returned_credits > 0 && (
              <span className="shrink-0 text-xs font-semibold">{t("{credits} returned", { credits: run.returned_credits })}</span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * Credit activity by day, folded into work sessions. Pass `projectNameMap`
 * when the history spans projects; omit it inside a single book.
 */
export function CreditHistoryLedger({
  groups,
  projectNameMap,
}: {
  groups: LedgerDayGroup[];
  projectNameMap?: Map<string, string>;
}) {
  const { t } = useI18n();
  const projectName = (projectId: string | null) => {
    if (!projectNameMap) return null;
    if (!projectId) return t("Account");
    return projectNameMap.get(projectId) ?? t("Project no longer available");
  };

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.key} aria-labelledby={`ledger-day-${group.key}`}>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-1">
            <h3 id={`ledger-day-${group.key}`} className="font-body text-[1rem] font-bold text-ink-black">{formatDay(group.latestAt, t)}</h3>
            <p className="flex flex-wrap gap-x-4 gap-y-1 font-meta text-xs font-bold tabular-nums text-ink-muted">
              {group.chargedCredits > 0 && <span><CreditAmount value={group.chargedCredits} /> {t("charged")}</span>}
              {group.openHoldCredits > 0 && <span><CreditAmount value={group.openHoldCredits} /> {t("still reserved")}</span>}
              {group.creditsAdded > 0 && <span className="text-archive-sage"><CreditAmount value={group.creditsAdded} sign="+" /> {t("added")}</span>}
            </p>
          </div>
          <div className="border-[2px] border-ink-black/10">
            {groupRunsIntoSessions(group.runs).map((entry) => entry.kind === "unfinished"
              ? <UnfinishedRow key={entry.key} runs={entry.runs} />
              : <SessionRow key={entry.session.key} session={entry.session} projectName={projectName(entry.session.projectId)} />)}
          </div>
        </section>
      ))}
    </div>
  );
}
