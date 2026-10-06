import { trackProductEvent } from "../../api/events";
import { PageVersions } from "../../components/pages/PageVersions";
import { ArchivedArtwork } from "../../components/pages/ArchivedArtwork";
import { createPortal } from "react-dom";
import { ArrowUpRight, BookOpen, Layers, ChevronLeft as ReviewChevronLeft, ChevronRight as ReviewChevronRight, X as ReviewClose } from "lucide-react";
import { LetteringEditor } from "../../components/lettering/LetteringEditor";
import { pageCompositePreviewUrl } from "../../api/lettering";
import { PageThumbnail } from "../../components/pages/PageThumbnail";
import { WholeBookReveal } from "../../components/pages/WholeBookReveal";
import { editionKeyFor } from "../../lib/editionKey";
import { accountIdentity } from "../../lib/accountEpoch";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  useAnalyzeCompletePage,
  useApproveStage,
  useCompletePages,
  useGenerateCompletePage,
  useGenerationJobs,
  useProjectStatus,
  useRunPipeline,
  useStageValidation,
  useCompletePageBatchEstimate,
  useCancelQueuedPageJobs,
  useCompletePageEstimate,
  usePageAnalysisEstimate,
  useStyles,
} from "../../api/queries";
import { pageRenderPreviewUrl } from "../../api/pages";
import { ReadingWorkspace } from "../../components/pages/ReadingWorkspace";
import { canReadDocument } from "../../lib/stationAccess";
import {
  ApprovalBar,
  RerunStageAction,
  EntityCard,
  ConfirmDrawer,
  RoomHeader,
  RoomShell,
  RoomTabs,
  SectionHeader,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { StageStartAction } from "../../components/composites/StagePlaceholder";
import { FlowingDotsPlaceholder } from "../../components/ui/FlowingDotsPlaceholder";
import { StatusPill } from "../../components/ui/StatusPill";
import { Surface } from "../../components/ui/Surface";
import { StateBlock } from "../../components/ui/StateBlock";
import { useI18n } from "../../i18n";
import { getImageFailureCopy } from "../../lib/imageFailure";
import type {
  CompletePageSummary,
  GenerationJob,
} from "../../types/api";
import { RevisionDraft } from "../../components/pages/RevisionDraft";
import { StaleRenderRedraw } from "../../components/pages/StaleRenderRedraw";
import { PageCheckRecovery } from "../../components/pages/PageCheckRecovery";
import { OutOfDatePages } from "../../components/pages/OutOfDatePages";
import { StageFailureSummary } from "../../components/pages/StageFailureSummary";
import { PageSourcePanel } from "../../components/pages/PageSourcePanel";
import { PageChecks, type DraftSeed } from "../../components/pages/PageChecks";
import type { DrawerKind } from "../../lib/stations";
import { BottomBarPortal } from "../../layout/TopBarSlot";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { useBackdropDismiss } from "../../hooks/useBackdropDismiss";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { seriesPath } from "../../api/projectScope";
import { PartNotices } from "../../components/parts/PartNotices";
import { describeRedrawChanges } from "../../components/pages/redrawChanges";

type ReviewView = "page" | "lettering" | "history";
type PageFilter = "all" | "needs-review" | "drawing" | "failed";
type PaidPageIntent =
  | { kind: "batch"; retry?: boolean }
  | { kind: "page"; pageNumber: number; depiction: "canonical" | "less_graphic" }
  | { kind: "analysis"; pageNumber: number };

function needsReview(item: CompletePageSummary) {
  return item.issues.some((issue) => issue.status === "open" || issue.status === "revised");
}

function PageSpendConsent({
  project, intent, busy, error, onConfirm, onClose,
}: {
  project: string;
  intent: PaidPageIntent;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const batch = useCompletePageBatchEstimate(project, intent.kind === "batch");
  const page = useCompletePageEstimate(
    project, intent.kind === "page" ? intent.pageNumber : undefined,
    intent.kind === "page" ? intent.depiction : "canonical", intent.kind === "page",
  );
  const analysis = usePageAnalysisEstimate(
    project, intent.kind === "analysis" ? intent.pageNumber : undefined, intent.kind === "analysis",
  );
  const estimate = intent.kind === "batch" ? batch : intent.kind === "page" ? page : analysis;
  const retryBatch = intent.kind === "batch" && intent.retry === true;
  return (
    <ConfirmDrawer
      open
      title={intent.kind === "batch" ? retryBatch ? t("Retry the remaining pages?") : t("Queue all undrawn pages?") : `${t("Page")} ${intent.pageNumber}`}
      body={intent.kind === "batch"
        ? retryBatch
          ? t("Only pages without a saved render will be queued. Completed artwork stays available to review.")
          : t("This starts drawing the remaining pages now. Completed artwork stays available to review.")
        : intent.kind === "analysis"
          ? t("Run the text check again on this render. This does not redraw the page.")
          : intent.depiction === "less_graphic"
            ? t("Draw a less graphic version of this page while keeping required identity references.")
            : t("Draw one complete page of artwork. Editable lettering is added without an image charge.")}
      cost={estimate.data}
      confirmLabel={intent.kind === "batch" ? retryBatch ? t("CONFIRM RETRY") : t("CONFIRM QUEUE") : intent.kind === "analysis" ? t("CONFIRM TEXT CHECK") : t("CONFIRM DRAW")}
      busy={busy || estimate.isFetching || !estimate.data || !!estimate.error}
      onConfirm={() => { if (estimate.data && !estimate.error && !estimate.isFetching && !busy) onConfirm(); }}
      onClose={onClose}
      extraBody={(
        <div className="space-y-3">
          {!estimate.data && !estimate.error && <p role="status">{t("Loading immediate estimate and hold…")}</p>}
          {estimate.error && (
            <div role="alert" className="space-y-2 text-sm text-hero-red">
              <p>{t("The cost could not be loaded. Nothing has been started.")} {estimate.error.message}</p>
              <Button variant="outline" size="sm" onClick={() => void estimate.refetch()}>{t("RETRY ESTIMATE")}</Button>
            </div>
          )}
          {error && <p role="alert" className="text-sm text-hero-red">{error}</p>}
        </div>
      )}
    />
  );
}

function PageReview({
  project,
  item,
  onClose,
  onJobQueued,
  pageIsDrawing,
  view,
  onViewChange,
  previousPage,
  nextPage,
  nextUnresolved,
  onNavigate,
  onCheckText,
  checkingText,
  checkError,
  deliberateView,
}: {
  project: string;
  item: CompletePageSummary;
  onClose: () => void;
  onJobQueued: (jobId: string, pageNumber: number) => void;
  pageIsDrawing: boolean;
  view: ReviewView;
  onViewChange: (view: ReviewView) => void;
  previousPage?: number;
  nextPage?: number;
  nextUnresolved?: number;
  onNavigate: (pageNumber: number) => void;
  onCheckText: () => void;
  checkingText: boolean;
  checkError?: string;
  deliberateView: boolean;
}) {
  const { t } = useI18n();
  const viewed = useRef(new Set<string>());
  // Canonical page revision being corrected; the redraw starts from the
  // active render revision. The render's own parent is comparison only.
  const comicPageRevision = item.page.revision;
  const editSourceRevision = item.active_render?.render.revision ?? null;
  const compareRevision = item.active_render?.render.parent_revision ?? null;
  // Re-planned after drawing: the art belongs to an earlier plan revision.
  const renderStale = editSourceRevision != null && item.analysis_recovery?.status === "stale_render";
  // Integrated editions carry their lettering in the art; there is nothing to edit separately.
  const editableLettering = item.lettering_mode === "hybrid";
  const shownView: ReviewView = view === "lettering" && !editableLettering ? "page" : view;
  const [visualSeeds, setVisualSeeds] = useState<DraftSeed[]>([]);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useDialogFocus(panelRef, { onClose });
  const backdrop = useBackdropDismiss(onClose);

  function selectView(next: ReviewView) {
    onViewChange(next);
    // Each view starts at the top of the modal body; the header stays put.
    const scroller = bodyRef.current;
    if (scroller) {
      if (typeof scroller.scrollTo === "function") scroller.scrollTo({ top: 0 });
      else scroller.scrollTop = 0;
    }
  }

  function addVisualSeeds(seeds: DraftSeed[]) {
    setVisualSeeds((current) => [...current, ...seeds]);
    // Explicit "add to changes" visibly opens the editor holding the seeds.
    selectView("page");
  }
  return createPortal(
    <section
      role="dialog"
      aria-modal="true"
      aria-label={`${t("Page")} ${item.page.page_number} ${t("review")}`}
      className="fixed inset-0 z-[120] flex justify-center bg-ink-black/75 p-0 sm:p-3 md:p-6"
      {...backdrop}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex max-h-full w-full max-w-[1800px] flex-col bg-pulp-paper lg:h-full shadow-ink focus-visible:outline-none sm:border-[3px] sm:border-ink-black"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="shrink-0 bg-bristol">
          <header className="flex items-start justify-between gap-3 px-4 pb-4 pt-5 sm:px-6 sm:pt-6">
            <div className="min-w-0">
              <h2 className="font-display text-2xl font-black uppercase leading-none tracking-[-0.03em] sm:text-3xl">
                {t("Page")} {item.page.page_number}
              </h2>
              <p className="mt-2 max-w-[22rem] font-meta text-[10px] leading-relaxed text-ink-muted sm:text-xs">
                {t("Revision")} {editSourceRevision ?? comicPageRevision}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2 sm:gap-4">
              <nav aria-label={t("Review navigation")} className="flex gap-1">
                <button type="button" className="flex size-11 items-center justify-center bg-pulp-paper text-ink-black transition-colors hover:bg-ink-black hover:text-bristol disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-pulp-paper disabled:hover:text-ink-black" aria-label={t("PREVIOUS PAGE")} title={t("PREVIOUS PAGE")} disabled={previousPage == null} onClick={() => previousPage != null && onNavigate(previousPage)}>
                  <ReviewChevronLeft size={20} aria-hidden="true" />
                </button>
                <button type="button" className="flex size-11 items-center justify-center bg-pulp-paper text-ink-black transition-colors hover:bg-ink-black hover:text-bristol disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-pulp-paper disabled:hover:text-ink-black" aria-label={t("NEXT PAGE")} title={t("NEXT PAGE")} disabled={nextPage == null} onClick={() => nextPage != null && onNavigate(nextPage)}>
                  <ReviewChevronRight size={20} aria-hidden="true" />
                </button>
              </nav>
              <button type="button" className="flex size-11 items-center justify-center text-ink-muted transition-colors hover:bg-pulp-paper hover:text-ink-black" onClick={onClose} aria-label={t("Close page review")} title={t("CLOSE")}>
                <ReviewClose size={20} aria-hidden="true" />
              </button>
            </div>
          </header>
          <div className="flex flex-wrap items-center justify-between gap-x-4 bg-surface-container px-4 sm:px-6">
            <RoomTabs
            ariaLabel={`${t("Page")} ${item.page.page_number} ${t("sections")}`}
            className="min-w-0 max-w-full gap-1 py-2 [&>button]:border-0 [&>button]:px-3 [&>button]:tracking-normal sm:[&>button]:px-4"
            tabs={[
              {
                key: "page",
                label: t("Page"),
                active: shownView === "page",
                onClick: () => selectView("page"),
              },
              ...(editableLettering ? [{
                key: "lettering",
                label: t("Lettering"),
                active: shownView === "lettering",
                onClick: () => selectView("lettering"),
                disabled: editSourceRevision == null,
              }] : []),
              {
                key: "history",
                label: t("History"),
                active: shownView === "history",
                onClick: () => selectView("history"),
              },
            ]}
          />
            {nextUnresolved != null && <button type="button" className="mb-2 flex min-h-11 items-center gap-2 font-meta text-[11px] font-bold tracking-[0.04em] text-ink-black underline decoration-ink-black/30 underline-offset-4 transition-colors hover:text-hero-red disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-ink-black sm:mb-0" disabled={nextUnresolved == null} onClick={() => nextUnresolved != null && onNavigate(nextUnresolved)}>
              {t("NEXT UNRESOLVED")} <ReviewChevronRight size={16} aria-hidden="true" />
            </button>}
          </div>
        </div>
        <div ref={bodyRef} className={`min-h-0 flex-1 overflow-y-auto ${shownView === "lettering" ? "lettering-modal-body" : ""}`}>
          {/* On wide screens the page and history views fill the window and their columns scroll on their own. */}
          <div className={`space-y-7 p-4 lg:p-6 ${shownView === "lettering" ? "" : "lg:flex lg:h-full lg:flex-col"}`}>
            {(renderStale || !!item.redraw?.changed_references.length) && !pageIsDrawing && (
              <StaleRenderRedraw project={project} pageNumber={item.page.page_number}
                changedLooks={renderStale || !item.redraw ? undefined : describeRedrawChanges(item.redraw.changed_references, t)}
                onJobQueued={(jobId) => onJobQueued(jobId, item.page.page_number)} />
            )}
            {/* Revision draft stays mounted while hidden so unsaved changes survive tab switches. */}
            <div hidden={shownView !== "page"} role="region" aria-label={t("Page")} className="lg:min-h-0 lg:flex-1">
              {editSourceRevision != null ? (
                <RevisionDraft
                  key={`${project}:${item.page.page_number}:${comicPageRevision}:${editSourceRevision}`}
                  project={project}
                  pageNumber={item.page.page_number}
                  comicPageRevision={comicPageRevision}
                  parentRenderRevision={editSourceRevision}
                  comicPageSha256={item.page.content_sha256}
                  compareRevision={compareRevision}
                  issues={item.issues}
                  seeds={visualSeeds}
                  onSeedsConsumed={() => setVisualSeeds([])}
                  onJobQueued={(jobId) => onJobQueued(jobId, item.page.page_number)}
                  onArtworkLoaded={() => {
                    const key = `${project}:${item.page.page_number}:${editSourceRevision}`;
                    if (deliberateView && shownView === "page" && !viewed.current.has(key)) {
                      viewed.current.add(key);
                      void trackProductEvent("page_viewed", { projectId: project, properties: {
                        page_number: item.page.page_number, render_revision: editSourceRevision,
                      } });
                    }
                  }}
                  disabled={pageIsDrawing}
                  aside={!renderStale && (
                    <PageChecks
                      project={project}
                      item={item}
                      pageIsDrawing={pageIsDrawing}
                      onFix={addVisualSeeds}
                      onRetryText={onCheckText}
                      retryingText={checkingText}
                      retryTextError={checkError ? t("Text could not be checked. Your artwork is saved and you can continue to export.") : undefined}
                    />
                  )}
                />
              ) : (
                <Surface padding="lg" border="soft" shadow="none">
                  <p>{t("This page has not been drawn yet.")}</p>
                </Surface>
              )}
            </div>

            {shownView === "history" && (
              <div role="region" aria-label={t("History")}
                className="grid gap-8 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,3fr)_minmax(20rem,2fr)] lg:grid-rows-[minmax(0,1fr)]">
                <div className="min-w-0 lg:min-h-0">
                  <PageVersions
                    key={`${project}:${item.page.page_number}`}
                    project={project} pageNumber={item.page.page_number}
                    activeRevision={editSourceRevision} disabled={pageIsDrawing}
                    onSelected={() => selectView("page")}
                  />
                </div>
                <div className="min-w-0 border-t border-ink-black/15 pt-6 lg:min-h-0 lg:overflow-y-auto lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
                  <PageSourcePanel project={project} item={item} />
                </div>
              </div>
            )}

            {shownView === "lettering" && editSourceRevision != null && !renderStale && <LetteringEditor project={project} pageNumber={item.page.page_number} disabled={pageIsDrawing}/>}
          </div>
        </div>
      </div>
    </section>,
    document.body,
  );
}

export function PagesRoom() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { data: status } = useProjectStatus(id);
  const planFailed = status?.stages.plan?.status === "failed";
  const adaptFailed = status?.stages.adapt?.status === "failed";
  const { data: planValidation } = useStageValidation(id, "plan", planFailed);
  const { data: adaptValidation } = useStageValidation(id, "adapt", adaptFailed);
  const planNeedsAdapt = planFailed && (planValidation?.invariant_failures.some(
    (failure) => failure.owner_stage === "adapt",
  ) ?? false);
  const { data, isLoading, error, refetch } = useCompletePages(id);
  const run = useRunPipeline();
  const generate = useGenerateCompletePage();
  const analyze = useAnalyzeCompletePage();
  const approve = useApproveStage();
  const { data: styles } = useStyles(id);
  const selectedStyle = styles?.suggestions.find((style) => style.is_active);
  const [searchParams, setSearchParams] = useSearchParams();
  const pageParam = searchParams.get("page") ?? "";
  const selected = /^[1-9]\d*$/.test(pageParam) && Number.isSafeInteger(Number(pageParam)) ? Number(pageParam) : null;
  const reviewParam = searchParams.get("review");
  const review: ReviewView = reviewParam === "lettering" || reviewParam === "history" ? reviewParam : "page";
  const filterParam = searchParams.get("filter");
  const filter: PageFilter = filterParam === "needs-review" || filterParam === "drawing" || filterParam === "failed" ? filterParam : "all";
  const readingParam = searchParams.get("reading");
  const reading: DrawerKind | null = readingParam === "adaptation" || readingParam === "page-plan" ? readingParam : null;
  const readingAvailable = reading !== null && canReadDocument(reading, status);
  useEffect(() => {
    if (!status || !reading || readingAvailable) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("reading");
      return next;
    }, { replace: true });
  }, [status, reading, readingAvailable, setSearchParams]);
  const restoredProject = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!id || restoredProject.current === id) return;
    restoredProject.current = id;
    if (searchParams.size > 0) return;
    try {
      const saved = sessionStorage.getItem(`page-review:v2:${accountIdentity ?? "signed-out"}:${id}`);
      if (saved) setSearchParams(new URLSearchParams(saved), { replace: true });
    } catch { /* Storage is optional; the URL remains authoritative. */ }
  }, [id, searchParams, setSearchParams]);

  const [deliberatePage, setDeliberatePage] = useState<string | null>(null);
  function updateContext(changes: Record<string, string | null>) {
    if ("page" in changes) setDeliberatePage(changes.page);
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value == null) next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next, { replace: !("reading" in changes) });
    setRevealedPage(null);
    try {
      const saved = new URLSearchParams(next);
      saved.delete("reading");
      sessionStorage.setItem(`page-review:v2:${accountIdentity ?? "signed-out"}:${id}`, saved.toString());
    } catch { /* Private browsing must not block review. */ }
  }

  const [pageJobs, setPageJobs] = useState<Record<string, number>>({});
  const [startingPages, setStartingPages] = useState<number[]>([]);
  const [batchPages, setBatchPages] = useState<number[]>([]);
  const [pageFailures, setPageFailures] = useState<Partial<Record<number, GenerationJob>>>({});
  const [paidIntent, setPaidIntent] = useState<PaidPageIntent | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pageActionErrors, setPageActionErrors] = useState<Partial<Record<number, string>>>({});
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const cancelQueued = useCancelQueuedPageJobs();
  const { data: generationJobs, isLoading: generationJobsLoading } = useGenerationJobs(id, [], true);
  const observedTerminalJobs = useRef(new Set<string>());
  const firstArtworkObserved = useRef<boolean | null>(null);
  const [revealedPage, setRevealedPage] = useState<number | null>(null);
  const latestPageJobs = new Map<number, GenerationJob>();
  for (const job of generationJobs?.jobs ?? []) {
    if (job.is_current_page === false) continue;
    if (job.kind !== "complete_page_draw" && pageJobs[job.id] == null) continue;
    const pageNumber = Number(job.payload?.page_number ?? pageJobs[job.id]);
    if (!Number.isSafeInteger(pageNumber) || pageNumber < 1) continue;
    const previous = latestPageJobs.get(pageNumber);
    if (!previous || Date.parse(job.queued_at) >= Date.parse(previous.queued_at)) latestPageJobs.set(pageNumber, job);
  }

  const drawStatus = status?.stages.draw?.status ?? "pending";
  const interruptedStage = status?.stages.adapt?.status !== "complete"
    ? "adapt"
    : planNeedsAdapt
      ? "adapt"
    : status?.stages.plan?.status !== "complete"
      ? "plan"
      : "draw";
  const interruptedStageInfo = status?.stages[interruptedStage];
  const interruptedStatus = planNeedsAdapt
    ? "failed"
    : interruptedStageInfo?.status ?? "pending";
  const selectedItem = data?.pages.find((item) => item.page.page_number === selected);

  useEffect(() => {
    const terminal = (generationJobs?.jobs ?? []).filter((job) =>
      job.is_current_page !== false
      && (job.kind === "complete_page_draw" || pageJobs[job.id] != null)
      && (job.status === "complete" || job.status === "failed" || job.status === "cancelled")
      && !observedTerminalJobs.current.has(job.id),
    );
    if (terminal.length === 0) return;
    terminal.forEach((job) => observedTerminalJobs.current.add(job.id));
    void refetch().then(() => {
      const donePages = terminal.map((job) => Number(job.payload?.page_number ?? pageJobs[job.id]));
      setBatchPages((current) => current.filter((page) => !donePages.includes(page)));
      setPageFailures((current) => {
        const next = { ...current };
        terminal.forEach((job) => {
          const pageNumber = Number(job.payload?.page_number ?? pageJobs[job.id]);
          if (job.status === "failed") next[pageNumber] = job;
          else delete next[pageNumber];
        });
        return next;
      });
      setPageJobs((current) => {
        const next = { ...current };
        terminal.forEach((job) => delete next[job.id]);
        return next;
      });
    });
  }, [generationJobs?.jobs, pageJobs, refetch]);

  useEffect(() => {
    if (!data) return;
    const artwork = data.pages.find((item) => item.active_render);
    if (firstArtworkObserved.current === null) {
      firstArtworkObserved.current = !!artwork;
    } else if (!firstArtworkObserved.current && artwork) {
      firstArtworkObserved.current = true;
      if (filter === "all" || (filter === "needs-review" && needsReview(artwork))) {
        setRevealedPage(artwork.page.page_number);
      }
    }
  }, [data, filter]);

  if (id && reading && readingAvailable) {
    return <ReadingWorkspace project={id} kind={reading} status={status}
      onKindChange={(kind) => updateContext({ reading: kind })}
      onClose={() => {
        updateContext({ reading: null });
        requestAnimationFrame(() => {
          document.querySelector<HTMLButtonElement>(`[data-reading-kind="${reading}"]`)?.focus();
        });
      }} />;
  }

  if (isLoading && drawStatus !== "pending") {
    return (
      <RoomShell
        project={id ?? ""}
        isLoading
        loadingText={t("PREPARING COMPLETE PAGES…")}
        loadingStage="draw"
        loadingStageStatus={drawStatus}
      />
    );
  }

  // Starting over only makes sense once a first adaptation and page plan
  // have finished (or the plan failed); never while that first run is going.
  const rerunAdaptation = id && status && status.stages.adapt?.status === "complete"
    && ["complete", "failed"].includes(status.stages.plan?.status ?? "pending") ? (
    <RerunStageAction
      project={id}
      stage="adapt"
      label="adaptation"
      disabled={!!status.is_running || !status.style_selected || generationJobsLoading
        || (generationJobs?.jobs ?? []).some((job) => job.status === "queued" || job.status === "running")}
    />
  ) : null;

  if (!id || error || !data) {
    if (id && status && interruptedStage === "adapt" && (
      status.stages.brief?.status !== "complete" || status.stages.brief?.approved !== true
    )) {
      return (
        <RoomShell project={id}>
          <StateBlock
            title={t("Approve your brief first")}
            description={t("Your revised brief is waiting for approval in Story. Approve it there before adaptation can start.")}
            action={<Button onClick={() => navigate(`/project/${id}/story`)}>{t("Review and approve brief")}</Button>}
          />
        </RoomShell>
      );
    }
    return (
      <RoomShell project={id ?? ""}>
        <StagePlaceholder
          activeJobs={status?.active_jobs}
          project={id ?? ""}
          stage={interruptedStage}
          status={interruptedStatus}
          stale={interruptedStageInfo?.stale}
          itemsDone={interruptedStageInfo?.items_done}
          itemsTotal={interruptedStageInfo?.items_total}
          startedAt={interruptedStageInfo?.started_at}
          snapshot={interruptedStageInfo?.snapshot}
          firstPhase={interruptedStage === "plan" ? status?.stages.adapt : undefined}
          retryAsRerun={planNeedsAdapt}
          allowPendingStart={interruptedStage === "adapt"}
          error={interruptedStageInfo?.error}
          errorDetail={interruptedStageInfo?.error_detail}
          errorCode={interruptedStageInfo?.error_code}
        />
        <StageFailureSummary recoveryStage={interruptedStage === "adapt" ? "adapt" : "plan"} failures={[
          ...(adaptFailed ? adaptValidation?.invariant_failures ?? [] : []),
          ...(planFailed ? planValidation?.invariant_failures ?? [] : []),
        ]} />
        {rerunAdaptation && <BottomBarPortal>
          <footer className="flex min-h-shell-footer flex-wrap items-center justify-end gap-3 border-t-[3px] border-ink-black bg-bristol px-4 py-3 shadow-[0_-4px_0_0_var(--color-ghost-shadow)] md:pr-6">
            {planFailed && !planNeedsAdapt ? <StageStartAction
              project={id ?? ""}
              stage="adapt"
              layout="footer"
              secondaryAction={rerunAdaptation}
              retry
              allowRestart={false}
              disabled={!!status?.is_running || !status?.style_selected || generationJobsLoading
                || (generationJobs?.jobs ?? []).some((job) => job.status === "queued" || job.status === "running")}
            /> : rerunAdaptation}
          </footer>
        </BottomBarPortal>}
        {id && <ArchivedArtwork project={id} />}
      </RoomShell>
    );
  }
  const projectId = id;
  const pages = data.pages;
  const drawingPages = new Set(startingPages);
  if (drawStatus !== "failed") batchPages.forEach((page) => drawingPages.add(page));
  Object.values(pageJobs).forEach((page) => drawingPages.add(page));
  latestPageJobs.forEach((job, page) => {
    if (job.status === "queued" || job.status === "running") drawingPages.add(page);
  });
  const failedPages = new Set(pages.filter((item) => {
    if (drawingPages.has(item.page.page_number)) return false;
    if (item.active_render) return false;
    const job = latestPageJobs.get(item.page.page_number);
    return job?.status === "failed" || !!pageFailures[item.page.page_number] || !!item.failure;
  }).map((item) => item.page.page_number));
  const drawnPages = pages.filter((item) => item.active_render);
  const undrawnPages = pages.filter((item) => !item.active_render);
  const pagesWaitingToDraw = undrawnPages.filter((item) => !drawingPages.has(item.page.page_number));
  const queuedPageJobs = (generationJobs?.jobs ?? []).filter((job) =>
    job.kind === "complete_page_draw" && job.is_current_page !== false && job.status === "queued",
  );
  const retryingDraw = undrawnPages.some((item) => failedPages.has(item.page.page_number))
    || drawStatus === "failed"
    || !!status?.stages.draw?.stale;
  const unresolvedPages = pages.filter(needsReview);
  // A page being drawn is read in the same job; only settled pages can still be unchecked.
  const uncheckedPages = pages.filter((item) => item.active_render && item.analysis_recovery?.status !== "checked" && !drawingPages.has(item.page.page_number));
  const visiblePages = pages.filter((item) => filter === "all"
    || (filter === "needs-review" && needsReview(item))
    || (filter === "drawing" && drawingPages.has(item.page.page_number))
    || (filter === "failed" && failedPages.has(item.page.page_number)));
  const reviewIndex = pages.findIndex((item) => item.page.page_number === selected);
  const nextUnresolved = [...unresolvedPages.filter((item) => item.page.page_number > (selected ?? 0)),
    ...unresolvedPages.filter((item) => item.page.page_number < (selected ?? 0))][0]?.page.page_number;

  function requestSpend(intent: PaidPageIntent) {
    setActionError(null);
    setPaidIntent(intent);
  }

  function continueToBook() {
    if (!id) return;
    setApprovalError(null);
    approve.mutate(
      { project: id, stage: "draw" },
      {
        onSuccess: () => navigate(`/project/${encodeURIComponent(id)}/book`),
        onError: (error) => setApprovalError(error.message),
      },
    );
  }

  function drawPage(
    pageNumber: number,
    depiction: "canonical" | "less_graphic" = "canonical",
  ) {
    if (!status?.style_selected || startingPages.includes(pageNumber)) return;
    setActionError(null);
    setPageActionErrors((current) => ({ ...current, [pageNumber]: undefined }));
    setStartingPages((current) => (
      current.includes(pageNumber) ? current : [...current, pageNumber]
    ));
    setPageFailures((current) => {
      const next = { ...current };
      delete next[pageNumber];
      return next;
    });
    generate.mutate(
      depiction === "canonical"
        ? { project: projectId, pageNumber }
        : { project: projectId, pageNumber, depiction },
      {
        onSuccess: ({ job }) => {
          setPaidIntent(null);
          setStartingPages((current) => current.filter((page) => page !== pageNumber));
          setPageJobs((current) => ({
            ...current,
            [job.id]: pageNumber,
          }));
        },
        onError: (error) => {
          setActionError(error.message);
          setPageActionErrors((current) => ({ ...current, [pageNumber]: error.message }));
          maybeShowInsufficientCredits(error, {
            actionLabel: `${t("Draw page")} ${pageNumber}`,
            onRetry: () => requestSpend({ kind: "page", pageNumber, depiction }),
          });
          setStartingPages((current) => current.filter((page) => page !== pageNumber));
        },
      },
    );
  }

  function startDraw(queuePages: boolean, retry = false) {
    if (!status?.style_selected || run.isPending) return;
    setActionError(null);
    const undrawnPages = pages
      .filter((item) => !item.active_render)
      .map((item) => item.page.page_number);
    run.mutate(
      { project: projectId, stage: "draw", queuePages },
      {
        onSuccess: () => {
          if (queuePages) setBatchPages(undrawnPages);
          setPaidIntent(null);
        },
        onError: (error) => {
          setActionError(error.message);
          maybeShowInsufficientCredits(error, {
            actionLabel: t(retry ? "RETRY ALL INCOMPLETE PAGES" : "QUEUE ALL PAGES"),
            onRetry: () => requestSpend({ kind: "batch", retry }),
          });
          if (queuePages) setBatchPages([]);
        },
      },
    );
  }

  function retryAnalysis(pageNumber: number) {
    setActionError(null);
    analyze.mutate({ project: projectId, pageNumber }, {
      onSuccess: () => {
        setPaidIntent(null);
        setPageFailures((current) => ({ ...current, [pageNumber]: undefined }));
        setPageActionErrors((current) => ({ ...current, [pageNumber]: undefined }));
      },
      onError: (error) => {
        setActionError(error.message);
        setPageActionErrors((current) => ({ ...current, [pageNumber]: error.message }));
        maybeShowInsufficientCredits(error, {
          actionLabel: t("RETRY TEXT CHECK"),
          onRetry: () => requestSpend({ kind: "analysis", pageNumber }),
        });
      },
    });
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker={t("PAGES")}
        title={t("REVIEW COMPLETE PAGES")}
        lead={t("Each thumbnail is one fully lettered page. Corrections always create a complete new revision.")}
      />
      <PartNotices status={status} project={id} />
      <section className="grid gap-6 bg-ink-black p-6 text-pulp-paper shadow-paper md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] md:p-8">
        <div>
          <h2 className="font-display text-3xl font-black uppercase leading-tight tracking-[-0.03em] md:text-4xl">{t("Your story, page by page")}</h2>
          <p className="mt-3 font-body text-sm leading-7 text-pulp-paper/85">{t("Read the edition as it comes to life. Open a page for a closer look, review flagged findings, or shape the next revision.")}</p>
          <div className="mt-5 flex flex-wrap gap-3">
            {unresolvedPages.length > 0 ? <Button variant="onInk" size="sm" onClick={() => updateContext({ filter: "needs-review", page: String(unresolvedPages[0].page.page_number), review: "page" })}>{t("REVIEW FLAGGED PAGES")} ({unresolvedPages.length})<ArrowUpRight size={16} aria-hidden="true" /></Button>
              : drawnPages.length > 0 && <Button variant="onInk" size="sm" onClick={() => updateContext({ page: String(drawnPages[0].page.page_number), review: "page" })}><BookOpen size={16} aria-hidden="true" />{t("Start reading")}</Button>}
          </div>
        </div>
        <div className="flex flex-col justify-center bg-pulp-paper/10 p-5">
          <p className="font-meta text-sm font-bold">{t("{drawn} of {total} pages drawn", { drawn: String(drawnPages.length), total: String(pages.length) })}</p>
          <progress aria-label={t("Drawing progress")} value={drawnPages.length} max={Math.max(1, pages.length)} className="mt-3 h-2 w-full overflow-hidden [&::-webkit-progress-bar]:bg-pulp-paper/20 [&::-webkit-progress-value]:bg-narrator-gold [&::-moz-progress-bar]:bg-narrator-gold" />
          <p className="mt-3 font-body text-xs leading-6 text-pulp-paper/85">{t("Open completed pages to check the artwork and lettering.")}</p>
          {status?.style_selected && selectedStyle && <div className="mt-4 flex items-center gap-3">
            {selectedStyle.has_sample && <img src={`/api${seriesPath(id)}/files/samples/style_${selectedStyle.index}.png`} alt="" className="h-14 w-11 shrink-0 object-contain" />}
            <p className="font-body text-xs leading-6"><span className="block font-meta text-narrator-gold">{t("Visual direction")}</span>{selectedStyle.label}</p>
          </div>}
        </div>
      </section>
      {!status?.style_selected && <p role="status" className="mb-4 text-sm">{t("Select a visual direction in Look before drawing pages.")}</p>}

      <section aria-label={t("Page gallery")}>
        <SectionHeader
          variant="underline"
          title={t("PAGE GALLERY")}
          description={`${data.pages.length} ${t("planned pages")}`}
          actions={(
            <>
              <Button
                variant="outline"
                size="xs"
                data-reading-kind="adaptation"
                disabled={!canReadDocument("adaptation", status)}
                onClick={() => updateContext({ reading: "adaptation" })}
              >
                {t("BOOK ADAPTATION")}
              </Button>
              <Button
                variant="outline"
                size="xs"
                data-reading-kind="page-plan"
                disabled={!canReadDocument("page-plan", status)}
                onClick={() => updateContext({ reading: "page-plan" })}
              >
                {t("PAGE PLAN")}
              </Button>
            </>
          )}
        />
        {drawStatus === "failed" && status?.stages.draw?.error && (
          <p role="alert" className="mb-5 text-sm text-hero-red">{status.stages.draw.error}</p>
        )}
        {drawStatus === "pending" && (
          <Surface tone="pulp" padding="md" className="mb-5">
            <div className="flex flex-wrap items-end justify-between gap-5">
              <div className="min-w-0 flex-1 basis-80">
                <h3 className="font-body text-base font-bold text-ink-black">
                  {t("How do you want to draw this edition?")}
                </h3>
                <p className="mt-1 text-sm leading-6 text-ink-muted">
                  {t("Queue every page now, or prepare the edition and generate pages one at a time while you review.")}
                </p>
                <p className="mt-2 text-sm leading-6 text-ink-muted">{t("One by one prepares the edition without drawing. Each paid draw waits for your cost confirmation.")}</p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  onClick={() => startDraw(false)}
                  disabled={run.isPending || !status?.style_selected}
                >
                  {t("GO ONE BY ONE")}
                </Button>
                <Button
                  variant="primary"
                  onClick={() => requestSpend({ kind: "batch" })}
                  disabled={run.isPending || !status?.style_selected}
                >
                  {t("QUEUE ALL PAGES")}
                </Button>
              </div>
            </div>
            {actionError && !paidIntent && <p role="alert" className="mt-3 text-sm">{actionError}</p>}
          </Surface>
        )}
        {drawStatus !== "pending" && !generationJobsLoading && pagesWaitingToDraw.length > 0 && (
          <Surface tone="pulp" padding="md" className="mb-5">
            <div className="flex flex-wrap items-end justify-between gap-5">
              <div className="min-w-0 flex-1 basis-80">
                <h3 className="font-body text-base font-bold text-ink-black">{t("Finish drawing the edition")}</h3>
                <p className="mt-1 text-sm leading-6 text-ink-muted">
                  {t("{count, plural, one {One page still needs artwork. Completed pages are saved. Queue it after reviewing the current estimate.} other {# pages still need artwork. Completed pages are saved. Queue the unfinished pages together after reviewing the current estimate.}}", { count: pagesWaitingToDraw.length })}
                </p>
                {drawingPages.size > 0 && <p className="mt-2 text-sm leading-6 text-ink-muted">{t("Wait for the current page to finish before queuing the rest.")}</p>}
              </div>
              <Button
                variant="primary"
                onClick={() => requestSpend({
                  kind: "batch",
                  retry: retryingDraw,
                })}
                disabled={run.isPending || !status?.style_selected || drawingPages.size > 0 || !!status?.is_running}
              >
                {t("DRAW REMAINING PAGES")}
              </Button>
            </div>
          </Surface>
        )}
        {(data?.redraws?.length ?? 0) > 0 && (
          <div className="mb-5">
            <OutOfDatePages project={id} redraws={(data?.redraws ?? []).filter((page) => !drawingPages.has(page.page_number))}
              disabled={drawingPages.size > 0 || !!status?.is_running}
              onQueued={(jobs) => setPageJobs((current) => ({
                ...current, ...Object.fromEntries(jobs.map(({ page_number, job }) => [job.id, page_number])),
              }))} />
          </div>
        )}
        {drawingPages.size > 0 && (
          <Surface tone="pulp" border="soft" shadow="none" padding="md" className="mb-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p role="status" className="text-sm font-bold">{drawingPages.size} {t("pages drawing or queued")}</p>
              {queuedPageJobs.length > 0 && <Button
                variant="outline"
                size="sm"
                disabled={cancelQueued.isPending}
                onClick={() => cancelQueued.mutate(id)}
              >{cancelQueued.isPending ? t("CANCELLING QUEUED PAGES…") : t("CANCEL QUEUED PAGES")} ({queuedPageJobs.length})</Button>}
            </div>
            <p className="mt-1 text-sm text-ink-muted">{t("Completed pages are ready to inspect while the press continues.")}</p>
            {cancelQueued.error && <p role="alert" className="mt-2 text-sm text-hero-red">{cancelQueued.error.message}</p>}
            <div className="mt-3 flex gap-3 overflow-x-auto">
              {pages.filter((item) => item.active_render).map((item) => (
                <button key={item.page.page_number} type="button" className="w-20 shrink-0 p-1 text-center text-xs font-bold" onClick={() => updateContext({ page: String(item.page.page_number), review: "page" })} aria-label={`${t("Inspect completed page")} ${item.page.page_number}`}>
                  <img src={item.lettering_mode === "hybrid" ? pageCompositePreviewUrl(id, item.page.page_number, item.active_render!.render.revision, "thumbnail", item.lettering_revision) : pageRenderPreviewUrl(id, item.page.page_number, item.active_render!.render.revision, "thumbnail")} alt="" className="mb-2 aspect-[2/3] w-full object-contain" />
                  {t("Page")} {item.page.page_number}
                </button>
              ))}
            </div>
          </Surface>
        )}
        <div role="group" aria-label={t("Filter pages")} className="mb-6 flex flex-wrap gap-2 bg-surface-container p-3">
          {([
            ["all", t("All"), pages.length],
            ["needs-review", t("Needs review"), unresolvedPages.length],
            ["drawing", t("Drawing"), drawingPages.size],
            ["failed", t("Failed"), failedPages.size],
          ] as const).map(([value, label, count]) => (
            <Button key={value} variant={filter === value ? "secondary" : "outline"} size="sm" aria-pressed={filter === value} onClick={() => updateContext({ filter: value })}>
              {label} ({count})
            </Button>
          ))}
        </div>
        {visiblePages.length === 0 && <p role="status" className="mb-6 text-sm text-ink-muted">{t("No pages in this filter.")}</p>}
        <WholeBookReveal
          ready={filter === "all" && pages.length > 1 && drawnPages.length === pages.length && drawingPages.size === 0}
          editionKey={editionKeyFor(projectId, pages.map((item) => item.page))}
          className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,250px),1fr))] gap-5"
        >
          {visiblePages.map((item) => {
            const revision = item.active_render?.render.revision;
            const pageIsDrawing = drawingPages.has(item.page.page_number);
            const revisedIssues = item.issues.some((issue) => issue.status === "revised");
            const openIssueCount = item.issues.filter((issue) => issue.status === "open").length;
            const serverJob = latestPageJobs.get(item.page.page_number);
            const pageFailure = item.analysis_recovery?.status === "checked" ? null
              : item.failure ?? pageFailures[item.page.page_number] ?? (serverJob?.status === "failed" ? serverJob : null);
            const failurePhase = revision && item.analysis_recovery?.status !== "checked"
              ? "analysis" : pageFailure?.phase;
            const failureCopy = pageFailure && !revision && !pageIsDrawing
              ? getImageFailureCopy(
                  t,
                  failurePhase === "analysis" ? "analysis_error" : pageFailure.classification,
                  failurePhase === "analysis" ? undefined : pageFailure.user_message,
                  failurePhase === "analysis" ? undefined : pageFailure.error,
                )
              : null;
            const canRetryGeneration = Boolean(pageFailure?.recoverable)
              && !revision
              && !pageIsDrawing
              && pageFailure?.classification !== "provider_blocked";
            const pageActionError = pageActionErrors[item.page.page_number];
            return (
              <EntityCard key={item.page.page_number} padding="cozy" className="h-full">
                <div className="mb-3 flex min-h-7 flex-wrap items-center justify-between gap-2">
                  <span className="font-display text-lg font-black uppercase">{t("Page")} {item.page.page_number}</span>
                  {pageIsDrawing && revision ? (
                    <StatusPill tone="ink">{t("New revision drawing")}</StatusPill>
                  ) : revision && item.analysis_recovery?.status === "stale_render" ? (
                    <StatusPill tone="red">{t("Re-planned · redraw")}</StatusPill>
                  ) : revision && item.redraw?.changed_references.length ? (
                    <StatusPill tone="gold">{t("Earlier look · redraw")}</StatusPill>
                  ) : revisedIssues ? (
                    <StatusPill tone="gold">{t("Confirm fix")}</StatusPill>
                  ) : openIssueCount > 0 ? (
                    <StatusPill tone="red">{openIssueCount} {t("FLAGGED")}</StatusPill>
                  ) : item.lettering_placement_review_needed ? (
                    <StatusPill tone="gold">{t("Needs placement")}</StatusPill>
                  ) : null}
                </div>
                {revision ? (
                  <button
                    type="button"
                    onClick={() => updateContext({ page: String(item.page.page_number), review: "page" })}
                    aria-label={`${t("Open page")} ${item.page.page_number}, ${t("revision")} ${revision}`}
                    className="block w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
                  >
                    <div className="aspect-[2/3] overflow-hidden bg-surface-container">
                      <PageThumbnail
                        src={item.lettering_mode === "hybrid" ? pageCompositePreviewUrl(id, item.page.page_number, revision, "thumbnail", item.lettering_revision) : pageRenderPreviewUrl(id, item.page.page_number, revision, "thumbnail")}
                        alt={`${t("Complete page thumbnail")} ${item.page.page_number}, ${t("revision")} ${revision}`}
                        reveal={revealedPage === item.page.page_number}
                        onRevealEnd={() => setRevealedPage(null)}
                      />
                    </div>
                  </button>
                ) : (
                  <div className="aspect-[2/3] overflow-hidden bg-surface-container">
                    {pageIsDrawing ? (
                      <FlowingDotsPlaceholder
                        aspect="2 / 3"
                        label={t("DRAWING PAGE…")}
                        caption={t("Queued in the page press")}
                        aria-label={`${t("Page")} ${item.page.page_number}: ${t("generation in progress")}`}
                        className="h-full border-0"
                      />
                    ) : failureCopy ? (
                      <div role="alert" className="flex h-full flex-col overflow-y-auto p-5 text-center">
                        <div className="my-auto flex flex-col items-center">
                          <Layers size={28} aria-hidden="true" className="text-hero-red" />
                          <strong className="mt-4 font-meta text-xs text-hero-red">
                            {failureCopy.title}
                          </strong>
                          <p className="mt-3 font-body text-xs leading-5 text-ink-black/75">
                            {failureCopy.message}
                          </p>
                          {failureCopy.guidance && (
                            <p className="mt-2 font-body text-xs leading-5 text-ink-black/75">
                              {failureCopy.guidance}
                            </p>
                          )}
                          {pageActionError && !paidIntent && (
                            <p className="mt-3 text-xs leading-5 text-hero-red">{pageActionError}</p>
                          )}
                        </div>
                        {pageFailure?.classification === "provider_blocked"
                          || (pageFailure?.recoverable && failurePhase !== "analysis"
                            && (pageFailure.classification === "generation_error"
                              || pageFailure.classification === "empty_response")) ? (
                          <div className="mt-5 grid shrink-0 gap-2">
                            <Button
                              size="xs"
                              fullWidth
                              onClick={() => requestSpend({ kind: "page", pageNumber: item.page.page_number, depiction: "less_graphic" })}
                              disabled={generate.isPending || !status?.style_selected}
                            >
                              {t("DRAW LESS GRAPHIC VERSION")}
                            </Button>
                            <Button
                              size="xs"
                              variant="outline"
                              fullWidth
                              onClick={() => requestSpend({ kind: "page", pageNumber: item.page.page_number, depiction: "canonical" })}
                              disabled={generate.isPending || !status?.style_selected}
                            >
                              {t("TRY AGAIN UNCHANGED")}
                            </Button>
                          </div>
                        ) : canRetryGeneration ? (
                          <Button
                            className="mt-5 shrink-0"
                            size="xs"
                            fullWidth
                            onClick={() => requestSpend({ kind: "page", pageNumber: item.page.page_number, depiction: "canonical" })}
                            disabled={generate.isPending || !status?.style_selected}
                          >
                            {t("TRY AGAIN")}
                          </Button>
                        ) : null}
                      </div>
                    ) : (
                      <div className="flex h-full flex-col overflow-y-auto p-5 text-center text-ink-muted">
                        <div className="my-auto flex flex-col items-center gap-4">
                          <Layers size={28} aria-hidden="true" />
                          <span className="font-meta text-xs font-bold">{t("READY TO DRAW")}</span>
                          <span className="font-body text-xs leading-6">{t("The page plan is ready. Artwork appears here once drawn.")}</span>
                          {pageActionError && !paidIntent && (
                            <span role="alert" className="text-xs leading-5 text-hero-red">{pageActionError}</span>
                          )}
                        </div>
                        {drawStatus !== "pending" && (
                          <Button
                            className="mt-5 shrink-0"
                            size="xs"
                            fullWidth
                            onClick={() => requestSpend({ kind: "page", pageNumber: item.page.page_number, depiction: "canonical" })}
                            disabled={!status?.style_selected}
                          >
                            {t("GENERATE COMPLETE PAGE")}
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </EntityCard>
            );
          })}
        </WholeBookReveal>
      </section>


      {selectedItem && (
        <PageReview
          deliberateView={deliberatePage === String(selectedItem.page.page_number)}
          key={`${id}:${selectedItem.page.page_number}`}
          project={id}
          item={selectedItem}
          onClose={() => updateContext({ page: null, review: null })}
          view={review}
          onViewChange={(view) => updateContext({ review: view })}
          previousPage={reviewIndex > 0 ? pages[reviewIndex - 1]?.page.page_number : undefined}
          nextPage={reviewIndex >= 0 ? pages[reviewIndex + 1]?.page.page_number : undefined}
          nextUnresolved={nextUnresolved}
          onNavigate={(pageNumber) => updateContext({ page: String(pageNumber) })}
          onCheckText={() => pages[reviewIndex].analysis_recovery?.requires_paid_call
            ? requestSpend({ kind: "analysis", pageNumber: pages[reviewIndex].page.page_number })
            : retryAnalysis(pages[reviewIndex].page.page_number)}
          checkingText={analyze.isPending}
          checkError={pageActionErrors[pages[reviewIndex].page.page_number]}
          onJobQueued={(jobId, pageNumber) => {
            setPageFailures((current) => {
              const next = { ...current };
              delete next[pageNumber];
              return next;
            });
            setPageJobs((current) => ({
              ...current,
              [jobId]: pageNumber,
            }));
          }}
          pageIsDrawing={drawingPages.has(selectedItem.page.page_number)}
        />
      )}
      {paidIntent && (
        <PageSpendConsent
          key={JSON.stringify(paidIntent)}
          project={id}
          intent={paidIntent}
          busy={generate.isPending || run.isPending || analyze.isPending}
          error={actionError}
          onClose={() => setPaidIntent(null)}
          onConfirm={() => {
            if (paidIntent.kind === "batch") startDraw(true, paidIntent.retry);
            else if (paidIntent.kind === "analysis") retryAnalysis(paidIntent.pageNumber);
            else drawPage(paidIntent.pageNumber, paidIntent.depiction);
          }}
        />
      )}
      {approvalError && <p role="alert" className="text-sm text-hero-red">{approvalError}</p>}
      {/* Pages are checked as they are drawn; only offer a re-check once drawing has settled. */}
      {uncheckedPages.length > 0 && drawingPages.size === 0 && queuedPageJobs.length === 0 && drawStatus !== "running" && (
        <PageCheckRecovery project={projectId} unchecked={uncheckedPages.length} onRecovered={() => void refetch()} />
      )}
      {pages.every((item) => item.active_render) && unresolvedPages.length === 0 && (
        <p role="status" className="text-sm font-bold text-archive-sage">{t("No unresolved page findings. Read through the edition before export.")}</p>
      )}

      {reviewIndex < 0 && <ApprovalBar
        next={t("Run Finish preflight and export the book")}
        primaryLabel={t("CONTINUE TO BOOK")}
        onPrimary={continueToBook}
        primaryDisabled={
          approve.isPending
          || (drawStatus !== "awaiting_review" && drawStatus !== "complete")
          || data.issue_summary.blocking_issue_ids.length > 0
          || data.pages.some((item) => !item.active_render)
        }
        busy={approve.isPending}
        secondary={rerunAdaptation}
        note={
          data.issue_summary.unresolved_issue_ids.length > 0
            ? `${data.issue_summary.unresolved_issue_ids.length} ${t("page findings available to review")}`
            : undefined
        }
      />}
      <ArchivedArtwork project={id} />
    </RoomShell>
  );
}
