import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { useAdaptation, useBookPlan, useCompletePages, useStoryBible } from "../../api/queries";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { entityNames } from "../../lib/readingDocs";
import { canReadDocument } from "../../lib/stationAccess";
import type { ProjectStatus } from "../../types/api";
import type { DrawerKind } from "../../lib/stations";
import { RoomHeader } from "../composites/RoomHeader";
import { RoomNotice } from "../composites/RoomNotice";
import { RoomShell } from "../composites/RoomShell";
import { Button } from "../ui/Button";
import { AdaptationDetails, EditorialNotes, PagePlanDetails } from "./ReadingDetails";

interface ReadingWorkspaceProps {
  project: string;
  kind: DrawerKind;
  status: ProjectStatus | undefined;
  onClose: () => void;
  onKindChange: (kind: DrawerKind) => void;
}

/** Long documents live in the station, keeping normal page scrolling and navigation. */
export function ReadingWorkspace(props: ReadingWorkspaceProps) {
  if (!canReadDocument(props.kind, props.status)) return null;
  return <ReadyReadingWorkspace {...props} />;
}

const segment = (on: boolean) => cn(
  "min-h-8 px-3.5 font-meta text-[0.8125rem] font-medium disabled:cursor-not-allowed disabled:opacity-40",
  on ? "bg-ink-black text-pulp-paper" : "text-ink-soft hover:bg-surface-container hover:text-ink-black",
);

function ReadyReadingWorkspace({ project, kind, status, onClose, onKindChange }: ReadingWorkspaceProps) {
  const { t } = useI18n();
  const container = useRef<HTMLElement>(null);
  const adaptation = useAdaptation(kind === "adaptation" ? project : undefined);
  const plan = useBookPlan(kind === "page-plan" ? project : undefined);
  const completePages = useCompletePages(project);
  const bible = useStoryBible(kind === "page-plan" ? project : undefined);
  const names = useMemo(() => entityNames(bible.data), [bible.data]);
  const query = kind === "adaptation" ? adaptation : plan;
  const title = kind === "adaptation" ? t("Adaptation") : t("Page plan");
  // Shared between the two documents: a panel's beat opens in the adaptation, a page header opens in the plan.
  const [planPage, setPlanPage] = useState<number | null>(null);
  const [focusBeat, setFocusBeat] = useState<string | null>(null);

  useEffect(() => {
    container.current?.focus({ preventScroll: true });
  }, [kind]);

  const pageCount = kind === "adaptation" ? completePages.data?.pages.length : plan.data?.pages?.length;
  const facts = kind === "adaptation"
    ? [adaptation.data?.beats && t("{count, plural, one {# beat} other {# beats}}", { count: adaptation.data.beats.length }), pageCount && t("{count, plural, one {# page} other {# pages}}", { count: pageCount })]
    : [pageCount && t("{count, plural, one {# page} other {# pages}}", { count: pageCount }),
      plan.data && t("target {range}", { range: plan.data.target_page_min === plan.data.target_page_max ? String(plan.data.target_page_min) : `${plan.data.target_page_min}–${plan.data.target_page_max}` })];
  const issues = query.data?.editorial_issues ?? [];

  return (
    <RoomShell project={project} bleed>
      <RoomHeader title={title} lead={facts.filter(Boolean).join(" · ")} />
      <section ref={container} tabIndex={-1} aria-label={title} className="flex min-h-0 flex-1 flex-col outline-none [overflow-wrap:anywhere]">
        <div className="flex min-h-13 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-ink-black/12 px-4 py-2 sm:px-6 studio-desktop:px-5">
          <button type="button" onClick={onClose} aria-label={t("Back to pages")}
            className="inline-flex min-h-8 items-center gap-1.5 px-1 font-meta text-[0.8125rem] font-medium text-ink-soft hover:text-ink-black">
            <ArrowLeft size={15} aria-hidden="true" />{t("Pages")}
          </button>
          <div role="group" aria-label={t("Reading documents")} className="inline-flex border border-ink-black/25 bg-bristol">
            {(["adaptation", "page-plan"] as const).map((key) => {
              const ready = canReadDocument(key, status);
              return (
                <button key={key} type="button" aria-pressed={kind === key} disabled={!ready}
                  title={!ready ? t("Available when this document is ready") : undefined}
                  onClick={() => { setFocusBeat(null); onKindChange(key); }} className={segment(kind === key)}>
                  {key === "adaptation" ? t("Adaptation") : t("Page plan")}
                </button>
              );
            })}
          </div>
          {issues.length > 0 && (
            <div className="ml-auto">
              <RoomNotice tone="attention" align="end" title={t("Editorial notes")} label={t("{count, plural, one {# editorial note} other {# editorial notes}}", { count: issues.length })}>
                <EditorialNotes issues={issues} />
              </RoomNotice>
            </div>
          )}
        </div>

        {query.isLoading && <p role="status" className="px-6 py-10 font-meta text-sm text-ink-muted">{t("Loading…")}</p>}
        {query.error && (
          <div className="px-6 py-10">
            <p role="alert" className="font-body text-sm leading-6">{t("This document could not be loaded. Try again in a moment.")}</p>
            <Button variant="outline" size="sm" className="mt-3" disabled={query.isFetching} onClick={() => void query.refetch()}>{t("Try again")}</Button>
          </div>
        )}
        {!query.isLoading && !query.error && !query.data && (
          <p className="px-6 py-10 font-body text-sm text-ink-muted">
            {kind === "adaptation" ? t("The book adaptation is not ready yet.") : t("The page plan is not ready yet.")}
          </p>
        )}
        {kind === "page-plan" && completePages.error && (
          <div className="border-b border-ink-black/10 px-6 py-2">
            <Button variant="outline" size="sm" disabled={completePages.isFetching} onClick={() => void completePages.refetch()}>{t("Retry page details")}</Button>
          </div>
        )}
        {kind === "adaptation" && adaptation.data && (
          <AdaptationDetails project={project} adaptation={adaptation.data} pages={completePages.data?.pages} focusBeat={focusBeat}
            onOpenPage={(page) => { setPlanPage(page); onKindChange("page-plan"); }} />
        )}
        {kind === "page-plan" && plan.data && (
          <PagePlanDetails project={project} plan={plan.data} pages={completePages.data?.pages} names={names}
            detailsLoading={completePages.isLoading} detailsError={completePages.error}
            page={planPage} onPage={setPlanPage}
            onOpenBeat={(beat) => { setFocusBeat(beat); onKindChange("adaptation"); }} />
        )}
      </section>
    </RoomShell>
  );
}
