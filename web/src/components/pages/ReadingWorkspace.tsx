import { useEffect, useRef } from "react";
import { ArrowLeft } from "lucide-react";
import { useAdaptation, useBookPlan, useCompletePages } from "../../api/queries";
import { useI18n } from "../../i18n";
import type { DrawerKind } from "../../lib/stations";
import { RoomTabs } from "../composites/RoomTabs";
import { Button } from "../ui/Button";
import { Surface } from "../ui/Surface";
import { AdaptationDetails, PagePlanDetails } from "./ReadingDetails";

interface ReadingWorkspaceProps {
  project: string;
  kind: DrawerKind;
  onClose: () => void;
  onKindChange: (kind: DrawerKind) => void;
}

/** Long documents live in the station, keeping normal page scrolling and navigation. */
export function ReadingWorkspace({ project, kind, onClose, onKindChange }: ReadingWorkspaceProps) {
  const { t } = useI18n();
  const container = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const adaptation = useAdaptation(kind === "adaptation" ? project : undefined);
  const plan = useBookPlan(kind === "page-plan" ? project : undefined);
  const completePages = useCompletePages(kind === "page-plan" ? project : undefined);
  const query = kind === "adaptation" ? adaptation : plan;
  const title = kind === "adaptation" ? t("BOOK ADAPTATION") : t("PAGE PLAN");

  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    container.current?.scrollIntoView?.({ block: "start" });
  }, [kind]);

  return (
    <section ref={container} aria-label={title} className="mx-auto w-full max-w-6xl space-y-8 [overflow-wrap:anywhere]">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Button variant="outline" size="sm" onClick={onClose}>
          <ArrowLeft size={17} aria-hidden="true" />{t("Back to pages")}
        </Button>
        <RoomTabs ariaLabel={t("Reading documents")} tabs={[
          { key: "adaptation", label: t("BOOK ADAPTATION"), active: kind === "adaptation", onClick: () => onKindChange("adaptation") },
          { key: "page-plan", label: t("PAGE PLAN"), active: kind === "page-plan", onClick: () => onKindChange("page-plan") },
        ]} className="max-w-full [&>button]:px-3 sm:[&>button]:px-5" />
      </div>
      <header className="py-3 md:py-6">
        <h2 ref={heading} tabIndex={-1} className="scroll-mt-6 font-display text-3xl font-black uppercase leading-tight tracking-[-0.03em] focus-visible:outline-none md:text-5xl">{title}</h2>
        <p className="mt-4 max-w-[65ch] font-body text-base leading-7 text-ink-muted">
          {kind === "adaptation"
            ? t("Follow the story from its narrative treatment to the beats that shape the comic.")
            : t("Explore how the story is paced across pages, from quiet moments to big reveals.")}
        </p>
      </header>
      {query.isLoading && <p role="status" className="font-meta text-sm">{t("LOADING…")}</p>}
      {query.error && <Surface tone="gold" padding="md" border="soft" shadow="none">
        <p role="alert" className="font-body text-sm leading-6">{t("This document could not be loaded. Try again in a moment.")}</p>
        <Button variant="outline" size="sm" className="mt-3" disabled={query.isFetching} onClick={() => void query.refetch()}>{t("Try again")}</Button>
      </Surface>}
      {!query.isLoading && !query.error && !query.data && <p className="font-body text-sm leading-7 text-ink-muted">
        {kind === "adaptation" ? t("The book adaptation is not ready yet.") : t("The page plan is not ready yet.")}
      </p>}
      {kind === "adaptation" && adaptation.data && <AdaptationDetails adaptation={adaptation.data} />}
      {kind === "page-plan" && completePages.error && <Button variant="outline" size="sm" disabled={completePages.isFetching} onClick={() => void completePages.refetch()}>{t("Retry page details")}</Button>}
      {kind === "page-plan" && plan.data && <PagePlanDetails plan={plan.data} pages={completePages.data?.pages} detailsLoading={completePages.isLoading} detailsError={completePages.error} />}
    </section>
  );
}
