import { ErrorNotice } from "../composites/ErrorNotice";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Columns2, LoaderCircle } from "lucide-react";
import { useI18n } from "../../i18n";
import type { PageIssue } from "../../types/api";
import {
  clearRevisionDraft,
  findStaleRevisionDraft,
  loadRevisionDraft,
  newChangeId,
  saveRevisionDraft,
  useCorrectionPreview,
  useRenderCorrection,
  useSubmitCorrections,
  useSubmittedCorrectionJob,
  type DraftTarget,
  type PersistedRevisionDraft,
} from "../../api/pageRevisions";
import {
  pageRenderPreviewUrl,
  referenceFileUrl,
  type ChangeReading,
  type PageCorrectionBody,
  type PageCorrectionChange,
} from "../../api/pages";
import { ChangeCheckAction, ChangeReadingNote } from "./ChangeCheck";
import { Button } from "../ui/Button";
import { FieldLabel, TextAreaField } from "../ui/Field";
import { Surface } from "../ui/Surface";
import { PageArtwork } from "./PageArtwork";
import { BeforeAfterWipe } from "./BeforeAfterWipe";
import { Loupe } from "../ui/Loupe";
import { InspectButton } from "../ui/InspectButton";
import { PageMarker, type EditorAnnotation } from "./PageMarker";
import {
  annotationProblem,
  MAX_CORRECTION_CHANGES,
  MAX_CORRECTION_INSTRUCTION,
  MAX_CORRECTION_MARKS,
  serializeAnnotation,
} from "./correctionValidation";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { useCompletePage } from "../../api/queries";
import { RevisionSwitcher, type RevisionOption } from "./RevisionSwitcher";

interface DraftChange {
  id: string;
  issueId?: string;
  instruction: string;
  annotations: EditorAnnotation[];
}
/**
 * Exact submitted correction frozen into a render: edited instructions, mark
 * notes and the overall note as submitted — never issue-text approximations.
 */
function SubmittedCorrection({
  project,
  pageNumber,
  renderRevision,
}: {
  project: string;
  pageNumber: number;
  renderRevision: number;
}) {
  const { t } = useI18n();
  const submitted = useRenderCorrection(project, pageNumber, renderRevision);
  const correction = submitted.data?.correction ?? null;
  return (
    <div>
      <p className="font-meta text-xs font-bold text-ink-muted">
        {t("SUBMITTED FOR THIS RENDER")}
      </p>
      {submitted.isLoading && (
        <p className="mt-1 font-body text-xs text-ink-muted">{t("Loading submitted correction…")}</p>
      )}
      {submitted.error && (
        <ErrorNotice error={(submitted.error as Error)} operation="load" />
      )}
      {!submitted.isLoading && !submitted.error && !correction && (
        <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
          {t("This render was an initial draw: no submitted correction exists.")}
        </p>
      )}
      {correction && (
        <ol className="mt-1 space-y-2">
          {correction.changes.map((change) => (
            <li key={change.id} className="border-l-[3px] border-narrator-gold pl-2">
              <p className="font-body text-xs font-bold leading-5">{change.instruction}</p>
              {change.annotations.length > 0 && (
                <ul className="mt-1 space-y-1">
                  {change.annotations.map((mark) => (
                    <li key={mark.id} className="font-body text-xs leading-5 text-ink-black/75">
                      <span className="font-meta font-bold text-ink-muted">{mark.kind}: </span>
                      {mark.note}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
          {correction.note && (
            <li className="font-body text-xs italic leading-5">{correction.note}</li>
          )}
        </ol>
      )}
    </div>
  );
}

/** What the page's checks need from the revision being built. */
export interface DraftControls {
  locked: boolean;
  /** The finding's change card when it is in the next revision; null otherwise. */
  included: (issueId: string) => ReactNode | null;
  /** Adds the finding to the next revision (or focuses it when already there). */
  include: (issue: PageIssue) => void;
}

interface RevisionDraftProps {
  project: string;
  pageNumber: number;
  /** Canonical page revision being corrected. */
  comicPageRevision: number;
  /** Render revision the redraw starts from. */
  parentRenderRevision: number;
  comicPageSha256: string;
  /** Default older render for before/after comparison (the parent). */
  compareRevision: number | null;
  issues: PageIssue[];
  /** Issue IDs this render's correction may link; omitted means every open draw issue. */
  correctableIssueIds?: string[];
  onJobQueued: (jobId: string) => void;
  disabled?: boolean;
  onArtworkLoaded?: () => void;
  /** The page's checks, shown above your own changes; included findings render inside them. */
  checks?: (draft: DraftControls) => ReactNode;
}

function isOpen(issue: PageIssue) {
  return issue.status === "open" || issue.status === "revised";
}

function suggestibleIssues(issues: PageIssue[], correctable?: string[]): PageIssue[] {
  // The server knows which tracked issues a correction of this render may
  // link; an older reselected render cannot fix issues found on later ones.
  const linkable = correctable ? new Set(correctable) : null;
  return issues.filter(
    (issue) => isOpen(issue) && issue.correction_owner === "draw" && (!linkable || linkable.has(issue.id)),
  );
}

/** A finding's change keeps the finding's key even when it cannot link to this render. */
function belongsTo(change: DraftChange, issueId: string) {
  return change.issueId === issueId || change.id === `issue:${issueId}`;
}

/**
 * The next revision, built in one place: findings the author chose to fix and
 * their own requests, each optionally pointed at on the page. Nothing is
 * included until the author adds it. Requests submit after an explicit
 * preview. Persisted per project/page/canonical-revision/edit-source-render;
 * queued drafts lock until the target changes.
 */
export function RevisionDraft({
  project,
  pageNumber,
  comicPageRevision,
  parentRenderRevision,
  comicPageSha256,
  compareRevision,
  issues,
  correctableIssueIds,
  onJobQueued,
  disabled,
  onArtworkLoaded,
  checks,
}: RevisionDraftProps) {
  const { t } = useI18n();
  const preview = useCorrectionPreview();
  const submit = useSubmitCorrections();
  const target = useMemo<DraftTarget>(() => ({ comicPageRevision, parentRenderRevision }), [comicPageRevision, parentRenderRevision]);

  const suggestions = useMemo(() => suggestibleIssues(issues, correctableIssueIds), [issues, correctableIssueIds]);
  const suggestionIds = useMemo(() => new Set(suggestions.map((issue) => issue.id)), [suggestions]);

  const [changes, setChanges] = useState<DraftChange[]>(() =>
    (loadRevisionDraft(project, pageNumber, target)?.changes ?? []).map((change) => ({
      id: change.id,
      issueId: change.issue_id,
      instruction: change.instruction,
      annotations: (change.annotations ?? []).map((mark) => ({ ...mark })),
    })),
  );
  const [manualInput, setManualInput] = useState(
    () => loadRevisionDraft(project, pageNumber, target)?.pendingRequest ?? "",
  );
  const [activeId, setActiveId] = useState<string | null>(null);
  const [previewHash, setPreviewHash] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<Error | string | null>(null);
  // The latest change check, keyed by change, with the wording it read.
  const [readings, setReadings] = useState<Map<string, { reading: ChangeReading; asked: string }>>(() => new Map());
  const [replanned, setReplanned] = useState(false);
  const [submittedJobId, setSubmittedJobId] = useState<string | null>(() => loadRevisionDraft(project, pageNumber, target)?.submittedJobId ?? null);
  const submittedJob = useSubmittedCorrectionJob(project, submittedJobId);
  const job = submittedJob.data?.jobs.find((item) => item.id === submittedJobId);
  const canRetry = job?.status === "failed" || job?.status === "cancelled";
  const [staleDraft, setStaleDraft] = useState<PersistedRevisionDraft | null>(() =>
    loadRevisionDraft(project, pageNumber, target) ? null : findStaleRevisionDraft(project, pageNumber, target),
  );

  const completed = job?.status === "complete";
  const locked = disabled || submit.isPending || (submittedJobId != null && !canRetry && !completed);
  // A submitted correction in flight. Its job is polled, so this is status, never a prompt to act.
  const redraw = submittedJobId != null && !completed && !canRetry
    ? submittedJob.error || (submittedJob.data && !job) ? "unconfirmed" : job?.status === "queued" ? "queued" : "running"
    : null;

  const [comparison, setComparison] = useState<"wipe" | "before" | "after">("wipe");
  // Any saved render can be viewed and compared; corrections always start
  // from the selected render (parentRenderRevision).
  const pageDetail = useCompletePage(project, pageNumber);
  const revisions = useMemo<RevisionOption[]>(() => (pageDetail.data?.renders ?? [])
    .map(({ render }) => ({
      revision: render.revision,
      stale: render.comic_page_revision !== comicPageRevision || render.comic_page_sha256 !== comicPageSha256,
    }))
    .sort((a, b) => a.revision - b.revision), [pageDetail.data, comicPageRevision, comicPageSha256]);
  const [viewRevision, setViewRevision] = useState(parentRenderRevision);
  const [compareChoice, setCompareChoice] = useState<number | null>(null);
  const [comparisonOpen, setComparisonOpen] = useState(false);

  // A finished redraw of a deliberately reselected older render: start a fresh draft.
  if (completed) {
    setSubmittedJobId(null);
    setChanges([]);
    setManualInput("");
    setActiveId(null);
    setPreviewHash(null);
  }

  // Checks can clear findings without changing the page/render target. Reconcile
  // both mounted and restored drafts before displaying or previewing them, while
  // leaving the exact submitted request frozen until it is available for retry.
  if (!submit.isPending && (!submittedJobId || canRetry)) {
    // An open finding from a later render cannot be linked here; keep the
    // author's own wording or marks for it as a new request, drop the rest.
    const openElsewhere = new Map(suggestibleIssues(issues).map((issue) => [issue.id, issue]));
    const activeChanges = changes.flatMap((change) => {
      // Submission creates a deterministic tracked issue for each manual
      // change. A failed job's saved draft still carries the original change
      // ID; reconnect it before retrying, preserving the author's text/marks.
      if (!change.issueId) {
        const issueId = `page-issue-manual-${pageNumber}-${parentRenderRevision}-${change.id}`;
        if (suggestionIds.has(issueId)) return [{ ...change, issueId }];
      }
      if (!change.issueId || suggestionIds.has(change.issueId)) return [change];
      const issue = openElsewhere.get(change.issueId);
      const authored = issue && (change.instruction !== issue.requested_correction || change.annotations.length > 0);
      return authored ? [{ ...change, issueId: undefined }] : [];
    });
    if (activeChanges.some((change, index) => change !== changes[index]) || activeChanges.length !== changes.length) {
      setChanges(activeChanges);
      setPreviewHash(null);
    }
  }

  // Retain the exact change IDs through failure and reload, including queued work.
  useEffect(() => {
    if (job?.status === "complete" || (!submittedJobId && changes.length === 0 && !manualInput.trim())) {
      clearRevisionDraft(project, pageNumber, target);
      return;
    }
    saveRevisionDraft({
      ...(submittedJobId ? { submittedJobId } : {}),
      project,
      pageNumber,
      comicPageRevision,
      parentRenderRevision,
      comicPageSha256,
      changes: changes.map((change) => ({
        id: change.id,
        ...(change.issueId ? { issue_id: change.issueId } : {}),
        instruction: change.instruction,
        annotations: change.annotations,
      })),
      pendingRequest: manualInput,
      // No manual story-context selection: the backend assembles whole-book
      // context automatically. Stored passage ids from older drafts are
      // never re-submitted silently.
      contextSourceUnitIds: [],
      updatedAt: new Date().toISOString(),
    });
  }, [project, pageNumber, comicPageRevision, parentRenderRevision, comicPageSha256, changes, manualInput, submittedJobId, job?.status, target]);

  function buildBody(draftChanges = changes): { body: PageCorrectionBody; problems: string[] } {
    const problems: string[] = [];
    const bodyChanges: PageCorrectionChange[] = [];
    if (draftChanges.length > MAX_CORRECTION_CHANGES) {
      problems.push(t("Include at most 24 requests in one revision."));
    }
    if (draftChanges.reduce((total, change) => total + change.annotations.length, 0) > MAX_CORRECTION_MARKS) {
      problems.push(t("Include at most 24 locations across all requests."));
    }
    for (const change of draftChanges) {
      const instruction = change.instruction.trim();
      if (!instruction) {
        problems.push(t("One change has no description yet."));
        continue;
      }
      if (instruction.length > MAX_CORRECTION_INSTRUCTION) {
        problems.push(t("Shorten each request to 1000 characters."));
      }
      const invalidMark = change.annotations.find((mark) => annotationProblem(mark));
      if (invalidMark) {
        problems.push(`${t("Location")} ${change.annotations.indexOf(invalidMark) + 1}: ${t(annotationProblem(invalidMark)!)}`);
        continue; // The problem blocks preview/submit; invalid context is never silently sent.
      }
      bodyChanges.push({
        id: change.id,
        ...(change.issueId ? { issue_id: change.issueId } : {}),
        instruction,
        annotations: change.annotations.map(serializeAnnotation),
      });
    }
    if (bodyChanges.length === 0 && problems.length === 0) {
      problems.push(t("Describe what you would like to change."));
    }
    return {
      body: {
        changes: bodyChanges,
        parent_render_revision: parentRenderRevision,
        comic_page_revision: comicPageRevision,
        comic_page_sha256: comicPageSha256,
      },
      problems,
    };
  }

  // Recomputed every render so the preview-fresh gate can never go stale.
  const prepared = buildBody();
  const bodyHash = JSON.stringify(prepared.body);

  const previewFresh = preview.data != null && previewHash === bodyHash && !manualInput.trim() && prepared.problems.length === 0;
  const previewResult = previewFresh ? preview.data : undefined;

  function runPreview() {
    if (locked) return;
    setSubmitError(null);
    const pendingRequest: DraftChange | null = manualInput.trim()
      ? { id: newChangeId(), instruction: manualInput.trim(), annotations: [] }
      : null;
    const { body, problems } = buildBody(pendingRequest ? [...changes, pendingRequest] : changes);
    if (problems.length > 0) {
      setSubmitError(problems[0] ?? t("The draft is not ready to preview."));
      return;
    }
    if (pendingRequest) {
      setChanges((current) => [...current, pendingRequest]);
      setManualInput("");
    }
    // A failed or cancelled redraw is retried as a fresh submission of the same changes.
    if (canRetry) setSubmittedJobId(null);
    setPreviewHash(null);
    preview.mutate(
      { project, pageNumber, body },
      { onSuccess: () => setPreviewHash(JSON.stringify(body)) },
    );
  }

  function runSubmit() {
    if (locked) return;
    setSubmitError(null);
    const { body, problems } = buildBody();
    if (problems.length > 0) {
      setSubmitError(problems[0] ?? t("The draft is not ready to submit."));
      return;
    }
    if (manualInput.trim() || JSON.stringify(body) !== previewHash || !preview.data) {
      setSubmitError(t("Preview the exact draft first; the draft changed since the last preview."));
      return;
    }
    submit.mutate(
      { project, pageNumber, body },
      {
        onSuccess: ({ job }) => {
          setPreviewHash(null);
          setSubmittedJobId(job.id);
          setActiveId(null);
          onJobQueued(job.id);
        },
        onError: (error) => {
          setSubmitError(error instanceof Error ? error : new Error(String(error)));
          maybeShowInsufficientCredits(error, {
            actionLabel: t("SUBMIT ONE CORRECTION"),
            onRetry: runSubmit,
          });
        },
      },
    );
  }

  function prepareCheck(): { body: PageCorrectionBody; problem: string | null } {
    const pendingRequest: DraftChange | null = manualInput.trim()
      ? { id: newChangeId(), instruction: manualInput.trim(), annotations: [] }
      : null;
    const { body, problems } = buildBody(pendingRequest ? [...changes, pendingRequest] : changes);
    if (problems.length > 0) return { body, problem: problems[0] ?? t("The draft is not ready to check.") };
    if (pendingRequest) {
      setChanges((current) => [...current, pendingRequest]);
      setManualInput("");
    }
    return { body, problem: null };
  }

  function readingFor(change: DraftChange) {
    const entry = readings.get(change.id);
    if (!entry) return null;
    // A note describes the wording it read, or its own suggestion once used.
    const wording = change.instruction.trim();
    return wording === entry.asked.trim() || wording === entry.reading.instruction.trim() ? entry.reading : null;
  }

  function addChange(change: DraftChange) {
    setChanges((current) => [...current, change]);
    setActiveId(change.id);
    // Changes are drafted against the selected render.
    setViewRevision(parentRenderRevision);
  }

  function addManual() {
    const instruction = manualInput.trim();
    if (!instruction || locked) return;
    addChange({ id: newChangeId(), instruction, annotations: [] });
    setManualInput("");
  }

  function include(issue: PageIssue) {
    if (locked) return;
    const existing = changes.find((change) => belongsTo(change, issue.id));
    if (existing) {
      setActiveId(existing.id);
      return;
    }
    // A finding this render cannot link still travels as the author's request.
    addChange({
      id: `issue:${issue.id}`,
      ...(suggestionIds.has(issue.id) ? { issueId: issue.id } : {}),
      instruction: issue.requested_correction,
      annotations: [],
    });
  }

  function updateChange(id: string, patch: Partial<DraftChange>) {
    setChanges((current) => current.map((change) => change.id === id ? { ...change, ...patch } : change));
  }

  function removeChange(id: string) {
    setChanges((current) => current.filter((change) => change.id !== id));
    if (activeId === id) setActiveId(null);
  }

  function rebaseStale(copy: boolean) {
    if (!staleDraft) return;
    if (copy) {
      setChanges((current) => {
        const known = new Set(current.map((change) => change.id));
        const rebased: DraftChange[] = staleDraft.changes
          .filter((change) => !known.has(`rebased:${change.id}`))
          // Marks never migrate across renders: geometry belongs to the old image.
          .map((change) => ({ id: `rebased:${change.id}`, instruction: change.instruction, annotations: [] }));
        if (typeof staleDraft.pendingRequest === "string" && staleDraft.pendingRequest.trim()) {
          rebased.push({ id: newChangeId(), instruction: staleDraft.pendingRequest, annotations: [] });
        }
        return [...current, ...rebased];
      });
      setViewRevision(parentRenderRevision);
    }
    // Copied or discarded, the earlier draft is done with: never offer it again.
    clearRevisionDraft(project, pageNumber, staleDraft);
    setStaleDraft(null);
  }

  const staleRequests = staleDraft
    ? [...staleDraft.changes.filter((change) => !change.issue_id || change.annotations.length > 0).map((change) => change.instruction),
      ...(staleDraft.pendingRequest?.trim() ? [staleDraft.pendingRequest.trim()] : [])]
    : [];
  const staleNotice = staleDraft && (
    <Surface tone="pulp" border="soft" shadow="none" padding="md" role="status">
      <p className="font-body text-sm font-bold">{t("You have unsent changes from an earlier version of this page.")}</p>
      {staleRequests.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-5 font-body text-sm leading-6">
          {staleRequests.slice(0, 3).map((instruction, index) => <li key={index}>{instruction}</li>)}
          {staleRequests.length > 3 && <li className="list-none text-ink-muted">{t("{count, plural, one {and # more} other {and # more}}", { count: staleRequests.length - 3 })}</li>}
        </ul>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="xs" onClick={() => rebaseStale(true)} disabled={locked}>{t("USE ON THIS VERSION")}</Button>
        <Button size="xs" variant="outline" onClick={() => rebaseStale(false)}>{t("DISCARD")}</Button>
      </div>
    </Surface>
  );

  // Findings shown by the checks hold their own change cards; everything else is listed as yours.
  const openIssues = issues.filter(isOpen);
  const checkChanges = checks
    ? openIssues.flatMap((issue) => changes.filter((change) => belongsTo(change, issue.id)).slice(0, 1))
    : [];
  const inChecks = new Set(checkChanges.map((change) => change.id));
  const ownChanges = changes.filter((change) => !inChecks.has(change.id));
  const numbers = new Map([...checkChanges, ...ownChanges].map((change, index) => [change.id, index + 1]));
  const markCount = changes.reduce((total, change) => total + change.annotations.length, 0);
  const reviewCount = changes.length + (manualInput.trim() ? 1 : 0);

  function changeCard(change: DraftChange) {
    const number = numbers.get(change.id) ?? 0;
    const active = change.id === activeId && !locked;
    const marks = change.annotations.length;
    const reading = readingFor(change);
    return (
      <div className={`space-y-2 border p-3 transition-colors ${active ? "border-ink-black bg-bristol" : "border-ink-black/12 bg-pulp-paper"}`}
        onFocusCapture={() => !locked && setActiveId(change.id)} onClick={() => !locked && setActiveId(change.id)}>
        <div className="flex items-start gap-2">
          <span aria-hidden="true" className={`mt-2 flex size-[22px] shrink-0 items-center justify-center border border-ink-black font-meta text-[0.6875rem] font-bold ${active ? "bg-narrator-gold" : "bg-bristol"}`}>
            {number}
          </span>
          <TextAreaField
            aria-label={t("Change {number}", { number })}
            className="min-h-0"
            value={change.instruction}
            disabled={locked}
            rows={2}
            maxLength={MAX_CORRECTION_INSTRUCTION}
            onChange={(event) => updateChange(change.id, { instruction: event.target.value })}
          />
        </div>
        <div className="flex min-h-8 flex-wrap items-center justify-between gap-2 pl-[30px]">
          <p className="font-body text-xs text-ink-muted">
            {marks > 0 && t("{count, plural, one {# mark} other {# marks}}", { count: marks })}
            {marks > 0 && active && " · "}
            {active && t("Click or drag on the page to show where.")}
          </p>
          {!locked && (
            <Button size="xs" variant="outline" className="border-transparent text-ink-muted hover:border-transparent hover:bg-surface-container hover:text-ink-black" onClick={(event) => { event.stopPropagation(); removeChange(change.id); }}>
              {t("Remove")}
            </Button>
          )}
        </div>
        {reading && (
          <ChangeReadingNote project={project} pageNumber={pageNumber} reading={reading}
            current={change.instruction} locked={locked}
            onUse={(instruction) => updateChange(change.id, { instruction })}
            onReplanned={() => { removeChange(change.id); setReplanned(true); }} />
        )}
      </div>
    );
  }

  const controls: DraftControls = {
    locked,
    include,
    included: (issueId) => {
      const change = checkChanges.find((candidate) => belongsTo(candidate, issueId));
      return change ? changeCard(change) : null;
    },
  };

  // While changes are being drafted, the page shows the selected render and becomes the marking surface.
  const drafting = changes.length > 0 && !redraw;
  const shownRevision = changes.length > 0 ? parentRenderRevision : viewRevision;
  const canvasSrc = pageRenderPreviewUrl(project, pageNumber, shownRevision, "reader");
  const canvasAlt = `${t("Complete page")} ${pageNumber}, ${t("render revision")} ${shownRevision}`;
  const otherRevisions = revisions.filter((option) => option.revision !== shownRevision);
  const fallbackCompare = shownRevision === parentRenderRevision && compareRevision != null
    ? compareRevision
    : [...otherRevisions].reverse().find((option) => option.revision < shownRevision)?.revision ?? otherRevisions[0]?.revision ?? null;
  const beforeRevision = compareChoice != null && compareChoice !== shownRevision
    && revisions.some((option) => option.revision === compareChoice) ? compareChoice : fallbackCompare;
  const leftOut = previewResult?.unselected_open_issue_ids.length ?? 0;
  const previewManualCount = previewResult?.pending_manual_change_ids.length ?? 0;

  return (
    <section aria-label={t("Page corrections")} className="lg:flex lg:h-full lg:flex-col">
      {/* The page under the lamp on the ink stage; the next revision in the inspector: its checks, then your own changes. */}
      <div className="grid lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_25rem] lg:grid-rows-[minmax(0,1fr)] 2xl:grid-cols-[minmax(0,1fr)_28rem]">
        <div className="benday-ink min-w-0 space-y-4 px-4 py-5 sm:px-6 lg:flex lg:min-h-0 lg:flex-col lg:overflow-y-auto">
          <figure hidden={comparisonOpen} className="relative flex h-[max(12rem,calc(100dvh-14rem))] justify-center lg:h-auto lg:min-h-64 lg:flex-1 [&_img]:shadow-[0_30px_60px_-20px_rgb(0_0_0/0.7),0_0_0_1px_rgb(252_250_237/0.12)]">
            {drafting ? (
              <PageMarker
                key={`${comicPageRevision}:${parentRenderRevision}`}
                imageSrc={canvasSrc}
                alt={canvasAlt}
                groups={[...checkChanges, ...ownChanges].map((change) => ({ id: change.id, number: numbers.get(change.id) ?? 0, marks: change.annotations }))}
                activeId={locked ? null : activeId}
                onChange={(id, annotations) => updateChange(id, { annotations })}
                onActivate={setActiveId}
                remaining={MAX_CORRECTION_MARKS - markCount}
                disabled={locked}
                onLoaded={onArtworkLoaded}
              />
            ) : (
              <Loupe className={`flex h-full w-full justify-center transition-opacity ${redraw ? "opacity-60" : ""}`}>
                <PageArtwork src={canvasSrc} alt={canvasAlt} onLoaded={onArtworkLoaded} />
              </Loupe>
            )}
            {redraw && (
              <figcaption role="status" className="pointer-events-none absolute left-1/2 top-4 flex max-w-[calc(100%-2rem)] -translate-x-1/2 items-center gap-2 border-[2px] border-ink-black bg-bristol px-3 py-2 font-meta text-xs font-bold uppercase tracking-wider shadow-ink">
                {redraw !== "unconfirmed" && <LoaderCircle size={14} aria-hidden="true" className="shrink-0 motion-safe:animate-spin" />}
                {t(redraw === "queued" ? "Redraw waiting to start" : redraw === "running" ? "Redrawing this page" : "Can’t confirm the redraw yet")}
              </figcaption>
            )}
          </figure>
          {beforeRevision != null && comparisonOpen && (
            <section aria-label={t("Revision comparison")} className="space-y-4 border border-pulp-paper/15 bg-[#141510]/95 p-4 text-pulp-paper lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
              {otherRevisions.length > 1 && (
                <label className="flex flex-wrap items-center gap-2 font-meta text-xs font-medium text-on-chrome-muted">
                  {t("Compare with")}
                  <select value={beforeRevision} className="min-h-8 border border-pulp-paper/20 bg-transparent px-2 text-pulp-paper [&>option]:text-ink-black"
                    onChange={(event) => setCompareChoice(Number(event.target.value))}>
                    {otherRevisions.map((option) => (
                      <option key={option.revision} value={option.revision}>{t("Revision")} {option.revision}</option>
                    ))}
                  </select>
                </label>
              )}
              <div role="group" aria-label={t("Revision comparison")} className="inline-flex border border-pulp-paper/20">
                {([
                  ["wipe", t("Wipe")],
                  ["before", `${t("Before")} · ${t("Revision")} ${beforeRevision}`],
                  ["after", `${t("After")} · ${t("Revision")} ${shownRevision}`],
                ] as const).map(([value, label]) => (
                  <button key={value} type="button" aria-pressed={comparison === value} onClick={() => setComparison(value)}
                    className={`h-8 px-3 font-meta text-xs font-medium transition-colors [&+&]:border-l [&+&]:border-pulp-paper/20 ${comparison === value ? "bg-pulp-paper text-ink-black" : "text-pulp-paper/85 hover:bg-pulp-paper/10"}`}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,0.6fr)]">
                <div className="relative min-w-0">
                <InspectButton
                  images={[
                    { src: pageRenderPreviewUrl(project, pageNumber, beforeRevision, "reader"), alt: `${t("Complete page")} ${pageNumber}, ${t("previous revision")} ${beforeRevision}`, label: `${t("Before")} · ${t("Revision")} ${beforeRevision}` },
                    { src: canvasSrc, alt: `${t("Complete page")} ${pageNumber}, ${t("current revision")} ${shownRevision}`, label: `${t("After")} · ${t("Revision")} ${shownRevision}` },
                  ]}
                  index={comparison === "before" ? 0 : 1}
                  placement={comparison === "wipe" ? "right-2 top-10" : undefined}
                />
                {comparison === "wipe" ? (
                  <BeforeAfterWipe
                    beforeSrc={pageRenderPreviewUrl(project, pageNumber, beforeRevision, "reader")}
                    afterSrc={canvasSrc}
                    beforeAlt={`${t("Complete page")} ${pageNumber}, ${t("previous revision")} ${beforeRevision}`}
                    afterAlt={`${t("Complete page")} ${pageNumber}, ${t("current revision")} ${shownRevision}`}
                    beforeLabel={`${t("Before")} · ${beforeRevision}`}
                    afterLabel={`${t("After")} · ${shownRevision}`}
                    visible={comparisonOpen}
                    firstViewKey={`${project}:${pageNumber}:${beforeRevision}:${shownRevision}`}
                  />
                ) : (
                <figure>
                  <img
                    src={comparison === "before" ? pageRenderPreviewUrl(project, pageNumber, beforeRevision, "reader") : canvasSrc}
                    alt={`${t("Complete page")} ${pageNumber}, ${t(comparison === "before" ? "previous revision" : "current revision")} ${comparison === "before" ? beforeRevision : shownRevision}`}
                    loading="lazy"
                    decoding="async"
                    className="max-h-[70dvh] w-full object-contain"
                  />
                  <figcaption className="mt-2 font-meta text-xs font-medium text-on-chrome-muted" aria-live="polite">
                    {t(comparison === "before" ? "Before" : "After")} · {t("Revision")} {comparison === "before" ? beforeRevision : shownRevision}
                  </figcaption>
                </figure>
                )}
                </div>
                <div className="space-y-3 text-pulp-paper [&_.text-ink-black\/75]:text-pulp-paper/80 [&_.text-ink-muted]:text-on-chrome-muted">
                  <p className="text-sm leading-6 text-pulp-paper/90">{t("A new revision is not a confirmed fix. Compare the requested change and check for unintended differences.")}</p>
                <SubmittedCorrection
                  project={project}
                  pageNumber={pageNumber}
                  renderRevision={shownRevision}
                />
                {issues.filter((issue) => issue.render_revision === beforeRevision && (issue.status === "open" || issue.status === "revised")).length > 0 && (
                  <div>
                    <p className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-ink-muted">
                      {t("Still open from the previous render")}
                    </p>
                    <ul className="mt-1 space-y-1">
                      {issues
                        .filter((issue) => issue.render_revision === beforeRevision && (issue.status === "open" || issue.status === "revised"))
                        .map((issue) => (
                          <li key={issue.id} className="font-body text-xs leading-5">
                            {issue.requested_correction}
                          </li>
                        ))}
                    </ul>
                  </div>
                )}
              </div>
                </div>
            </section>
          )}
          <div role="toolbar" aria-label={t("Page tools")} className="flex shrink-0 flex-wrap items-center justify-center gap-1 self-center border border-pulp-paper/15 bg-[#141510]/95 p-1 text-pulp-paper">
            {changes.length === 0 && revisions.length > 1 && (
              <RevisionSwitcher project={project} pageNumber={pageNumber} revisions={revisions} tone="dark"
                selected={parentRenderRevision} viewing={viewRevision} disabled={locked || !!redraw}
                onView={(revision) => { setViewRevision(revision); setCompareChoice(null); }} />
            )}
            {beforeRevision != null && (
              <button type="button" aria-expanded={comparisonOpen} onClick={() => setComparisonOpen((open) => !open)}
                className={`flex h-8 items-center gap-1.5 px-2.5 font-meta text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-narrator-gold ${comparisonOpen ? "bg-pulp-paper text-ink-black" : "text-pulp-paper/85 hover:bg-pulp-paper/10 hover:text-pulp-paper"}`}>
                <Columns2 size={14} aria-hidden="true" />{t("Compare with revision {revision}", { revision: String(beforeRevision) })}
              </button>
            )}
            <InspectButton images={{ src: canvasSrc, alt: canvasAlt }} tone="toolbar" />
          </div>
        </div>

        {/* Room at the end for button shadows and their 1px hover nudge, so hovering never adds a scrollbar. */}
        <div className="min-w-0 space-y-6 bg-bristol px-5 pb-6 pt-5 text-ink-black lg:min-h-0 lg:overflow-y-auto lg:overflow-x-hidden">
          {submittedJobId && canRetry && (
            <Surface tone="container" border="soft" shadow="none" padding="md" role="status">
              <p className="font-body text-sm font-bold">{t("The redraw didn’t finish. Your changes are still here.")}</p>
              {job?.user_message && <p className="mt-1 font-body text-sm leading-6 text-ink-muted">{job.user_message}</p>}
            </Surface>
          )}
          {staleNotice}
          {redraw && (
            <p role="status" className="font-body text-sm leading-6 text-ink-muted">
              {t(redraw === "unconfirmed"
                ? "Your changes are saved. This page updates once the redraw is confirmed."
                : "You can close this page. The new version replaces it here when ready.")}
            </p>
          )}

          {checks?.(controls)}

          {(ownChanges.length > 0 || !locked) && (
            <section aria-label={t("Your changes")} className="space-y-3 border-t border-ink-black/12 pt-5">
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="font-display text-[1.0625rem] font-extrabold tracking-[-0.01em]">{t("Your changes")}</h3>
                <p className="font-meta text-xs text-ink-soft">{changes.length === 0 ? t("None yet") : t("{count, plural, one {# change} other {# changes}}", { count: changes.length })}</p>
              </div>
              {ownChanges.length > 0 && (
                <ol className="space-y-3">
                  {ownChanges.map((change) => <li key={change.id}>{changeCard(change)}</li>)}
                </ol>
              )}
              {!locked && (
                <div className="space-y-2">
                  <FieldLabel htmlFor="draft-manual" className="sr-only">{t("Describe a change")}</FieldLabel>
                  <TextAreaField
                    id="draft-manual"
                    className="min-h-0"
                    value={manualInput}
                    maxLength={MAX_CORRECTION_INSTRUCTION}
                    rows={3}
                    placeholder={t("Describe a change, e.g. in panel 2 make his hair pink; keep his face and the lighting.")}
                    onChange={(event) => setManualInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                        event.preventDefault();
                        addManual();
                      }
                    }}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-meta text-xs text-ink-soft">{t("Enter adds it. Then mark the spot on the page.")}</p>
                    <Button size="xs" variant="outline" onClick={addManual} disabled={!manualInput.trim()}>
                      {t("Add")}
                    </Button>
                  </div>
                </div>
              )}
            </section>
          )}

          {replanned && (
            <p role="status" className="font-body text-sm leading-6">
              {t("Page {page} was re-planned. Redraw it so the art matches.", { page: String(pageNumber) })}
            </p>
          )}

          {!previewFresh && !redraw && reviewCount > 0 && (
            <ChangeCheckAction project={project} pageNumber={pageNumber} prepare={prepareCheck}
              disabled={locked || preview.isPending}
              onReadings={(body, result) => setReadings(new Map(result.changes.map((reading) => [
                reading.change_id,
                { reading, asked: body.changes.find((change) => change.id === reading.change_id)?.instruction ?? "" },
              ])))} />
          )}

          {!previewFresh && !redraw && (
            <div className="sticky bottom-0 -mx-5 space-y-2 border-t border-ink-black/12 bg-pulp-paper px-5 pb-1 pt-4">
              <Button className="w-full" size="md" onClick={runPreview} disabled={locked || preview.isPending || reviewCount === 0}>
                {preview.isPending ? t("Reviewing…") : t("{count, plural, =0 {Add a change to review} one {Review # change} other {Review # changes}}", { count: reviewCount })}
              </Button>
              {preview.data && !submittedJobId && reviewCount > 0 && (
                <p role="status" className="font-body text-xs text-ink-muted">{t("Changed since your last review.")}</p>
              )}
            </div>
          )}

          {previewResult && (
            <Surface tone="container" border="soft" shadow="none" padding="md" aria-live="polite">
              <p className="font-body text-lg font-bold">
                ~{previewResult.estimate.estimate_credits} {t("credits")}
              </p>
              {leftOut > 0 && (
                <p className="mt-1 font-body text-xs text-ink-muted">
                  {t("{count, plural, one {# other check stays open.} other {# other checks stay open.}}", { count: leftOut })}
                </p>
              )}
              {previewResult.context.truncated && (
                <p className="mt-2 font-body text-xs font-bold">{t("Context truncated to fit.")}</p>
              )}
              {previewResult.warnings.length > 0 && (
                <ul className="mt-2 space-y-1 font-body text-xs leading-5 text-hero-red">
                  {previewResult.warnings.map((warning, index) => <li key={`warning:${index}`}>{warning}</li>)}
                </ul>
              )}
              <details className="mt-3">
                <summary className="cursor-pointer py-2 font-meta text-xs font-bold text-ink-muted">{t("Reference images and instructions")}</summary>
                {previewResult.references.length > 0 && (
                  <ul className="mt-2 space-y-2">
                    {previewResult.references.map((reference) => (
                      <li key={reference.id} className="flex items-center gap-2 font-body text-xs leading-5">
                        {reference.image_path && (
                          <img
                            src={referenceFileUrl(project, reference.image_path)}
                            alt={reference.display_label ?? reference.label}
                            loading="lazy"
                            decoding="async"
                            className="h-12 w-12 shrink-0 border border-ink-black/30 object-cover"
                          />
                        )}
                        <span>{reference.display_label ?? reference.label}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap font-body text-xs leading-5">
                  {previewResult.instruction}
                </p>
                <ul className="mt-2 space-y-1 font-mono text-[0.65rem] leading-4 text-ink-muted">
                  <li>{previewResult.prompt_characters} {t("characters")} · {previewResult.lettering_count} {t("lettering")} · {t("reserved")}: {previewResult.estimate.reserved_credits} · {previewResult.estimate.confidence}</li>
                  <li>{previewManualCount} {t("{count, plural, one {manual request} other {manual requests}}", { count: previewManualCount })} · Mode: {previewResult.mode}</li>
                </ul>
              </details>
              <Button
                className="mt-4 w-full"
                size="sm"
                onClick={runSubmit}
                disabled={locked || submit.isPending || !previewFresh || submittedJobId != null || !!manualInput.trim()}
              >
                {t(submit.isPending ? "Generating…" : "Generate revision")}
              </Button>
            </Surface>
          )}

          {(submitError || preview.error) && !submittedJobId && (
            <ErrorNotice error={submitError ?? preview.error} operation={submitError ? "generate" : "estimate"} />
          )}
        </div>
      </div>
    </section>
  );
}
