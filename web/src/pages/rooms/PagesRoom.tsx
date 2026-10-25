import { useGenerationTracking } from "../../hooks/useGenerationTracking";
import { pageState, pageDisplayImage } from "../../lib/pageState";
import { isGenerationActive, isGenerationTerminal } from "../../lib/generationTracking";
import { ErrorNotice } from "../../components/composites/ErrorNotice";
import { trackProductEvent } from "../../api/events";
import { ArchivedArtwork } from "../../components/pages/ArchivedArtwork";
import { createPortal } from "react-dom";
import { BookOpen, Columns2, LayoutGrid, Layers, MoreHorizontal, ChevronLeft as ReviewChevronLeft, ChevronRight as ReviewChevronRight, X as ReviewClose } from "lucide-react";
import { PageThumbnail } from "../../components/pages/PageThumbnail";
import { WholeBookReveal } from "../../components/pages/WholeBookReveal";
import { editionKeyFor } from "../../lib/editionKey";
import { gallerySpreads } from "../../lib/pageSpreads";
import { accountIdentity } from "../../lib/accountEpoch";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  useAnalyzeCompletePage,
  useApproveStage,
  useCompletePages,
  useGenerateCompletePage,
  useProjectStatus,
  useRunPipeline,
  useStageValidation,
  useCompletePageBatchEstimate,
  useCancelQueuedPageJobs,
  useCompletePageEstimate,
  usePageAnalysisEstimate,
  useStyles,
} from "../../api/queries";
import { ReadingWorkspace } from "../../components/pages/ReadingWorkspace";
import { canReadDocument } from "../../lib/stationAccess";
import {
  ApprovalBar,
  RerunStageAction,
  ConfirmDrawer,
  RoomHeader,
  RoomShell,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { StageStartAction } from "../../components/composites/StagePlaceholder";
import { ImageGenerationPreview } from "../../components/composites/ImageGenerationPreview";
import { usePipelineStore } from "../../store/pipeline";
import { StatusPill } from "../../components/ui/StatusPill";
import { Surface } from "../../components/ui/Surface";
import { StateBlock } from "../../components/ui/StateBlock";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { getImageFailureCopy } from "../../lib/imageFailure";
import type {
  CompletePageSummary,
  GenerationJob,
} from "../../types/api";
import { RevisionDraft } from "../../components/pages/RevisionDraft";
import { StaleRenderRedraw } from "../../components/pages/StaleRenderRedraw";
import { PageCheckRecovery } from "../../components/pages/PageCheckRecovery";
import { OutOfDatePages } from "../../components/pages/OutOfDatePages";
import { ReviewRecheck } from "../../components/pages/ReviewRecheck";
import { StageFailureSummary } from "../../components/pages/StageFailureSummary";
import { PageSourcePanel } from "../../components/pages/PageSourcePanel";
import { PageChecks } from "../../components/pages/PageChecks";
import type { DrawerKind } from "../../lib/stations";
import { BottomBarPortal } from "../../layout/TopBarSlot";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { useBackdropDismiss } from "../../hooks/useBackdropDismiss";
import { PartNotices } from "../../components/parts/PartNotices";
import { describeRedrawChanges } from "../../components/pages/redrawChanges";
import { isStorageLimitError } from "../../lib/storageLimit";
import { StorageLimitNotice } from "../../components/composites/StorageLimitNotice";

const LetteringEditor = lazy(() => import("../../components/lettering/LetteringEditor").then(module => ({ default: module.LetteringEditor })));

type ReviewView = "page" | "lettering" | "source";
type PageFilter = "all" | "needs-review" | "drawing" | "failed";
type PaidPageIntent =
  | { kind: "batch"; retry?: boolean }
  | { kind: "page"; pageNumber: number; depiction: "canonical" | "less_graphic" }
  | { kind: "analysis"; pageNumber: number };

function needsReview(item: CompletePageSummary) {
  return pageState(item).needsReview;
}

function PageSpendConsent({
  project, intent, busy, error, onConfirm, onClose,
}: {
  project: string;
  intent: PaidPageIntent;
  busy: boolean;
  error: Error | string | null;
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
      busy={busy}
      disabled={estimate.isFetching || !estimate.data || !!estimate.error}
      onConfirm={() => { if (estimate.data && !estimate.error && !estimate.isFetching && !busy) onConfirm(); }}
      onClose={onClose}
      extraBody={(
        <div className="space-y-3">
          {!estimate.data && !estimate.error && <p role="status">{t("Loading immediate estimate and hold…")}</p>}
          {estimate.error && (
            <ErrorNotice error={estimate.error} operation="estimate" title="The cost could not be loaded. Nothing has been started."
              onRetry={() => void estimate.refetch()} retryLabel={t("RETRY ESTIMATE")} />
          )}
          {error && <ErrorNotice error={error} operation="generate" />}
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
  totalPages,
  filmstrip,
}: {
  project: string;
  item: CompletePageSummary;
  totalPages: number;
  filmstrip: Array<{ pageNumber: number; src: string | null; flagged: boolean }>;
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
  checkError?: Error;
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

  const darkButton = "flex size-9 items-center justify-center border border-pulp-paper/20 text-pulp-paper transition-colors hover:bg-pulp-paper/10 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold";

  return createPortal(
    <section
      role="dialog"
      aria-modal="true"
      aria-label={`${t("Page")} ${item.page.page_number} ${t("review")}`}
      className="fixed inset-0 z-[120] flex"
      {...backdrop}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex h-full w-full flex-col bg-ink-black text-pulp-paper focus-visible:outline-none"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-pulp-paper/10 px-3 py-2 sm:px-5">
          <button type="button" onClick={onClose} className="flex h-9 items-center gap-1.5 pr-1 font-meta text-[0.8125rem] text-on-chrome-muted transition-colors hover:text-pulp-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-narrator-gold">
            <ReviewChevronLeft size={16} aria-hidden="true" />{t("Pages")}
          </button>
          <span aria-hidden="true" className="hidden h-5 w-px bg-pulp-paper/15 sm:block" />
          <h2 className="font-display text-[1.625rem] font-black uppercase leading-none tracking-[-0.03em]">
            {t("Page")} {item.page.page_number}
          </h2>
          <p className="font-meta text-[0.8125rem] text-on-chrome-muted">
            {totalPages > 0 && <>{t("of {total}", { total: String(totalPages) })} · </>}<span>{t("Revision")} {editSourceRevision ?? comicPageRevision}</span>
          </p>
          <p className="hidden min-w-0 flex-1 truncate text-[0.8125rem] text-pulp-paper/80 xl:block" title={item.page.rhythm_intent}>{item.page.rhythm_intent}</p>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <div role="group" aria-label={`${t("Page")} ${item.page.page_number} ${t("sections")}`} className="flex border border-pulp-paper/20">
              {([
                { key: "page", label: t("Page") },
                ...(editableLettering ? [{ key: "lettering", label: t("Lettering"), disabled: editSourceRevision == null }] : []),
                { key: "source", label: t("Source") },
              ] as Array<{ key: ReviewView; label: string; disabled?: boolean }>).map((tab) => (
                <button key={tab.key} type="button" aria-pressed={shownView === tab.key} disabled={tab.disabled}
                  onClick={() => selectView(tab.key)}
                  className={cn("h-9 px-3 font-meta text-[0.8125rem] font-medium transition-colors focus-visible:relative focus-visible:outline focus-visible:outline-2 focus-visible:outline-narrator-gold disabled:cursor-not-allowed disabled:opacity-40",
                    shownView === tab.key ? "bg-pulp-paper text-ink-black" : "text-on-chrome-muted hover:bg-pulp-paper/10 hover:text-pulp-paper")}>
                  {tab.label}
                </button>
              ))}
            </div>
            <nav aria-label={t("Review navigation")} className="flex gap-1">
              <button type="button" className={darkButton} aria-label={t("PREVIOUS PAGE")} title={t("PREVIOUS PAGE")} disabled={previousPage == null} onClick={() => previousPage != null && onNavigate(previousPage)}>
                <ReviewChevronLeft size={18} aria-hidden="true" />
              </button>
              <button type="button" className={darkButton} aria-label={t("NEXT PAGE")} title={t("NEXT PAGE")} disabled={nextPage == null} onClick={() => nextPage != null && onNavigate(nextPage)}>
                <ReviewChevronRight size={18} aria-hidden="true" />
              </button>
            </nav>
            {nextUnresolved != null && (
              <button type="button" className="flex h-9 items-center gap-2 border border-pulp-paper/20 px-3 font-meta text-[0.8125rem] font-medium text-pulp-paper transition-colors hover:bg-pulp-paper/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-narrator-gold" onClick={() => onNavigate(nextUnresolved)}>
                <span aria-hidden="true" className="size-2 border border-ink-black bg-narrator-gold" />
                {t("Next that needs you · {page}", { page: String(nextUnresolved) })}
              </button>
            )}
            <button type="button" className={darkButton} onClick={onClose} aria-label={t("Close page review")} title={t("CLOSE")}>
              <ReviewClose size={18} aria-hidden="true" />
            </button>
          </div>
        </header>
        <div className="flex min-h-0 flex-1">
          {filmstrip.length > 1 && (
            <nav aria-label={t("Pages")} className="hidden w-[6.5rem] shrink-0 overflow-y-auto bg-[#141510] py-4 lg:block">
              <ol className="flex flex-col items-center gap-3.5">
                {filmstrip.map((entry) => {
                  const current = entry.pageNumber === item.page.page_number;
                  return (
                    <li key={entry.pageNumber}>
                      <button type="button" aria-current={current ? "page" : undefined}
                        aria-label={`${t("Page")} ${entry.pageNumber}${entry.flagged ? `, ${t("Needs you")}` : ""}`}
                        ref={current ? (node) => node?.scrollIntoView?.({ block: "nearest" }) : undefined}
                        onClick={() => !current && onNavigate(entry.pageNumber)}
                        className={cn("group relative block w-[4.5rem] text-center font-meta text-[0.6875rem] font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold", current ? "text-narrator-gold" : "text-on-chrome-muted hover:text-pulp-paper")}>
                        {entry.src
                          ? <img src={entry.src} alt="" loading="lazy" decoding="async" className={cn("aspect-[2/3] w-full object-cover outline outline-1 outline-pulp-paper/15 transition-opacity", current ? "opacity-100 outline-2 outline-offset-2 outline-narrator-gold" : "opacity-60 group-hover:opacity-100")} />
                          : <span className="block aspect-[2/3] w-full bg-pulp-paper/5 outline outline-1 outline-pulp-paper/15" />}
                        {entry.flagged && <span aria-hidden="true" className="absolute right-1 top-1 size-2.5 border border-ink-black bg-narrator-gold" />}
                        <span className="mt-1 block">{entry.pageNumber}</span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            </nav>
          )}
          <div ref={bodyRef} className={cn("flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto", shownView === "lettering" && "lettering-modal-body")}>
            {(renderStale || !!item.redraw?.changed_references.length) && !pageIsDrawing && (
              <div className="shrink-0 bg-pulp-paper p-4 text-ink-black lg:px-6">
                <StaleRenderRedraw project={project} pageNumber={item.page.page_number}
                  changedLooks={renderStale || !item.redraw ? undefined : describeRedrawChanges(item.redraw.changed_references, t)}
                  onJobQueued={(jobId) => onJobQueued(jobId, item.page.page_number)} />
              </div>
            )}
            {/* Revision draft stays mounted while hidden so unsaved changes survive tab switches. */}
            <div hidden={shownView !== "page"} role="region" aria-label={t("Page")} className="min-h-0 lg:flex-1">
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
                  correctableIssueIds={item.correctable_issue_ids}
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
                  checks={renderStale ? undefined : (draft) => (
                    <PageChecks
                      project={project}
                      item={item}
                      pageIsDrawing={pageIsDrawing}
                      draft={draft}
                      onRetryText={onCheckText}
                      retryingText={checkingText}
                      retryTextError={checkError ? t("Text could not be checked. Your artwork is saved and you can continue to export.") : undefined}
                    />
                  )}
                />
              ) : (
                <div className="p-6">
                  <Surface padding="lg" border="soft" shadow="none">
                    <p className="text-ink-black">{t("This page has not been drawn yet.")}</p>
                  </Surface>
                </div>
              )}
            </div>

            {shownView === "source" && (
              <div role="region" aria-label={t("Source")} className="min-h-full bg-pulp-paper px-4 py-6 text-ink-black lg:px-10 lg:py-8">
                <div className="mx-auto max-w-6xl"><PageSourcePanel project={project} item={item} /></div>
              </div>
            )}

            {shownView === "lettering" && editSourceRevision != null && !renderStale && (
              <div className="min-h-full bg-pulp-paper text-ink-black">
                <Suspense fallback={<p role="status">{t("Opening lettering…")}</p>}><LetteringEditor project={project} pageNumber={item.page.page_number} disabled={pageIsDrawing}/></Suspense>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>,
    document.body,
  );
}

/** The room's quiet reference documents, kept behind one button. */
function PageToolsMenu({ items, onOpen }: {
  items: Array<{ kind: "adaptation" | "page-plan"; label: string; disabled: boolean }>;
  onOpen: (kind: "adaptation" | "page-plan") => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    function close(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <div ref={rootRef} className="relative">
      <button type="button" data-page-tools aria-expanded={open} aria-haspopup="true" aria-label={t("Page documents")} title={t("Page documents")}
        onClick={() => setOpen((value) => !value)}
        className="flex size-8 items-center justify-center text-ink-muted transition-colors hover:bg-surface-container hover:text-ink-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
        <MoreHorizontal size={18} aria-hidden="true" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-52 border border-ink-black/12 bg-bristol py-1 shadow-float">
          {items.map((item) => (
            <button key={item.kind} type="button" data-reading-kind={item.kind} disabled={item.disabled}
              onClick={() => { setOpen(false); onOpen(item.kind); }}
              className="flex h-9 w-full items-center px-3 text-left font-meta text-[0.8125rem] font-medium text-ink-black transition-colors hover:bg-sidebar-tint disabled:cursor-not-allowed disabled:text-ink-soft disabled:hover:bg-transparent">
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
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
  const review: ReviewView = reviewParam === "lettering" || reviewParam === "source" ? reviewParam : "page";
  const filterParam = searchParams.get("filter");
  const filter: PageFilter = filterParam === "needs-review" || filterParam === "drawing" || filterParam === "failed" ? filterParam : "all";
  const layout: "spreads" | "grid" = searchParams.get("layout") === "grid" ? "grid" : "spreads";
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
  const [actionError, setActionError] = useState<Error | null>(null);
  const [pageActionErrors, setPageActionErrors] = useState<Partial<Record<number, Error>>>({});
  const [approvalError, setApprovalError] = useState<Error | null>(null);
  const cancelQueued = useCancelQueuedPageJobs();
  const tracking = useGenerationTracking(id);
  const { data: generationJobs, isLoading: generationJobsLoading } = tracking;
  const observedTerminalJobs = useRef(new Set<string>());
  const firstArtworkObserved = useRef<boolean | null>(null);
  const [revealedPage, setRevealedPage] = useState<number | null>(null);
  const latestPageJobs = new Map((data?.pages ?? []).map(({ page }) => [page.page_number,
    tracking.status({ kind: "complete_page_draw", identity: "page_number", value: page.page_number, currentPage: true }) ?? undefined,
  ]));

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
      && (isGenerationTerminal(job))
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
      // A page that developed in a live preview has already been revealed.
      const previewed = !!usePipelineStore.getState().imagePreviews[`page:${artwork.page.page_number}`];
      if (!previewed && (filter === "all" || (filter === "needs-review" && needsReview(artwork)))) {
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
          (document.querySelector<HTMLButtonElement>(`[data-reading-kind="${reading}"]`)
            ?? document.querySelector<HTMLButtonElement>("[data-page-tools]"))?.focus();
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

  const projectWorkActive = !!status?.is_running
    || Object.values(status?.stages ?? {}).some((stage) => stage.status === "running")
    || (generationJobs?.jobs ?? []).some((job) => isGenerationActive(job));

  // Starting over only makes sense once a first adaptation and page plan
  // have finished (or the plan failed); never while that first run is going.
  const rerunAdaptation = id && status && !projectWorkActive && status.stages.adapt?.status === "complete"
    && ["complete", "failed"].includes(status.stages.plan?.status ?? "pending") ? (
    <RerunStageAction
      project={id}
      stage="adapt"
      label="adaptation"
      disabled={!!status.is_running || !status.style_selected || generationJobsLoading
        || (generationJobs?.jobs ?? []).some((job) => isGenerationActive(job))}
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
                || (generationJobs?.jobs ?? []).some((job) => isGenerationActive(job))}
            /> : rerunAdaptation}
          </footer>
        </BottomBarPortal>}
        {id && <ArchivedArtwork project={id} />}
      </RoomShell>
    );
  }
  const projectId = id;
  const pages = data.pages;
  const states = new Map(pages.map(item => [item.page.page_number, pageState(item, {
    starting: startingPages.includes(item.page.page_number), batch: batchPages.includes(item.page.page_number),
    drawFailed: drawStatus === "failed", submitted: Object.values(pageJobs).includes(item.page.page_number),
    job: latestPageJobs.get(item.page.page_number), failure: pageFailures[item.page.page_number],
  })]));
  const drawingPages = new Set(pages.filter(item => states.get(item.page.page_number)!.drawing).map(item => item.page.page_number));
  const failedPages = new Set(pages.filter(item => states.get(item.page.page_number)!.failed).map(item => item.page.page_number));
  const drawnPages = pages.filter((item) => item.active_render);
  const undrawnPages = pages.filter((item) => !item.active_render);
  const pagesWaitingToDraw = undrawnPages.filter((item) => !drawingPages.has(item.page.page_number));
  const queuedPageJobs = (generationJobs?.jobs ?? []).filter((job) =>
    job.kind === "complete_page_draw" && job.is_current_page !== false && job.status === "queued",
  );
  // Require server-confirmed jobs for the whole remaining batch. A single
  // page request or a partially queued edition is not a queue-all run.
  const allRemainingPagesQueued = undrawnPages.length > 1 && undrawnPages.every((item) => {
    const job = latestPageJobs.get(item.page.page_number);
    return job?.status === "queued" || job?.status === "running";
  });
  const queueControl = allRemainingPagesQueued && queuedPageJobs.length > 0 ? (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">{t("Spotted an issue? Stop queued pages before more artwork is generated.")}</p>
        <Button
          variant="outline"
          size="sm"
          disabled={cancelQueued.isPending}
          onClick={() => cancelQueued.mutate(id)}
        >{cancelQueued.isPending ? t("STOPPING QUEUED DRAWING…") : t("STOP QUEUED DRAWING")} ({queuedPageJobs.length})</Button>
      </div>
      <p className="text-xs text-ink-muted">{t("Pages already drawing will finish. Waiting pages are cancelled without a generation charge. Completed artwork stays saved.")}</p>
      {cancelQueued.error && <ErrorNotice error={cancelQueued.error} operation="save" />}
    </div>
  ) : null;
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
  const showSpreads = filter === "all" && layout === "spreads";
  // Pages holding an export blocker: the bar sends you to the first one instead of to Book.
  const blockingIds = new Set(data.issue_summary.blocking_issue_ids);
  const blockedPages = pages.filter((item) => item.issues.some((issue) => blockingIds.has(issue.id)));
  const firstBlockedPage = blockingIds.size > 0 ? (blockedPages[0]?.page.page_number ?? unresolvedPages[0]?.page.page_number) : undefined;
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
        onError: (error) => setApprovalError(error),
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
    void tracking.start({ kind: "complete_page_draw", identity: "page_number", value: pageNumber },
      () => generate.mutateAsync({ project: projectId, pageNumber, depiction }), {
        actionLabel: `${t("Draw page")} ${pageNumber}`,
        onRetry: () => requestSpend({ kind: "page", pageNumber, depiction }),
      }).then(({ job }) => {
        setPaidIntent(null);
        setStartingPages(current => current.filter(page => page !== pageNumber));
        setPageJobs(current => ({ ...current, [job.id]: pageNumber }));
      }).catch((error: Error) => {
        setActionError(error);
        setPageActionErrors(current => ({ ...current, [pageNumber]: error }));
        setStartingPages(current => current.filter(page => page !== pageNumber));
      });
  }

  function startDraw(queuePages: boolean, retry = false) {
    if (!status?.style_selected || run.isPending) return;
    setActionError(null);
    const undrawnPages = pages.filter(item => !item.active_render).map(item => item.page.page_number);
    void tracking.start({ kind: "complete_page_draw" }, () => run.mutateAsync({ project: projectId, stage: "draw", queuePages }), {
      actionLabel: t(retry ? "RETRY ALL INCOMPLETE PAGES" : "QUEUE ALL PAGES"),
      onRetry: () => requestSpend({ kind: "batch", retry }),
    }).then(() => {
      if (queuePages) setBatchPages(undrawnPages);
      setPaidIntent(null);
    }).catch((error: Error) => {
      setActionError(error);
      if (queuePages) setBatchPages([]);
    });
  }

  function retryAnalysis(pageNumber: number) {
    setActionError(null);
    void tracking.start({ kind: "page_analysis", identity: "page_number", value: pageNumber }, () => analyze.mutateAsync({ project: projectId, pageNumber }), {
      actionLabel: t("RETRY TEXT CHECK"),
      onRetry: () => requestSpend({ kind: "analysis", pageNumber }),
    }).then(() => {
      setPaidIntent(null);
      setPageFailures(current => ({ ...current, [pageNumber]: undefined }));
      setPageActionErrors(current => ({ ...current, [pageNumber]: undefined }));
    }).catch((error: Error) => {
      setActionError(error);
      setPageActionErrors(current => ({ ...current, [pageNumber]: error }));
    });
  }

  function renderPage(item: CompletePageSummary, side?: "left" | "right") {
    const { revision, drawing: pageIsDrawing, failure: pageFailure, failurePhase, badge, openIssues: openIssueCount, canRetryGeneration } = states.get(item.page.page_number)!;
    const failureCopy = pageFailure && !revision && !pageIsDrawing
      ? getImageFailureCopy(
          t,
          failurePhase === "analysis" ? "analysis_error" : pageFailure.classification,
          failurePhase === "analysis" ? undefined : pageFailure.user_message,
          failurePhase === "analysis" ? undefined : pageFailure.error,
        )
      : null;
    const pageActionError = pageActionErrors[item.page.page_number];
    return (
      <article key={item.page.page_number} aria-label={`${t("Page")} ${item.page.page_number}`} className="relative flex min-w-0 flex-col">
        <div className="relative shadow-[0_1px_2px_rgb(27_28_21/0.18),0_18px_34px_-18px_rgb(27_28_21/0.45)]">
        <ImageGenerationPreview project={projectId} target={`page:${item.page.page_number}`} active={pageIsDrawing} keepChildren={!!revision} aspect="2 / 3"
          aria-label={`${t("Page")} ${item.page.page_number}: ${t("generation in progress")}`}
          finalSrc={revision ? (pageDisplayImage(projectId, { pageNumber: item.page.page_number, revision: revision, hybrid: item.lettering_mode === "hybrid", letteringRevision: item.lettering_revision }, "thumbnail")) : undefined}
          label={t("DRAWING PAGE…")} caption={t("Queued in the page press")}>
        {revision ? (
          <button
            type="button"
            onClick={() => updateContext({ page: String(item.page.page_number), review: "page" })}
            aria-label={`${t("Open page")} ${item.page.page_number}, ${t("revision")} ${revision}`}
            className="group relative block w-full text-left transition-[translate,box-shadow] duration-[var(--motion-settle)] ease-[var(--ease-press)] hover:z-10 hover:-translate-x-px hover:-translate-y-px hover:shadow-press focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
          >
            <div className="relative aspect-[2/3] overflow-hidden bg-surface-container outline outline-0 outline-ink-black group-hover:outline-2">
              <PageThumbnail
                src={pageDisplayImage(projectId, { pageNumber: item.page.page_number, revision: revision, hybrid: item.lettering_mode === "hybrid", letteringRevision: item.lettering_revision }, "thumbnail")}
                alt={`${t("Complete page thumbnail")} ${item.page.page_number}, ${t("revision")} ${revision}`}
                reveal={revealedPage === item.page.page_number}
                onRevealEnd={() => setRevealedPage(null)}
              />
              {/* The fold of the open book darkens the inner edge of each facing page. */}
              {side && <span aria-hidden="true" className={cn("pointer-events-none absolute inset-y-0 w-6", side === "left" ? "right-0 bg-gradient-to-l" : "left-0 bg-gradient-to-r", "from-ink-black/30 to-transparent")} />}
              <span aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-ink-black/80 to-transparent px-2.5 pb-2 pt-6 font-meta text-xs font-medium text-pulp-paper opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                {t("Open page")}<span>→</span>
              </span>
            </div>
          </button>
        ) : (
          <div className="benday-paper aspect-[2/3] overflow-hidden">
            {failureCopy ? (
              <div role="alert" className="flex h-full flex-col overflow-y-auto px-3 pb-3 pt-10 text-center">
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
                    <ErrorNotice error={pageActionError} operation="generate" />
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
              <div className="flex h-full flex-col overflow-y-auto px-3 pb-3 pt-10 text-center text-ink-muted">
                <div className="my-auto flex flex-col items-center gap-4">
                  <Layers size={28} aria-hidden="true" />
                  <span className="font-meta text-xs font-semibold">{t("Ready to draw")}</span>
                  <span className="font-body text-xs leading-6">{t("The page plan is ready. Artwork appears here once drawn.")}</span>
                  {pageActionError && !paidIntent && (
                    <ErrorNotice error={pageActionError} operation="generate" />
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
                    {t("Draw page")}
                  </Button>
                )}
              </div>
            )}
          </div>
        )}
        </ImageGenerationPreview>
        {/* Comic caption box and stamp: the page's identity rides on the art. */}
        <div className="pointer-events-none absolute inset-x-2 top-2 z-10 flex flex-wrap items-start justify-between gap-1">
          <span aria-hidden="true" className="flex h-[22px] min-w-6 items-center justify-center border border-ink-black bg-pulp-paper px-1.5 font-meta text-[0.6875rem] font-bold leading-none tracking-[0.08em] text-ink-black">
            {item.page.page_number}
          </span>
            {badge === "revising" ? (
              <StatusPill className="border border-ink-black" tone="ink">{t("New revision drawing")}</StatusPill>
            ) : badge === "stale" ? (
              <StatusPill className="border border-ink-black" tone="red">{t("Re-planned · redraw")}</StatusPill>
            ) : badge === "earlier-look" ? (
              <StatusPill className="border border-ink-black" tone="gold">{t("Earlier look · redraw")}</StatusPill>
            ) : badge === "confirm-fix" ? (
              <StatusPill className="border border-ink-black" tone="gold">{t("Confirm fix")}</StatusPill>
            ) : badge === "flagged" ? (
              <StatusPill className="border border-ink-black" tone="gold">{t("{count, plural, one {# check} other {# checks}}", { count: openIssueCount })}</StatusPill>
            ) : badge === "placement" ? (
              <StatusPill className="border border-ink-black" tone="gold">{t("Needs placement")}</StatusPill>
            ) : null}
        </div>
        </div>
        <p className={cn("mt-2.5 flex min-w-0 gap-2 font-body text-xs leading-[17px] text-ink-soft", side === "left" && "pr-4", side === "right" && "pl-1")}>
          <span aria-hidden="true" className={cn("shrink-0 font-meta font-bold text-ink-black", needsReview(item) && "bg-narrator-gold px-1")}>{item.page.page_number}</span>
          <span className="truncate" title={item.page.rhythm_intent}>{item.page.rhythm_intent}</span>
        </p>
      </article>
    );
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        title={t("Pages")}
        lead={[
          t("{count, plural, one {# page} other {# pages}}", { count: pages.length }),
          status?.style_selected ? selectedStyle?.label : undefined,
        ].filter(Boolean).join(" · ")}
      />
      <PartNotices status={status} project={id} />
      {!status?.style_selected && <p role="status" className="text-sm">{t("Select a visual direction in Look before drawing pages.")}</p>}

      <section aria-label={t("Page gallery")} className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div role="group" aria-label={t("Filter pages")} className="inline-flex border border-ink-black/55 bg-bristol">
            {([
              ["all", t("All"), pages.length],
              ["needs-review", t("Needs you"), unresolvedPages.length],
              ["drawing", t("Drawing"), drawingPages.size],
              ["failed", t("Failed"), failedPages.size],
            ] as const).filter(([value, , count]) => value === "all" || count > 0 || filter === value).map(([value, label, count]) => (
              <button key={value} type="button" aria-pressed={filter === value} onClick={() => updateContext({ filter: value })}
                className={cn(
                  "flex h-8 items-center gap-1.5 px-3 font-meta text-[0.8125rem] font-medium transition-colors [&+&]:shadow-[inset_1px_0_0_rgb(27_28_21/0.12)]",
                  filter === value ? "bg-ink-black text-pulp-paper" : "text-ink-muted hover:bg-sidebar-tint hover:text-ink-black",
                )}>
                {label} <span className="tabular-nums opacity-70">{count}</span>
              </button>
            ))}
          </div>
          {drawnPages.length < pages.length && (
            <div className="flex items-center gap-2">
              <progress aria-label={t("Drawing progress")} value={drawnPages.length} max={Math.max(1, pages.length)} className="h-1 w-20 overflow-hidden [&::-moz-progress-bar]:bg-ink-black [&::-webkit-progress-bar]:bg-surface-variant [&::-webkit-progress-value]:bg-ink-black" />
              <p className="font-meta text-xs text-ink-soft">{t("{drawn} of {total} pages drawn", { drawn: String(drawnPages.length), total: String(pages.length) })}</p>
            </div>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {filter === "all" && (
              <div role="group" aria-label={t("Page layout")} className="inline-flex border border-ink-black/55 bg-bristol">
                {([
                  ["spreads", t("Spreads"), Columns2],
                  ["grid", t("Grid"), LayoutGrid],
                ] as const).map(([value, label, Icon]) => (
                  <button key={value} type="button" aria-pressed={layout === value}
                    onClick={() => updateContext({ layout: value === "spreads" ? null : value })}
                    className={cn(
                      "flex h-8 items-center gap-1.5 px-3 font-meta text-[0.8125rem] font-medium transition-colors [&+&]:shadow-[inset_1px_0_0_rgb(27_28_21/0.12)]",
                      layout === value ? "bg-ink-black text-pulp-paper" : "text-ink-muted hover:bg-sidebar-tint hover:text-ink-black",
                    )}>
                    <Icon size={15} aria-hidden="true" />{label}
                  </button>
                ))}
              </div>
            )}
            {drawnPages.length > 0 && (
              <Button variant="outline" size="sm" onClick={() => updateContext({ page: String(drawnPages[0].page.page_number), review: "page" })}>
                <BookOpen size={15} aria-hidden="true" />{t("Read")}
              </Button>
            )}
            <PageToolsMenu
              items={[
                { kind: "adaptation", label: t("Adaptation"), disabled: !canReadDocument("adaptation", status) },
                { kind: "page-plan", label: t("Page plan"), disabled: !canReadDocument("page-plan", status) },
              ]}
              onOpen={(kind) => updateContext({ reading: kind })}
            />
          </div>
        </div>
        {drawStatus === "failed" && (status?.stages.draw?.error || status?.stages.draw?.error_code) && (
          isStorageLimitError(status.stages.draw.error, status.stages.draw.error_code)
            ? <StorageLimitNotice error={status.stages.draw.error} errorDetail={status.stages.draw.error_detail} />
            : <ErrorNotice error={status.stages.draw.error} errorCode={status.stages.draw.error_code} errorDetail={status.stages.draw.error_detail} operation="generate" />
        )}
        {drawStatus === "pending" && (
          <Surface tone="bristol" padding="md" border="soft" shadow="none">
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
            {actionError && !paidIntent && <ErrorNotice error={actionError} operation="generate" />}
          </Surface>
        )}
        {(data?.review_recheck?.length ?? 0) > 0 && (
          <div>
            <ReviewRecheck project={id} disabled={drawingPages.size > 0 || !!status?.is_running} />
          </div>
        )}
        {drawStatus !== "pending" && !generationJobsLoading && pagesWaitingToDraw.length > 0 && (
          <Surface tone="bristol" padding="md" border="soft" shadow="none">
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
          <div>
            <OutOfDatePages project={id} redraws={(data?.redraws ?? []).filter((page) => !drawingPages.has(page.page_number))}
              disabled={drawingPages.size > 0 || !!status?.is_running}
              onQueued={(jobs) => setPageJobs((current) => ({
                ...current, ...Object.fromEntries(jobs.map(({ page_number, job }) => [job.id, page_number])),
              }))} />
          </div>
        )}
        {drawingPages.size > 0 && (
          <Surface tone="bristol" border="soft" shadow="none" padding="md">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p role="status" className="text-sm font-bold">{drawingPages.size} {t("pages drawing or queued")}</p>
            </div>
            <p className="mt-1 text-sm text-ink-muted">{t("Completed pages are ready to inspect while the press continues.")}</p>
            <div className="mt-3">{queueControl}</div>
            <div className="mt-3 flex gap-3 overflow-x-auto">
              {pages.filter((item) => item.active_render).map((item) => (
                <button key={item.page.page_number} type="button" className="w-20 shrink-0 p-1 text-center text-xs font-bold" onClick={() => updateContext({ page: String(item.page.page_number), review: "page" })} aria-label={`${t("Inspect completed page")} ${item.page.page_number}`}>
                  <img src={pageDisplayImage(id, { pageNumber: item.page.page_number, revision: item.active_render!.render.revision, hybrid: item.lettering_mode === "hybrid", letteringRevision: item.lettering_revision }, "thumbnail")} alt="" className="mb-2 aspect-[2/3] w-full object-contain" />
                  {t("Page")} {item.page.page_number}
                </button>
              ))}
            </div>
          </Surface>
        )}
        {visiblePages.length === 0 && <p role="status" className="benday-paper px-5 py-10 text-center text-sm text-ink-muted">{t("No pages in this filter.")}</p>}
        <WholeBookReveal
          ready={filter === "all" && pages.length > 1 && drawnPages.length === pages.length && drawingPages.size === 0}
          editionKey={editionKeyFor(projectId, pages.map((item) => item.page))}
          className={showSpreads
            ? "grid grid-cols-[repeat(auto-fill,minmax(min(100%,27rem),1fr))] gap-x-11 gap-y-10 pt-1"
            : "grid grid-cols-[repeat(auto-fill,minmax(min(100%,176px),1fr))] gap-x-5 gap-y-7 pt-1"}
        >
          {showSpreads
            ? gallerySpreads(visiblePages).map((spread) => (
              <section key={spread.key} aria-label={spread.slots.filter(Boolean).length > 1
                ? t("Pages {first} and {second}", { first: String(spread.slots[0]!.page.page_number), second: String(spread.slots[1]!.page.page_number) })
                : `${t("Page")} ${spread.slots.find(Boolean)!.page.page_number}`}
                className={cn("grid min-w-0 grid-cols-2", spread.kind === "wide" && "grid-cols-1")}>
                {spread.slots.map((slot, index) => slot
                  ? <div key={slot.page.page_number} className="min-w-0">{renderPage(slot, spread.kind === "facing" && spread.slots.every(Boolean) ? (index === 0 ? "left" : "right") : undefined)}</div>
                  : <div key={`blank-${index}`} aria-hidden="true" />)}
              </section>
            ))
            : visiblePages.map((item) => renderPage(item))}
        </WholeBookReveal>
      </section>


      {selectedItem && (
        <PageReview
          deliberateView={deliberatePage === String(selectedItem.page.page_number)}
          totalPages={pages.length}
          filmstrip={pages.map((entry) => ({
            pageNumber: entry.page.page_number,
            src: entry.active_render ? pageDisplayImage(projectId, { pageNumber: entry.page.page_number, revision: entry.active_render.render.revision, hybrid: entry.lettering_mode === "hybrid", letteringRevision: entry.lettering_revision }, "thumbnail") : null,
            flagged: needsReview(entry),
          }))}
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
      {approvalError && <ErrorNotice error={approvalError} operation="approve" />}
      {/* Pages are checked as they are drawn; only offer a re-check once drawing has settled. */}
      {uncheckedPages.length > 0 && drawingPages.size === 0 && queuedPageJobs.length === 0 && drawStatus !== "running" && (
        <PageCheckRecovery project={projectId} unchecked={uncheckedPages.length} onRecovered={() => void refetch()} />
      )}
      {pages.every((item) => item.active_render) && unresolvedPages.length === 0 && (
        <p role="status" className="text-sm font-bold text-archive-sage">{t("No unresolved page findings. Read through the edition before export.")}</p>
      )}

      {reviewIndex < 0 && !projectWorkActive && drawingPages.size === 0 && !run.isPending && !generate.isPending && (
        firstBlockedPage != null ? <ApprovalBar
          next={t("{count, plural, one {# page needs you before export} other {# pages need you before export}}", { count: Math.max(1, blockedPages.length) })}
          primaryLabel={t("Review page {page}", { page: String(firstBlockedPage) })}
          onPrimary={() => updateContext({ page: String(firstBlockedPage), review: "page" })}
          secondary={rerunAdaptation}
          note={t("{ready} of {total} ready", { ready: String(pages.length - blockedPages.length), total: String(pages.length) })}
        /> : <ApprovalBar
          next={t("Export your book")}
          primaryLabel={t("Continue to Book")}
          onPrimary={continueToBook}
          primaryDisabled={
            approve.isPending
            || (drawStatus !== "awaiting_review" && drawStatus !== "complete")
            || data.pages.some((item) => !item.active_render)
          }
          busy={approve.isPending}
          secondary={rerunAdaptation}
          note={
            data.issue_summary.unresolved_issue_ids.length > 0
              ? `${data.issue_summary.unresolved_issue_ids.length} ${t("page findings available to review")}`
              : undefined
          }
        />
      )}
      <ArchivedArtwork project={id} />
    </RoomShell>
  );
}
