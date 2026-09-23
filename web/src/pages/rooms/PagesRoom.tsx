import { createPortal } from "react-dom";
import { ArrowUpRight, BookOpen, Layers, ChevronLeft as ReviewChevronLeft, ChevronRight as ReviewChevronRight, X as ReviewClose } from "lucide-react";
import { TextCheckArtwork } from "../../components/pages/TextCheckArtwork";
import { LetteringEditor } from "../../components/lettering/LetteringEditor";
import { pageCompositePreviewUrl } from "../../api/lettering";
import { PageThumbnail } from "../../components/pages/PageThumbnail";
import { WholeBookReveal } from "../../components/pages/WholeBookReveal";
import { editionKeyFor } from "../../lib/editionKey";
import { accountIdentity } from "../../lib/accountEpoch";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  useAcceptPageIssue,
  useAnalyzeCompletePage,
  useApproveStage,
  useCompletePages,
  useDismissPageIssue,
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
  PageIssue,
  StageValidation,
} from "../../types/api";
import {
  LetteringIssueCard,
  PlainIssueCard,
  ResolvedIssueHistory,
} from "../../components/pages/LetteringEvidence";
import { isOcrIssue } from "../../components/pages/lettering";
import { RevisionDraft } from "../../components/pages/RevisionDraft";
import { PageCheckRecovery } from "../../components/pages/PageCheckRecovery";
import { VisualReviewPanel, type VisualReviewDraftSeed } from "../../components/pages/VisualReviewPanel";
import type { DrawerKind } from "../../lib/stations";
import { BottomBarPortal } from "../../layout/TopBarSlot";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";

type ReviewView = "page" | "visual" | "checks" | "lettering";
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

function BlockingFailureList({ validation }: { validation?: StageValidation }) {
  const { t } = useI18n();
  if (!validation || validation.invariant_failures.length === 0) return null;
  const explanations: Record<string, string> = {
    invalid_lettering_speaker: "Some dialogue or captions are missing who speaks them or how they should appear.",
    trailing_clipped_display_text: "Some text may end too abruptly. It needs another check before it can appear on a page.",
    upstream_adaptation_granularity: "The story needs more visual moments to fill the planned pages.",
  };
  return (
    <section aria-label={t("What needs another check")} className="mx-auto w-full max-w-[760px] px-2 pb-8 sm:px-6">
      <SectionHeader
        title={t("What needs another check")}
        description={t("These checks protect your finished pages. Try the recovery action above to address them.")}
      />
      <ul className="space-y-5">
        {validation.invariant_failures.map((failure) => (
          <li key={failure.id} className="font-body text-ink-black [overflow-wrap:anywhere]">
            <p className="text-base font-semibold leading-7">
              {t(explanations[failure.code] ?? "Part of the script or page plan needs another check before work can continue.")}
            </p>
            <details className="mt-1">
              <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm text-ink-muted">{t("Check details")}</summary>
              <div className="space-y-2 bg-surface-container p-4 text-sm leading-6">
                <p>{failure.message}</p>
                {failure.evidence.map((evidence, index) => <p key={index}>{evidence}</p>)}
              </div>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}

function IssueHistory({
  project,
  pageNumber,
  issues,
}: {
  project: string;
  pageNumber: number;
  issues: PageIssue[];
}) {
  const { t } = useI18n();
  const accept = useAcceptPageIssue();
  const dismiss = useDismissPageIssue();
  const [actionError, setActionError] = useState<{ issueId: string; message: string } | null>(null);

  function decide(issue: PageIssue, dismissFalsePositive = false) {
    setActionError(null);
    const mutation = dismissFalsePositive ? dismiss : accept;
    mutation.mutate({ project, pageNumber, issueId: issue.id }, {
      onError: (error) => setActionError({ issueId: issue.id, message: error.message }),
    });
  }

  if (issues.length === 0) {
    return <p className="font-body text-sm text-ink-muted">{t("No page issues recorded.")}</p>;
  }
  const active = issues.filter((issue) => issue.status === "open" || issue.status === "revised");
  const resolved = issues.filter((issue) => issue.status !== "open" && issue.status !== "revised");

  return (
    <div className="space-y-3">
      <ol className="space-y-3">
        {active.map((issue) => (
          <li key={issue.id}>
            <Surface
              tone={issue.classification === "invariant_failure" ? "pulp" : "bristol"}
              border="soft"
              shadow="none"
              padding="md"
            >
              <div className="space-y-3">
                {isOcrIssue(issue)
                  ? <><TextCheckArtwork project={project} issue={issue} /><LetteringIssueCard issue={issue} /></>
                  : <PlainIssueCard issue={issue} />}
                <div className="flex flex-wrap justify-end gap-2">
                  {issue.classification === "editorial_issue" && (
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() => decide(issue)}
                      disabled={accept.isPending}
                    >
                      {t(issue.status === "revised" ? "CONFIRM FIX" : "ACCEPT AS-IS")}
                    </Button>
                  )}
                  {issue.id.startsWith("page-issue-draw-page-") && (
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() => decide(issue, true)}
                      disabled={dismiss.isPending}
                    >
                      {t(isOcrIssue(issue) ? "TEXT LOOKS CORRECT" : "DISMISS FALSE POSITIVE")}
                    </Button>
                  )}
                </div>
                {actionError?.issueId === issue.id && (
                  <p role="alert" className="text-sm leading-6 text-hero-red">
                    {actionError.message} {t("Your decision was not saved. Review this finding and try again.")}
                  </p>
                )}
              </div>
            </Surface>
          </li>
        ))}
      </ol>
      <ResolvedIssueHistory issues={resolved} />
      {active.some((issue) => issue.correction_owner === "draw") && (
        <p className="font-body text-xs leading-5 text-ink-black/70">
          {t("Use Make changes on the Page tab to request draw fixes — one correction covers everything selected.")}
        </p>
      )}
    </div>
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
}) {
  const { t } = useI18n();
  // Canonical page revision being corrected; the redraw starts from the
  // active render revision. The render's own parent is comparison only.
  const comicPageRevision = item.page.revision;
  const editSourceRevision = item.active_render?.render.revision ?? null;
  const compareRevision = item.active_render?.render.parent_revision ?? null;
  const [draftKeys, setDraftKeys] = useState<string[]>([]);
  const [visualSeeds, setVisualSeeds] = useState<VisualReviewDraftSeed[]>([]);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useDialogFocus(panelRef, { onClose });

  function selectView(next: ReviewView) {
    onViewChange(next);
    // Each view starts at the top of the modal body; the header stays put.
    const scroller = bodyRef.current;
    if (scroller) {
      if (typeof scroller.scrollTo === "function") scroller.scrollTo({ top: 0 });
      else scroller.scrollTop = 0;
    }
  }

  function addVisualSeeds(seeds: VisualReviewDraftSeed[]) {
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
      onClick={onClose}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className={`flex max-h-full w-full ${view === "lettering" ? "max-w-[1800px]" : "max-w-6xl"} flex-col bg-pulp-paper shadow-ink focus-visible:outline-none sm:border-[3px] sm:border-ink-black`}
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
                active: view === "page",
                onClick: () => selectView("page"),
              },
              {
                key: "lettering",
                label: t("Lettering"),
                active: view === "lettering",
                onClick: () => selectView("lettering"),
                disabled: editSourceRevision == null,
              },
              {
                key: "visual",
                label: t("Visual review"),
                active: view === "visual",
                onClick: () => selectView("visual"),
              },
              {
                key: "checks",
                label: t("Text & findings"),
                active: view === "checks",
                onClick: () => selectView("checks"),
              },
            ]}
          />
            {nextUnresolved != null && <button type="button" className="mb-2 flex min-h-11 items-center gap-2 font-meta text-[11px] font-bold tracking-[0.04em] text-ink-black underline decoration-ink-black/30 underline-offset-4 transition-colors hover:text-hero-red disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-ink-black sm:mb-0" disabled={nextUnresolved == null} onClick={() => nextUnresolved != null && onNavigate(nextUnresolved)}>
              {t("NEXT UNRESOLVED")} <ReviewChevronRight size={16} aria-hidden="true" />
            </button>}
          </div>
        </div>
        <div ref={bodyRef} className={`min-h-0 flex-1 overflow-y-auto ${view === "lettering" ? "lettering-modal-body" : ""}`}>
          <div className="space-y-7 p-4 lg:p-6">
            {/* Revision draft stays mounted while hidden so unsaved changes survive tab switches. */}
            <div hidden={view !== "page"} role="region" aria-label={t("Page")}>
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
                  onDraftKeysChange={setDraftKeys}
                  onJobQueued={(jobId) => onJobQueued(jobId, item.page.page_number)}
                  disabled={pageIsDrawing}
                />
              ) : (
                <Surface padding="lg" border="soft" shadow="none">
                  <p>{t("This page has not been drawn yet.")}</p>
                </Surface>
              )}
            </div>

            {view === "lettering" && editSourceRevision != null && <LetteringEditor project={project} pageNumber={item.page.page_number} disabled={pageIsDrawing}/>}

            {view === "visual" && (
              <div role="region" aria-label={t("Visual review")}>
                {editSourceRevision != null ? (
                  <VisualReviewPanel
                    key={`${project}:${item.page.page_number}:${editSourceRevision}`}
                    project={project}
                    pageNumber={item.page.page_number}
                    revision={editSourceRevision}
                    pageIsDrawing={pageIsDrawing}
                    issues={item.issues}
                    draftKeys={draftKeys}
                    onAddToDraft={addVisualSeeds}
                  />
                ) : (
                  <Surface padding="lg" border="soft" shadow="none">
                    <p>{t("This page has not been drawn yet.")}</p>
                  </Surface>
                )}
              </div>
            )}

            {view === "checks" && (
              <div role="region" aria-label={t("Checks")}>
                <section className="space-y-4">
                  <SectionHeader variant="underline" title={t(item.lettering_mode === "hybrid" ? "Base-art lettering check" : "Optional text review")}
                    description={t(item.lettering_mode === "hybrid" ? "The artwork should not contain generated comic lettering. Inspect any detected regions; legitimate in-world signs remain separate." : "The checker can misread words. Compare suggestions with the artwork; they do not block export.")} />
                  {editSourceRevision != null && <Button variant="outline" onClick={onCheckText} disabled={checkingText || pageIsDrawing || item.analysis_recovery?.status === "checked"}>
                    {checkingText ? t("CHECKING TEXT…") : item.analysis_recovery?.status === "checked" ? t("TEXT CHECK COMPLETE") : t("CHECK PAGE TEXT")}
                  </Button>}
                  {checkError && <p role="alert" className="text-sm text-hero-red">{t("Text could not be checked. Your artwork is saved and you can continue to export.")}</p>}
                  <SectionHeader variant="underline" title={t("ISSUE HISTORY")} />
                  <IssueHistory
                    project={project}
                    pageNumber={item.page.page_number}
                    issues={item.issues}
                  />
                </section>
              </div>
            )}
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
  const planNeedsAdapt = planValidation?.invariant_failures.some(
    (failure) => failure.owner_stage === "adapt",
  ) ?? false;
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
  const review: ReviewView = reviewParam === "visual" || reviewParam === "checks" || reviewParam === "lettering" ? reviewParam : "page";
  const filterParam = searchParams.get("filter");
  const filter: PageFilter = filterParam === "needs-review" || filterParam === "drawing" || filterParam === "failed" ? filterParam : "all";
  const readingParam = searchParams.get("reading");
  const reading: DrawerKind | null = readingParam === "adaptation" || readingParam === "page-plan" ? readingParam : null;
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

  function updateContext(changes: Record<string, string | null>) {
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

  if (id && reading) {
    return <ReadingWorkspace project={id} kind={reading}
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

  const rerunAdaptation = id && status && ["complete", "running"].includes(status.stages.adapt?.status ?? "pending") ? (
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
          project={id ?? ""}
          stage={interruptedStage}
          status={interruptedStatus}
          stale={interruptedStageInfo?.stale}
          itemsDone={interruptedStageInfo?.items_done}
          itemsTotal={interruptedStageInfo?.items_total}
          startedAt={interruptedStageInfo?.started_at}
          retryAsRerun={planNeedsAdapt}
          allowPendingStart={interruptedStage === "adapt"}
          error={interruptedStageInfo?.error}
          errorDetail={interruptedStageInfo?.error_detail}
          errorCode={interruptedStageInfo?.error_code}
        />
        <BlockingFailureList validation={adaptValidation ?? planValidation} />
        {rerunAdaptation && <BottomBarPortal>
          <footer className="flex min-h-shell-footer flex-wrap items-center justify-end gap-3 border-t-[3px] border-ink-black bg-bristol px-4 py-3 shadow-[0_-4px_0_0_var(--color-ghost-shadow)] md:pr-6">
            {planFailed && !planNeedsAdapt && <StageStartAction
              project={id ?? ""}
              stage="adapt"
              retry
              allowRestart={false}
              disabled={!!status?.is_running || !status?.style_selected || generationJobsLoading
                || (generationJobs?.jobs ?? []).some((job) => job.status === "queued" || job.status === "running")}
            />}
            {rerunAdaptation}
          </footer>
        </BottomBarPortal>}
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
  const uncheckedPages = pages.filter((item) => item.active_render && item.analysis_recovery?.status !== "checked");
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
      <section className="grid gap-6 bg-ink-black p-6 text-pulp-paper shadow-paper md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] md:p-8">
        <div>
          <h2 className="font-display text-3xl font-black uppercase leading-tight tracking-[-0.03em] md:text-4xl">{t("Your story, page by page")}</h2>
          <p className="mt-3 max-w-[60ch] font-body text-sm leading-7 text-pulp-paper/85">{t("Read the edition as it comes to life. Open a page for a closer look, review flagged findings, or shape the next revision.")}</p>
          <div className="mt-5 flex flex-wrap gap-3">
            {unresolvedPages.length > 0 ? <Button variant="onInk" size="sm" onClick={() => updateContext({ filter: "needs-review", page: String(unresolvedPages[0].page.page_number), review: "checks" })}>{t("REVIEW FLAGGED PAGES")} ({unresolvedPages.length})<ArrowUpRight size={16} aria-hidden="true" /></Button>
              : drawnPages.length > 0 && <Button variant="onInk" size="sm" onClick={() => updateContext({ page: String(drawnPages[0].page.page_number), review: "page" })}><BookOpen size={16} aria-hidden="true" />{t("Start reading")}</Button>}
          </div>
        </div>
        <div className="flex flex-col justify-center bg-pulp-paper/10 p-5">
          <p className="font-meta text-sm font-bold">{t("{drawn} of {total} pages drawn").replace("{drawn}", String(drawnPages.length)).replace("{total}", String(pages.length))}</p>
          <progress aria-label={t("Drawing progress")} value={drawnPages.length} max={Math.max(1, pages.length)} className="mt-3 h-2 w-full overflow-hidden [&::-webkit-progress-bar]:bg-pulp-paper/20 [&::-webkit-progress-value]:bg-narrator-gold [&::-moz-progress-bar]:bg-narrator-gold" />
          <p className="mt-3 font-body text-xs leading-6 text-pulp-paper/85">{t("Open completed pages to check the artwork and lettering.")}</p>
          {status?.style_selected && selectedStyle && <div className="mt-4 flex items-center gap-3">
            {selectedStyle.has_sample && <img src={`/api/projects/${encodeURIComponent(id)}/files/samples/style_${selectedStyle.index}.png`} alt="" className="h-14 w-11 shrink-0 object-contain" />}
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
                onClick={() => updateContext({ reading: "adaptation" })}
              >
                {t("BOOK ADAPTATION")}
              </Button>
              <Button
                variant="outline"
                size="xs"
                data-reading-kind="page-plan"
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
              <div className="max-w-[62ch]">
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
              <div className="max-w-[62ch]">
                <h3 className="font-body text-base font-bold text-ink-black">{t("Finish drawing the edition")}</h3>
                <p className="mt-1 text-sm leading-6 text-ink-muted">
                  {t(pagesWaitingToDraw.length === 1
                    ? "One page still needs artwork. Completed pages are saved. Queue it after reviewing the current estimate."
                    : "{count} pages still need artwork. Completed pages are saved. Queue the unfinished pages together after reviewing the current estimate.")
                    .replace("{count}", String(pagesWaitingToDraw.length))}
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
          className="grid grid-cols-1 gap-5 min-[480px]:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
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
                  ) : revisedIssues ? (
                    <StatusPill tone="gold">{t("Needs visual review")}</StatusPill>
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
                          <p className="mt-3 max-w-[28ch] font-body text-xs leading-5 text-ink-black/75">
                            {failureCopy.message}
                          </p>
                          {failureCopy.guidance && (
                            <p className="mt-2 max-w-[28ch] font-body text-xs leading-5 text-ink-black/75">
                              {failureCopy.guidance}
                            </p>
                          )}
                          {pageActionError && !paidIntent && (
                            <p className="mt-3 max-w-[28ch] text-xs leading-5 text-hero-red">{pageActionError}</p>
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
                          <span className="max-w-[22ch] font-body text-xs leading-6">{t("The page plan is ready. Artwork appears here once drawn.")}</span>
                          {pageActionError && !paidIntent && (
                            <span role="alert" className="max-w-[28ch] text-xs leading-5 text-hero-red">{pageActionError}</span>
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
      {uncheckedPages.length > 0 && (
        <section className="space-y-3">
          <p role="status" className="text-sm font-bold">
            {pages.filter((item) => item.active_render).length} {t("pages drawn")} · {pages.filter((item) => item.analysis_recovery?.status === "checked").length} {t("pages checked")}
          </p>
          <details>
            <summary className="cursor-pointer py-3 font-meta text-sm font-bold">{t("Optional text review")}</summary>
            <p className="mb-3 max-w-prose text-sm text-ink-muted">{t("Look for possible wording differences. You can export without running this check.")}</p>
            <PageCheckRecovery project={projectId} onRecovered={() => void refetch()} />
          </details>
        </section>
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
    </RoomShell>
  );
}
