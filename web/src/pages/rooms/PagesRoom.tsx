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
} from "../../api/queries";
import { pageRenderPreviewUrl } from "../../api/pages";
import { InspectDrawer } from "../../components/InspectDrawer";
import {
  ApprovalBar,
  EntityCard,
  RoomHeader,
  RoomShell,
  RoomTabs,
  SectionHeader,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { FlowingDotsPlaceholder } from "../../components/ui/FlowingDotsPlaceholder";
import { StatusPill } from "../../components/ui/StatusPill";
import { Surface } from "../../components/ui/Surface";
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
import { VisualReviewPanel, type VisualReviewDraftSeed } from "../../components/pages/VisualReviewPanel";
import type { DrawerKind } from "../../lib/stations";

function BlockingFailureList({ validation }: { validation?: StageValidation }) {
  const { t } = useI18n();
  if (!validation || validation.invariant_failures.length === 0) return null;
  return (
    <section aria-label={t("WHAT MUST BE FIXED")}>
      <SectionHeader
        variant="underline"
        title={t("WHAT MUST BE FIXED")}
        description={t("These contract failures block the book and cannot be accepted.")}
      />
      <div className="grid gap-3">
        {validation.invariant_failures.map((failure) => (
          <Surface key={failure.id} tone="red" border="hard" shadow="paper-sm" padding="md">
            <p className="font-body text-sm font-bold leading-6">{failure.message}</p>
            <p className="mt-2 font-body text-xs leading-5 text-ink-black/70">
              {failure.evidence.join(" · ")}
            </p>
          </Surface>
        ))}
      </div>
      {validation.recommendations.length > 0 && (
        <p className="mt-3 font-body text-sm leading-6">
          {validation.recommendations.join(" ")}
        </p>
      )}
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
                  ? <LetteringIssueCard issue={issue} />
                  : <PlainIssueCard issue={issue} />}
                <div className="flex flex-wrap justify-end gap-2">
                  {issue.classification === "editorial_issue" && (
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() => accept.mutate({
                        project,
                        pageNumber,
                        issueId: issue.id,
                      })}
                      disabled={accept.isPending}
                    >
                      {t(issue.status === "revised" ? "CONFIRM FIX" : "ACCEPT AS-IS")}
                    </Button>
                  )}
                  {issue.classification === "invariant_failure"
                    && issue.id.startsWith("page-issue-draw-page-") && (
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() => dismiss.mutate({
                        project,
                        pageNumber,
                        issueId: issue.id,
                      })}
                      disabled={dismiss.isPending}
                    >
                      {t("DISMISS FALSE POSITIVE")}
                    </Button>
                  )}
                </div>
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
}: {
  project: string;
  item: CompletePageSummary;
  onClose: () => void;
  onJobQueued: (jobId: string, pageNumber: number) => void;
  pageIsDrawing: boolean;
}) {
  const { t } = useI18n();
  // Canonical page revision being corrected; the redraw starts from the
  // active render revision. The render's own parent is comparison only.
  const comicPageRevision = item.page.revision;
  const editSourceRevision = item.active_render?.render.revision ?? null;
  const compareRevision = item.active_render?.render.parent_revision ?? null;
  const [draftKeys, setDraftKeys] = useState<string[]>([]);
  const [visualSeeds, setVisualSeeds] = useState<VisualReviewDraftSeed[]>([]);
  const [view, setView] = useState<"page" | "visual" | "checks">("page");
  const panelRef = useRef<HTMLDivElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  // The gallery re-renders on every job/query tick with a fresh inline
  // onClose; calling through a ref keeps this effect (and review focus)
  // stable instead of resetting focus mid-edit.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    panel?.focus();
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      // Keep keyboard focus inside the modal while it is open. The draft
      // stays mounted while hidden, so hidden/disabled controls are
      // excluded alongside offscreen ones.
      if (event.key === "Tab" && panel) {
        const focusables = panel.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        const enabled = Array.from(focusables).filter(
          (el) => !el.hasAttribute("disabled")
            && !el.closest("[hidden]")
            && el.getClientRects().length > 0,
        );
        const active = document.activeElement as HTMLElement | null;
        if (enabled.length === 0) {
          event.preventDefault();
          return;
        }
        const first = enabled[0];
        const last = enabled[enabled.length - 1];
        if (event.shiftKey && (active === first || active === panel || !panel.contains(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (active === last || active === panel || !panel.contains(active))) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = originalOverflow;
      previouslyFocused?.focus?.();
    };
  }, []);

  function selectView(next: "page" | "visual" | "checks") {
    setView(next);
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
  return (
    <section
      role="dialog"
      aria-modal="true"
      aria-label={`${t("Page")} ${item.page.page_number} ${t("review")}`}
      className="fixed inset-0 z-[120] flex justify-center bg-ink-black/75 p-3 md:p-8"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex max-h-full w-full max-w-6xl flex-col border-[3px] border-ink-black bg-pulp-paper shadow-ink focus-visible:outline-none"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="shrink-0 border-b-[3px] border-ink-black bg-bristol">
          <header className="flex items-center justify-between gap-4 px-4 py-3">
            <div>
              <h2 className="font-display text-xl font-black uppercase">
                {t("Page")} {item.page.page_number}
              </h2>
              <p className="font-meta text-xs font-bold text-ink-muted">
                {t("Page revision")} {comicPageRevision}
                {editSourceRevision != null && ` · ${t("Render revision")} ${editSourceRevision}`}
              </p>
            </div>
            <Button variant="outline" size="xs" onClick={onClose} aria-label={t("Close page review")}>
              {t("CLOSE")}
            </Button>
          </header>
          <RoomTabs
            ariaLabel={`${t("Page")} ${item.page.page_number} ${t("sections")}`}
            className="border-t border-ink-black/15 px-4 pb-3 pt-3"
            tabs={[
              {
                key: "page",
                label: t("Page"),
                active: view === "page",
                onClick: () => selectView("page"),
              },
              {
                key: "visual",
                label: t("Visual review"),
                active: view === "visual",
                onClick: () => selectView("visual"),
              },
              {
                key: "checks",
                label: t("Checks"),
                active: view === "checks",
                onClick: () => selectView("checks"),
              },
            ]}
          />
        </div>
        <div ref={bodyRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-7 p-4 lg:p-6">
            {/* Revision draft stays mounted while hidden so unsaved changes survive tab switches. */}
            <div hidden={view !== "page"} role="tabpanel" aria-label={t("Page")}>
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

            {view === "visual" && (
              <div role="tabpanel" aria-label={t("Visual review")}>
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
              <div role="tabpanel" aria-label={t("Checks")}>
                <section>
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
    </section>
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
  const [selected, setSelected] = useState<number | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const readingParam = searchParams.get("reading");
  const reading: DrawerKind | null = readingParam === "adaptation" || readingParam === "page-plan"
    ? readingParam
    : null;
  const [pageJobs, setPageJobs] = useState<Record<string, number>>({});
  const [startingPages, setStartingPages] = useState<number[]>([]);
  const [batchPages, setBatchPages] = useState<number[]>([]);
  const [batchStartedAt, setBatchStartedAt] = useState<number | null>(null);
  const [pageFailures, setPageFailures] = useState<Partial<Record<number, GenerationJob>>>({});
  const jobIds = Object.keys(pageJobs);
  const watchingBatch = batchPages.length > 0
    && status?.stages.draw?.status !== "failed";
  const { data: trackedGenerationJobs } = useGenerationJobs(
    id,
    watchingBatch ? [] : jobIds,
    watchingBatch,
  );
  const generationJobs = watchingBatch ? undefined : trackedGenerationJobs;
  const batchGenerationJobs = watchingBatch ? trackedGenerationJobs : undefined;

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
    const failedJobs = (generationJobs?.jobs ?? [])
      .filter((job) => job.status === "failed");
    const terminalIds = (generationJobs?.jobs ?? [])
      .filter((job) => job.status === "complete" || job.status === "failed")
      .map((job) => job.id);
    if (terminalIds.length === 0) return;
    void refetch().finally(() => {
      if (failedJobs.length > 0) {
        setPageFailures((current) => {
          const next = { ...current };
          failedJobs.forEach((job) => {
            const pageNumber = pageJobs[job.id];
            if (pageNumber !== undefined) next[pageNumber] = job;
          });
          return next;
        });
      }
      setPageJobs((current) => {
        const next = { ...current };
        terminalIds.forEach((jobId) => delete next[jobId]);
        return next;
      });
    });
  }, [generationJobs?.jobs, pageJobs, refetch]);

  useEffect(() => {
    if (batchPages.length === 0) return;
    const relevant = (batchGenerationJobs?.jobs ?? []).filter(
      (job) =>
        job.kind === "complete_page_draw"
        && job.payload.issue_id == null
        && (batchStartedAt == null || Date.parse(job.queued_at) >= batchStartedAt)
        && batchPages.includes(Number(job.payload.page_number)),
    );
    const terminalPages = relevant
      .filter((job) => job.status === "complete" || job.status === "failed")
      .map((job) => Number(job.payload.page_number));
    if (terminalPages.length === 0) return;
    const failed = relevant.filter((job) => job.status === "failed");
    void refetch().finally(() => {
      if (failed.length > 0) {
        setPageFailures((current) => {
          const next = { ...current };
          failed.forEach((job) => {
            next[Number(job.payload.page_number)] = job;
          });
          return next;
        });
      }
      setBatchPages((current) => current.filter((page) => !terminalPages.includes(page)));
    });
  }, [batchGenerationJobs?.jobs, batchPages, batchStartedAt, refetch]);

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

  if (!id || error || !data) {
    return (
      <RoomShell project={id ?? ""}>
        <StagePlaceholder
          project={id ?? ""}
          stage={interruptedStage}
          status={interruptedStatus}
          stale={interruptedStageInfo?.stale}
          itemsDone={interruptedStageInfo?.items_done}
          itemsTotal={interruptedStageInfo?.items_total}
          retryAsRerun={planNeedsAdapt}
          allowPendingStart={interruptedStage === "adapt"}
          error={interruptedStageInfo?.error}
          errorDetail={interruptedStageInfo?.error_detail}
        />
        <BlockingFailureList validation={adaptValidation ?? planValidation} />
      </RoomShell>
    );
  }
  const projectId = id;
  const pages = data.pages;

  function continueToBook() {
    if (!id) return;
    approve.mutate(
      { project: id, stage: "draw" },
      { onSuccess: () => navigate(`/project/${encodeURIComponent(id)}/book`) },
    );
  }

  function drawPage(
    pageNumber: number,
    depiction: "canonical" | "less_graphic" = "canonical",
  ) {
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
          setStartingPages((current) => current.filter((page) => page !== pageNumber));
          setPageJobs((current) => ({
            ...current,
            [job.id]: pageNumber,
          }));
        },
        onError: () => {
          setStartingPages((current) => current.filter((page) => page !== pageNumber));
        },
      },
    );
  }

  function startDraw(queuePages: boolean) {
    const undrawnPages = pages
      .filter((item) => !item.active_render)
      .map((item) => item.page.page_number);
    if (queuePages) {
      setBatchStartedAt(Date.now());
      setBatchPages(undrawnPages);
    }
    run.mutate(
      { project: projectId, stage: "draw", queuePages },
      {
        onError: () => {
          if (queuePages) setBatchPages([]);
        },
      },
    );
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker={t("PAGES")}
        title={t("REVIEW COMPLETE PAGES")}
        lead={t("Each thumbnail is one fully lettered page. Corrections always create a complete new revision.")}
      />

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
                onClick={() => setSearchParams({ reading: "adaptation" })}
              >
                {t("BOOK ADAPTATION")}
              </Button>
              <Button
                variant="outline"
                size="xs"
                onClick={() => setSearchParams({ reading: "page-plan" })}
              >
                {t("PAGE PLAN")}
              </Button>
            </>
          )}
        />
        {drawStatus === "pending" && (
          <Surface tone="ink" padding="md" className="mb-5">
            <div className="flex flex-wrap items-end justify-between gap-5">
              <div className="max-w-[62ch]">
                <h3 className="font-body text-base font-bold text-bristol">
                  {t("How do you want to draw this edition?")}
                </h3>
                <p className="mt-1 text-sm leading-6 text-bristol/80">
                  {t("Queue every page now, or prepare the edition and generate pages one at a time while you review.")}
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  onClick={() => startDraw(false)}
                  disabled={run.isPending}
                >
                  {t("GO ONE BY ONE")}
                </Button>
                <Button
                  variant="onInk"
                  onClick={() => startDraw(true)}
                  disabled={run.isPending}
                >
                  {t("QUEUE ALL PAGES")}
                </Button>
              </div>
            </div>
          </Surface>
        )}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
          {data.pages.map((item) => {
            const revision = item.active_render?.render.revision;
            const pageIsDrawing = startingPages.includes(item.page.page_number)
              || (drawStatus !== "failed" && batchPages.includes(item.page.page_number))
              || Object.values(pageJobs).includes(item.page.page_number);
            const pageFailure = pageFailures[item.page.page_number] ?? item.failure;
            const failurePhase = pageFailure && "phase" in pageFailure
              ? pageFailure.phase
              : undefined;
            const failureCopy = pageFailure
              ? getImageFailureCopy(
                  t,
                  pageFailure.classification,
                  pageFailure.user_message,
                  pageFailure.error,
                )
              : null;
            const canRetryGeneration = Boolean(pageFailure?.recoverable)
              && !revision
              && pageFailure?.classification !== "provider_blocked";
            return (
              <EntityCard key={item.page.page_number} padding="cozy">
                <button
                  type="button"
                  onClick={() => setSelected(item.page.page_number)}
                  aria-label={`${t("Open page")} ${item.page.page_number}, ${t("revision")} ${revision ?? 0}`}
                  className="block w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
                >
                  <div className="aspect-[2/3] overflow-hidden bg-surface-container">
                    {pageIsDrawing ? (
                      <FlowingDotsPlaceholder
                        aspect="2 / 3"
                        label={t("DRAWING PAGE…")}
                        caption={t("Queued in the page press")}
                        aria-label={`${t("Page")} ${item.page.page_number}: ${t("generation in progress")}`}
                        className="h-full border-0"
                      />
                    ) : revision ? (
                      <img
                        src={pageRenderPreviewUrl(id, item.page.page_number, revision, "thumbnail")}
                        alt={`${t("Complete page thumbnail")} ${item.page.page_number}, ${t("revision")} ${revision}`}
                        loading="lazy"
                        decoding="async"
                        className="h-full w-full object-contain"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center px-4 text-center font-meta text-xs font-bold text-ink-muted">
                        {t("READY TO DRAW")}
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <span className="font-display text-lg font-black uppercase">{t("Page")} {item.page.page_number}</span>
                    {item.issues.some((issue) => (issue.status === "open" || issue.status === "revised")) && (
                      <StatusPill tone={item.issues.some((issue) => issue.status === "revised") ? "gold" : "red"}>
                        {item.issues.some((issue) => issue.status === "revised")
                          ? t("REVISED")
                          : item.issues.filter((issue) => issue.status === "open").length}
                      </StatusPill>
                    )}
                  </div>
                  <p className="mt-1 font-meta text-xs text-ink-muted">
                    {revision ? `${t("Revision")} ${revision}` : t("Not generated")}
                    {item.issues.some((issue) => isOcrIssue(issue) && (issue.status === "open" || issue.status === "revised"))
                      ? ` · ${t("Text check differs")}`
                      : ""}
                    {item.issues.some((issue) => issue.status === "revised")
                      ? ` · ${t("Needs visual review")}`
                      : ""}
                    {!item.issues.some((issue) => issue.status === "open" || issue.status === "revised")
                      && item.issues.some((issue) => issue.status === "resolved" || issue.status === "accepted")
                      ? ` · ${t("Checks resolved")}`
                      : ""}
                  </p>
                </button>
                {failureCopy && (
                  <Surface
                    tone="pulp"
                    border="soft"
                    shadow="none"
                    padding="sm"
                    className="mt-3 border-l-[4px] border-l-hero-red"
                    role="alert"
                  >
                    <strong className="font-meta text-[0.62rem] tracking-[0.12em] text-hero-red">
                      {failureCopy.title}
                    </strong>
                    <p className="mt-1 text-xs leading-5 text-ink-black/75">
                      {failureCopy.message}
                    </p>
                    {failureCopy.guidance && (
                      <p className="mt-2 text-xs leading-5 text-ink-black/75">
                        {failureCopy.guidance}
                      </p>
                    )}
                    {pageFailure?.classification === "provider_blocked" && !revision && (
                      <div className="mt-3 grid gap-2">
                        <Button
                          size="xs"
                          fullWidth
                          onClick={() => drawPage(item.page.page_number, "less_graphic")}
                          disabled={
                            generate.isPending
                            || pageIsDrawing
                          }
                        >
                          {t("DRAW WITHOUT REFERENCES")}
                        </Button>
                        <Button
                          size="xs"
                          variant="outline"
                          fullWidth
                          onClick={() => drawPage(item.page.page_number)}
                          disabled={
                            generate.isPending
                            || pageIsDrawing
                          }
                        >
                          {t("TRY AGAIN UNCHANGED")}
                        </Button>
                      </div>
                    )}
                    {canRetryGeneration && (
                      <Button
                        className="mt-3"
                        size="xs"
                        fullWidth
                        onClick={() => drawPage(item.page.page_number)}
                        disabled={generate.isPending || pageIsDrawing}
                      >
                        {pageIsDrawing ? t("DRAWING PAGE…") : t("TRY AGAIN")}
                      </Button>
                    )}
                    {failurePhase === "analysis" && revision && (
                      <Button
                        className="mt-3"
                        size="xs"
                        fullWidth
                        onClick={() => analyze.mutate({
                          project: projectId,
                          pageNumber: item.page.page_number,
                        })}
                        disabled={analyze.isPending}
                      >
                        {analyze.isPending ? t("CHECKING TEXT…") : t("RETRY TEXT CHECK")}
                      </Button>
                    )}
                  </Surface>
                )}
                {!revision && drawStatus !== "pending" && !failureCopy && (
                  <Button
                    className="mt-3"
                    size="xs"
                    fullWidth
                    onClick={() => drawPage(item.page.page_number)}
                    disabled={
                      pageIsDrawing
                    }
                  >
                    {pageIsDrawing
                      ? t("DRAWING PAGE…")
                      : t("GENERATE COMPLETE PAGE")}
                  </Button>
                )}
              </EntityCard>
            );
          })}
        </div>
      </section>
      {reading && (
        <InspectDrawer
          project={id}
          kind={reading}
          onClose={() => setSearchParams({}, { replace: true })}
        />
      )}

      {selectedItem && (
        <PageReview
          project={id}
          item={selectedItem}
          onClose={() => setSelected(null)}
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
          pageIsDrawing={
            startingPages.includes(selectedItem.page.page_number)
            || (drawStatus !== "failed" && batchPages.includes(selectedItem.page.page_number))
            || Object.values(pageJobs).includes(selectedItem.page.page_number)
          }
        />
      )}

      <ApprovalBar
        next={t("Run Finish preflight and export the book")}
        primaryLabel={t("CONTINUE TO BOOK")}
        onPrimary={continueToBook}
        primaryDisabled={
          approve.isPending
          || drawStatus !== "awaiting_review"
          || data.issue_summary.blocking_issue_ids.length > 0
          || data.pages.some((item) => !item.active_render)
        }
        busy={approve.isPending}
        note={
          data.issue_summary.unresolved_issue_ids.length > 0
            ? `${data.issue_summary.unresolved_issue_ids.length} ${t("unresolved page issues must be accepted before export")}`
            : undefined
        }
      />
    </RoomShell>
  );
}
