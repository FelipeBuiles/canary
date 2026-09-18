import { isOcrIssue } from "./lettering";
import { useEffect, useMemo, useRef, useState } from "react";
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
  type DraftTarget,
  type PersistedRevisionDraft,
} from "../../api/pageRevisions";
import {
  pageRenderPreviewUrl,
  referenceFileUrl,
  type PageCorrectionBody,
  type PageCorrectionChange,
} from "../../api/pages";
import { Button } from "../ui/Button";
import { FieldLabel, TextAreaField } from "../ui/Field";
import { Surface } from "../ui/Surface";
import { PageArtwork } from "./PageArtwork";
import { AnnotationEditor, type EditorAnnotation } from "./AnnotationEditor";
import {
  annotationProblem,
  MAX_CORRECTION_CHANGES,
  MAX_CORRECTION_INSTRUCTION,
  MAX_CORRECTION_MARKS,
  serializeAnnotation,
} from "./correctionValidation";
import type { VisualReviewDraftSeed } from "./VisualReviewPanel";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";

interface DraftChange {
  id: string;
  issueId?: string;
  instruction: string;
  selected: boolean;
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
        <p role="alert" className="mt-1 font-body text-xs text-hero-red">{(submitted.error as Error).message}</p>
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

interface RevisionDraftProps {
  project: string;
  pageNumber: number;
  /** Canonical page revision being corrected. */
  comicPageRevision: number;
  /** Render revision the redraw starts from. */
  parentRenderRevision: number;
  comicPageSha256: string;
  /** Older render used only for before/after comparison. */
  compareRevision: number | null;
  issues: PageIssue[];
  /** Seeds pushed from the visual review panel; consumed once merged. */
  seeds: VisualReviewDraftSeed[];
  onSeedsConsumed: () => void;
  onDraftKeysChange: (keys: string[]) => void;
  onJobQueued: (jobId: string) => void;
  disabled?: boolean;
}

function suggestibleIssues(issues: PageIssue[]): PageIssue[] {
  return issues.filter(
    (issue) =>
      (issue.status === "open" || issue.status === "revised")
      && issue.correction_owner === "draw",
  );
}

function changeFromIssue(issue: PageIssue): DraftChange {
  return {
    id: `issue:${issue.id}`,
    issueId: issue.id,
    instruction: issue.requested_correction,
    selected: !isOcrIssue(issue),
    annotations: [],
  };
}

function mergeSeeds(current: DraftChange[], seeds: VisualReviewDraftSeed[]): DraftChange[] {
  const byKey = new Map(current.map((change) => [change.id, change]));
  const byIssue = new Map(
    current.filter((change) => change.issueId).map((change) => [change.issueId!, change]),
  );
  const next = [...current];
  for (const seed of seeds) {
    if (seed.issueId && byIssue.has(seed.issueId)) {
      const existing = byIssue.get(seed.issueId)!;
      if (!existing.selected) {
        next.splice(next.indexOf(existing), 1, { ...existing, selected: true });
      }
      continue;
    }
    if (byKey.has(seed.key)) continue;
    next.push({
      id: seed.key,
      issueId: seed.issueId,
      instruction: seed.instruction,
      selected: true,
      annotations: [],
    });
  }
  return next;
}



/**
 * Scroll a newly revealed panel into view inside the nearest scrollable
 * ancestor (the modal body), never the page: entering editing/marking must
 * not leave the fresh controls clipped above the fold.
 */
function scrollLocalIntoView(node: HTMLElement | null) {
  if (!node || typeof window === "undefined") return;
  let container: HTMLElement | null = node.parentElement;
  while (container) {
    const overflowY = window.getComputedStyle(container).overflowY;
    if ((overflowY === "auto" || overflowY === "scroll") && container.scrollHeight > container.clientHeight) break;
    container = container.parentElement;
  }
  if (container) {
    const delta = node.getBoundingClientRect().top - container.getBoundingClientRect().top - 8;
    if (delta !== 0) container.scrollTop += delta;
  } else if (typeof node.scrollIntoView === "function") {
    node.scrollIntoView({ block: "start" });
  }
}

/**
 * Text-first correction draft. Locations are optional context attached to a
 * request, never a second required writing task. Requests submit after an
 * explicit preview. Persisted per
 * project/page/canonical-revision/edit-source-render; queued drafts lock
 * until the target changes.
 */
export function RevisionDraft({
  project,
  pageNumber,
  comicPageRevision,
  parentRenderRevision,
  comicPageSha256,
  compareRevision,
  issues,
  seeds,
  onSeedsConsumed,
  onDraftKeysChange,
  onJobQueued,
  disabled,
}: RevisionDraftProps) {
  const { t } = useI18n();
  const preview = useCorrectionPreview();
  const submit = useSubmitCorrections();
  const target: DraftTarget = { comicPageRevision, parentRenderRevision };

  const suggestions = useMemo(() => suggestibleIssues(issues), [issues]);
  const suggestionIds = useMemo(() => new Set(suggestions.map((issue) => issue.id)), [suggestions]);

  const [changes, setChanges] = useState<DraftChange[]>(() => {
    const persisted = loadRevisionDraft(project, pageNumber, target);
    if (persisted && persisted.changes.length > 0) {
      return persisted.changes.map((change) => ({
        id: change.id,
        issueId: change.issue_id,
        instruction: change.instruction,
        selected: change.selected,
        annotations: (change.annotations ?? []).map((mark) => ({ ...mark })),
      }));
    }
    return suggestions.map(changeFromIssue);
  });
  const [note, setNote] = useState(
    () => loadRevisionDraft(project, pageNumber, target)?.note ?? "",
  );
  const [manualInput, setManualInput] = useState(
    () => loadRevisionDraft(project, pageNumber, target)?.pendingRequest ?? "",
  );
  const [focusId, setFocusId] = useState<string | null>(null);
  const [previewHash, setPreviewHash] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submittedJobId, setSubmittedJobId] = useState<string | null>(null);
  const [staleDraft, setStaleDraft] = useState<PersistedRevisionDraft | null>(() =>
    loadRevisionDraft(project, pageNumber, target) ? null : findStaleRevisionDraft(project, pageNumber, target),
  );

  const locked = disabled || submit.isPending || submittedJobId != null;
  const focused = changes.find((change) => change.id === focusId)
    ?? changes.find((change) => change.selected)
    ?? changes[0]
    ?? null;

  // Editing stays closed until asked for or a visual-review seed arrives;
  // stored drafts are preserved but never force the rail open.
  const [editing, setEditing] = useState(() => seeds.length > 0);
  // Whether the page annotator is shown for the focused request; false keeps
  // the artwork a plain fitted image so controls never crowd it.
  const [marking, setMarking] = useState(false);
  const [comparison, setComparison] = useState<"before" | "after">("after");
  // Scroll only on explicit mode transitions (start editing, start marking,
  // hide editing). Mark updates and note edits never scroll: the intent flag
  // is consumed once by the effect below, so later renders stay put.
  const sectionRef = useRef<HTMLElement | null>(null);
  const artRef = useRef<HTMLElement | null>(null);
  const railRef = useRef<HTMLDivElement | null>(null);
  const markTopRef = useRef<HTMLDivElement | null>(null);
  const makeChangesWrapRef = useRef<HTMLDivElement | null>(null);
  const scrollIntentRef = useRef<"edit" | "mark" | "hide" | null>(null);
  useEffect(() => {
    const intent = scrollIntentRef.current;
    if (!intent) return;
    scrollIntentRef.current = null;
    if (intent === "edit") {
      scrollLocalIntoView(railRef.current);
      railRef.current?.querySelector<HTMLTextAreaElement>("textarea:not([disabled])")?.focus({ preventScroll: true });
    } else if (intent === "mark") {
      scrollLocalIntoView(markTopRef.current);
      markTopRef.current?.querySelector<HTMLButtonElement>('[role="toolbar"] button:not([disabled])')?.focus({ preventScroll: true });
    } else {
      scrollLocalIntoView(artRef.current ?? sectionRef.current);
      makeChangesWrapRef.current?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus({ preventScroll: true });
    }
  }, [editing, marking]);

  // Merge visual-review seeds once: known issues become selections, the rest new changes.
  // Own-state merge happens during render (the supported derived-state pattern);
  // parent notification stays in an effect since it sets parent state.
  const [lastSeeds, setLastSeeds] = useState<VisualReviewDraftSeed[]>([]);
  if (seeds !== lastSeeds && seeds.length > 0) {
    setLastSeeds(seeds);
    setChanges((current) => mergeSeeds(current, seeds));
    setEditing(true);
  }
  useEffect(() => {
    if (seeds.length > 0) onSeedsConsumed();
  }, [seeds, onSeedsConsumed]);

  // Persist every edit under the exact target key, but never resurrect a queued draft.
  useEffect(() => {
    if (submittedJobId) return;
    saveRevisionDraft({
      project,
      pageNumber,
      comicPageRevision,
      parentRenderRevision,
      comicPageSha256,
      changes: changes.map((change) => ({
        id: change.id,
        ...(change.issueId ? { issue_id: change.issueId } : {}),
        instruction: change.instruction,
        selected: change.selected,
        annotations: change.annotations,
      })),
      note,
      pendingRequest: manualInput,
      // No manual story-context selection: the backend assembles whole-book
      // context automatically. Stored passage ids from older drafts are
      // never re-submitted silently.
      contextSourceUnitIds: [],
      updatedAt: new Date().toISOString(),
    });
  }, [project, pageNumber, comicPageRevision, parentRenderRevision, comicPageSha256, changes, note, manualInput, submittedJobId]);

  useEffect(() => {
    onDraftKeysChange([
      ...changes.filter((change) => change.selected && change.issueId).map((change) => change.issueId!),
      ...changes.filter((change) => change.selected).map((change) => change.id),
    ]);
  }, [changes, onDraftKeysChange]);

  const selectedChanges = useMemo(() => changes.filter((change) => change.selected), [changes]);

  function buildBody(draftChanges = selectedChanges): { body: PageCorrectionBody; problems: string[] } {
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
        problems.push(t("One selected fix has no instruction yet."));
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
      const submitted = change.annotations.map(serializeAnnotation);
      bodyChanges.push({
        id: change.id,
        ...(change.issueId ? { issue_id: change.issueId } : {}),
        instruction,
        annotations: submitted,
      });
    }
    const trimmedNote = note.trim();
    if (trimmedNote.length > MAX_CORRECTION_INSTRUCTION) {
      problems.push(t("Shorten the overall note to 1000 characters."));
    }
    if (bodyChanges.length === 0 && trimmedNote.length === 0 && problems.length === 0) {
      problems.push(t("Describe what you would like to change. Marking the page is optional."));
    }
    return {
      body: {
        changes: bodyChanges,
        ...(trimmedNote ? { note: trimmedNote } : {}),
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
      ? { id: newChangeId(), instruction: manualInput.trim(), selected: true, annotations: [] }
      : null;
    const { body, problems } = buildBody(pendingRequest ? [...selectedChanges, pendingRequest] : selectedChanges);
    if (problems.length > 0) {
      setSubmitError(problems[0] ?? t("The draft is not ready to preview."));
      return;
    }
    if (pendingRequest) {
      setChanges((current) => [...current, pendingRequest]);
      setFocusId(pendingRequest.id);
      setManualInput("");
    }
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
          clearRevisionDraft(project, pageNumber, target);
          setPreviewHash(null);
          setSubmittedJobId(job.id);
          onJobQueued(job.id);
        },
        onError: (error) => {
          setSubmitError(error instanceof Error ? error.message : String(error));
          maybeShowInsufficientCredits(error, {
            actionLabel: t("SUBMIT ONE CORRECTION"),
            onRetry: runSubmit,
          });
        },
      },
    );
  }

  function addManual() {
    const instruction = manualInput.trim();
    if (!instruction || locked) return null;
    const change: DraftChange = {
      id: newChangeId(),
      instruction,
      selected: true,
      annotations: [],
    };
    setChanges((current) => [...current, change]);
    setFocusId(change.id);
    setManualInput("");
    return change.id;
  }

  function markPendingRequest() {
    const id = addManual();
    if (!id) return;
    scrollIntentRef.current = "mark";
    setMarking(true);
  }

  function rebaseStale(copy: boolean) {
    if (!staleDraft) return;
    if (copy) {
      setChanges((current) => {
        const known = new Set(current.map((change) => change.id));
        const rebased: DraftChange[] = staleDraft.changes
          .filter((change) => !known.has(`rebased:${change.id}`))
          .map((change) => ({
            id: `rebased:${change.id}`,
            instruction: change.instruction,
            selected: false,
            // Marks never migrate across renders: geometry belongs to the old image.
            annotations: [],
          }));
        if (typeof staleDraft.pendingRequest === "string" && staleDraft.pendingRequest.trim()) {
          rebased.push({ id: newChangeId(), instruction: staleDraft.pendingRequest, selected: false, annotations: [] });
        }
        const next = [...current, ...rebased];
        const knownIssues = new Set(next.filter((change) => change.issueId).map((change) => change.issueId!));
        for (const change of staleDraft.changes) {
          if (change.issue_id && suggestionIds.has(change.issue_id) && !knownIssues.has(change.issue_id)) {
            next.push({ ...changeFromIssue(suggestions.find((issue) => issue.id === change.issue_id)!), selected: false });
            knownIssues.add(change.issue_id);
          }
        }
        return next;
      });
      if (staleDraft.note && !note) setNote(staleDraft.note);
    }
    setStaleDraft(null);
  }

  const previewManualCount = previewResult?.pending_manual_change_ids.length ?? 0;
  const canvasSrc = pageRenderPreviewUrl(project, pageNumber, parentRenderRevision, "reader");
  const canvasAlt = `${t("Complete page")} ${pageNumber}, ${t("render revision")} ${parentRenderRevision}`;
  function startEditing() {
    if (locked) return;
    scrollIntentRef.current = "edit";
    setEditing(true);
    setMarking(false);
  }
  function hideEditing() {
    scrollIntentRef.current = "hide";
    setEditing(false);
    setMarking(false);
  }
  function toggleMarking(changeId: string) {
    setFocusId(changeId);
    if (!marking) scrollIntentRef.current = "mark";
    setMarking(!marking);
  }

  return (
    <section ref={sectionRef} aria-label={t("Page corrections")} className="space-y-4">
      {staleDraft && (
        <Surface tone="pulp" border="soft" shadow="none" padding="md" role="alert">
          <p className="font-body text-sm font-bold">
            {t("An older draft exists for page revision")} {staleDraft.comicPageRevision}
            {t(", render")} {staleDraft.parentRenderRevision}.
          </p>
          <p className="mt-1 font-body text-xs leading-5">
            {t("Marks stay with the old render and are never moved. You may copy the selections and wording only, or discard it.")}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="xs" onClick={() => rebaseStale(true)}>{t("COPY WORDING ONLY")}</Button>
            <Button size="xs" variant="outline" onClick={() => rebaseStale(false)}>{t("DISCARD OLD DRAFT")}</Button>
          </div>
        </Surface>
      )}

      {submittedJobId && (
        <Surface tone="container" border="soft" shadow="none" padding="md" role="status">
          <p className="font-body text-sm font-bold">{t("Correction queued. The draft is locked.")}</p>
          <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
            {t("Job")} {submittedJobId}. {t("The new revision will appear in the gallery; reopening then starts a fresh draft.")}
          </p>
        </Surface>
      )}

      <div className={editing ? "grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]" : "space-y-4"}>
        <div className="min-w-0 space-y-4">
          {!editing && !submittedJobId && (
            <div ref={makeChangesWrapRef} className="flex justify-end">
              <Button size="sm" variant="outline" onClick={startEditing} disabled={locked}>
                {t("MAKE CHANGES")}
              </Button>
            </div>
          )}
          {editing && focused && (marking || focused.annotations.length > 0) ? (
            <div ref={markTopRef} className="space-y-3">
              <p className="font-body text-sm leading-6 text-ink-muted">
                <span className="font-meta text-xs font-bold">{t("Locations for")}: </span>{focused.instruction}
              </p>
              <AnnotationEditor
                key={`${comicPageRevision}:${parentRenderRevision}:${focused.id}`}
                imageSrc={canvasSrc}
                alt={canvasAlt}
                value={focused.annotations}
                onChange={(annotations) => setChanges((current) => current.map((candidate) => candidate.id === focused.id
                  ? { ...candidate, annotations }
                  : candidate))}
                disabled={locked || !focused.selected}
                readOnly={!marking}
                maxMarks={Math.max(0, MAX_CORRECTION_MARKS - selectedChanges
                  .filter((change) => change.id !== focused.id)
                  .reduce((total, change) => total + change.annotations.length, 0))}
              />
            </div>
          ) : (
            <figure ref={artRef} className="flex h-[max(12rem,calc(100dvh-20rem))] justify-center">
              <PageArtwork src={canvasSrc} alt={canvasAlt} />
            </figure>
          )}
          {compareRevision != null && (
            <details className="border border-ink-black/20 px-3 py-2">
              <summary className="cursor-pointer font-meta text-xs font-bold text-ink-muted">
                {t("COMPARE WITH PREVIOUS RENDER")} ({t("Revision")} {compareRevision} → {t("Revision")} {parentRenderRevision})
              </summary>
              <div role="group" aria-label={t("Revision comparison")} className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" variant="outline" aria-pressed={comparison === "before"} onClick={() => setComparison("before")}>
                  {t("BEFORE")} · {t("Revision")} {compareRevision}
                </Button>
                <Button size="sm" variant="outline" aria-pressed={comparison === "after"} onClick={() => setComparison("after")}>
                  {t("AFTER")} · {t("Revision")} {parentRenderRevision}
                </Button>
              </div>
              <div className="mt-3 grid items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,0.6fr)]">
                <figure>
                  <img
                    src={comparison === "before" ? pageRenderPreviewUrl(project, pageNumber, compareRevision, "reader") : canvasSrc}
                    alt={`${t("Complete page")} ${pageNumber}, ${t(comparison === "before" ? "previous revision" : "current revision")} ${comparison === "before" ? compareRevision : parentRenderRevision}`}
                    loading="lazy"
                    decoding="async"
                    className="max-h-[70dvh] w-full object-contain"
                  />
                  <figcaption className="mt-2 text-sm font-bold" aria-live="polite">
                    {t(comparison === "before" ? "BEFORE" : "AFTER")} · {t("Revision")} {comparison === "before" ? compareRevision : parentRenderRevision}
                  </figcaption>
                </figure>
                <div className="space-y-3">
                  <p className="text-sm leading-6">{t("A new revision is not a confirmed fix. Compare the requested change and check for unintended differences.")}</p>
                <SubmittedCorrection
                  project={project}
                  pageNumber={pageNumber}
                  renderRevision={parentRenderRevision}
                />
                {issues.filter((issue) => issue.render_revision === compareRevision && (issue.status === "open" || issue.status === "revised")).length > 0 && (
                  <div>
                    <p className="font-meta text-xs font-bold text-ink-muted">
                      {t("STILL OPEN FROM THE PREVIOUS RENDER")}
                    </p>
                    <ul className="mt-1 space-y-1">
                      {issues
                        .filter((issue) => issue.render_revision === compareRevision && (issue.status === "open" || issue.status === "revised"))
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
            </details>
          )}
        </div>

        {editing && (
        <div ref={railRef} className={`min-w-0 space-y-5 border-t border-ink-black/15 pt-5 lg:order-none lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0 ${marking ? "" : "order-first"}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-display text-2xl font-black">{t("Request changes")}</h3>
            <Button size="sm" variant="outline" onClick={hideEditing}>
              {t("Back to page")}
            </Button>
          </div>
          <p className="font-body text-sm leading-6 text-ink-muted">
            {t("Text is enough. Optionally add a pin, area or highlight to show where. You’ll review the cost before generating.")}
          </p>
          {(!marking || !focused) && <div>
            <FieldLabel htmlFor="draft-manual">{t("What would you like to change?")}</FieldLabel>
            <div className="flex flex-col gap-2">
              <TextAreaField
                id="draft-manual"
                value={manualInput}
                disabled={locked}
                maxLength={MAX_CORRECTION_INSTRUCTION}
                rows={4}
                placeholder={t("For example: make his hair pink in the first panel, keeping his face and the lighting unchanged.")}
                onChange={(event) => setManualInput(event.target.value)}
              />
              <p className="font-body text-xs leading-5 text-ink-muted">
                {t("Go straight to Review changes, or add context below.")}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button size="xs" variant="outline" onClick={markPendingRequest} disabled={locked || !manualInput.trim()}>
                  {t("Add location (optional)")}
                </Button>
                <Button size="xs" variant="outline" onClick={addManual} disabled={locked || !manualInput.trim()}>
                  {t("Add request")}
                </Button>
              </div>
            </div>
          </div>}

          {changes.length > 0 && (
            <div className="border-t border-ink-black/15 pt-4">
              <h4 className="font-meta text-xs font-bold uppercase tracking-wider">{t("Requests to include")}</h4>
              <p className="mt-1 font-body text-xs leading-5 text-ink-muted">{t("Checked requests will be included. Select any request to edit it.")}</p>
            </div>
          )}
          {suggestions.filter((issue) => !changes.some((change) => change.issueId === issue.id)).map((issue) => (
            <div key={issue.id} className="flex flex-wrap items-center justify-between gap-2 border border-dashed border-ink-black/30 px-3 py-2">
              <span className="font-body text-xs">{issue.requested_correction}</span>
              <Button
                size="xs"
                variant="outline"
                disabled={locked}
                onClick={() => setChanges((current) => [...current, changeFromIssue(issue)])}
              >
                {t("ADD TO DRAFT")}
              </Button>
            </div>
          ))}

          {changes.length === 0 ? (
            <p className="font-body text-sm text-ink-muted">
              {t("Your requests will appear here once added.")}
            </p>
          ) : (
            <ol className="space-y-2">
              {changes.map((change) => {
                const summary = change.instruction.trim() || t("Empty request");
                if (focused?.id !== change.id) {
                  return (
                    <li key={change.id} className="flex items-start gap-2 border border-ink-black/20 px-2 py-2">
                      <label className="flex min-h-11 min-w-11 shrink-0 cursor-pointer items-center justify-center">
                      <input
                        type="checkbox"
                        checked={change.selected}
                        disabled={locked}
                        onChange={(event) => setChanges((current) => current.map((candidate) => candidate.id === change.id
                          ? { ...candidate, selected: event.target.checked }
                          : candidate))}
                        aria-label={`${t("Include fix")}: ${change.instruction.slice(0, 80)}`}
                        className="h-4 w-4 shrink-0 accent-hero-red"
                      />
                      </label>
                      <button
                        type="button"
                        onClick={() => setFocusId(change.id)}
                        aria-label={`${t("Edit request")}: ${change.instruction.slice(0, 80)}`}
                        className="min-h-11 min-w-0 flex-1 py-2 text-left font-body text-sm leading-6 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red"
                      >
                        {summary}
                      </button>
                      {change.annotations.length > 0 && (
                        <span className="shrink-0 font-meta text-xs font-bold text-ink-muted">
                          {change.annotations.length} {t(change.annotations.length === 1 ? "location" : "locations")}
                        </span>
                      )}
                    </li>
                  );
                }
                return (
                <li key={change.id}>
                  <Surface tone={change.selected ? "bristol" : "container"} border="soft" shadow="none" padding="md">
                    <div className="flex items-start gap-3">
                      <label className="flex min-h-11 min-w-11 shrink-0 cursor-pointer items-center justify-center">
                      <input
                        type="checkbox"
                        checked={change.selected}
                        disabled={locked}
                        onChange={(event) => setChanges((current) => current.map((candidate) => candidate.id === change.id
                          ? { ...candidate, selected: event.target.checked }
                          : candidate))}
                        aria-label={`${t("Include fix")}: ${change.instruction.slice(0, 80)}`}
                        className="h-4 w-4 shrink-0 accent-hero-red"
                      />
                      </label>
                      <div className="min-w-0 flex-1 space-y-2">
                        {change.annotations.length > 0 && (
                          <p className="font-meta text-xs font-bold text-ink-muted">
                            {change.annotations.length} {t(change.annotations.length === 1 ? "location" : "locations")}
                          </p>
                        )}
                        <FieldLabel htmlFor={`draft-instruction-${change.id}`}>
                          {t("Request")}
                        </FieldLabel>
                        <TextAreaField
                          id={`draft-instruction-${change.id}`}
                          value={change.instruction}
                          disabled={locked || !change.selected}
                          rows={3}
                          maxLength={MAX_CORRECTION_INSTRUCTION}
                          onChange={(event) => setChanges((current) => current.map((candidate) => candidate.id === change.id
                            ? { ...candidate, instruction: event.target.value }
                            : candidate))}
                        />
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant={marking ? undefined : "outline"}
                            disabled={locked || (!change.selected && !marking)}
                            aria-pressed={marking}
                            onClick={() => toggleMarking(change.id)}
                          >
                            {t(marking ? "DONE MARKING" : "MARK ON PAGE (OPTIONAL)")}
                          </Button>
                          {!change.issueId && (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={locked}
                              onClick={() => setChanges((current) => current.filter((candidate) => candidate.id !== change.id))}
                            >
                              {t("REMOVE")}
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  </Surface>
                </li>
                );
              })}
            </ol>
          )}

          <p className="font-body text-xs leading-5 text-ink-muted">
            {t("Approved style and character references are included automatically. Review changes to see the exact reference images before generating.")}
          </p>
          <details>
            <summary className="cursor-pointer py-3 font-meta text-xs font-bold text-ink-muted">
              {t("Overall note (optional)")}
            </summary>
            <div className="mt-2">
              <FieldLabel htmlFor="draft-note" className="sr-only">{t("Overall note (optional)")}</FieldLabel>
              <TextAreaField
                id="draft-note"
                maxLength={MAX_CORRECTION_INSTRUCTION}
                value={note}
                disabled={locked}
                placeholder={t("Guidance the individual fixes do not cover.")}
                onChange={(event) => setNote(event.target.value)}
              />
            </div>
          </details>


          {!previewFresh && !submittedJobId && (
            <div className="space-y-2 border-t border-ink-black/15 pt-4">
              <Button className="w-full" size="sm" onClick={runPreview} disabled={locked || preview.isPending}>
                {t(preview.isPending ? "Reviewing…" : "Review changes")}
              </Button>
              <p className="font-body text-xs leading-5 text-ink-muted">
                {t("Review the estimate and included requests before you confirm.")}
              </p>
            </div>
          )}
          {preview.data && !previewFresh && !submittedJobId && (
            <p role="status" className="font-body text-xs font-bold text-hero-red">
              {t("Your requests changed. Review them again before generating.")}
            </p>
          )}

          {previewResult && (
            <Surface tone="container" border="soft" shadow="none" padding="md" aria-live="polite">
              <h4 className="font-display text-lg font-bold">{t("Ready to generate")}</h4>
              <p className="mt-2 font-body text-lg font-bold">
                {t("Estimated cost:")} ~{previewResult.estimate.estimate_credits} {t("credits")}
              </p>
              <p className="mt-1 font-body text-xs text-ink-muted">
                {previewResult.changes.length} {t(previewResult.changes.length === 1 ? "selected fix" : "selected fixes")}
              </p>
              {previewResult.unselected_open_issue_ids.length > 0 && (
                <div className="mt-2">
                  <p className="font-body text-xs leading-5">
                    <span className="font-bold">{t("Left out:")} </span>
                    {previewResult.unselected_open_issue_ids.length} {t(previewResult.unselected_open_issue_ids.length === 1
                      ? "open finding stays open after this revision."
                      : "open findings stay open after this revision.")}
                    <Button
                      className="ml-2"
                      size="xs"
                      variant="outline"
                      disabled={locked}
                      onClick={() => setChanges((current) => {
                        const leftOut = new Set(previewResult.unselected_open_issue_ids);
                        const known = new Set(current.filter((change) => change.issueId).map((change) => change.issueId!));
                        const additions = suggestions
                          .filter((issue) => leftOut.has(issue.id) && !known.has(issue.id))
                          .map(changeFromIssue);
                        return [
                          ...current.map((change) => change.issueId && leftOut.has(change.issueId) && !change.selected
                            ? { ...change, selected: true }
                            : change),
                          ...additions,
                        ];
                      })}
                    >
                      {t("SELECT ALL OPEN")}
                    </Button>
                  </p>
                  <ul className="mt-1 space-y-1">
                    {previewResult.unselected_open_issue_ids.map((issueId) => {
                      const issue = issues.find((candidate) => candidate.id === issueId);
                      return (
                        <li key={issueId} className="font-body text-xs leading-5 text-ink-muted">
                          {issue ? issue.requested_correction : t("An open finding with no cached summary.")}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
              {previewResult.context.truncated && (
                <p className="mt-2 font-body text-xs font-bold">{t("Context truncated to fit.")}</p>
              )}
              <details className="mt-4 border-t border-ink-black/15 pt-3">
                <summary className="cursor-pointer py-2 font-meta text-xs font-bold text-ink-muted">{t("Reference images and instructions")}</summary>
              {previewResult.references.length > 0 && (
                <div className="mt-2">
                  <p className="font-meta text-xs font-bold text-ink-muted">{t("REFERENCES COMPARED")}</p>
                  <ul className="mt-1 space-y-2">
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
                </div>
              )}
              <div className="mt-4">
                <p className="font-meta text-xs font-bold text-ink-muted">
                  {t("COMPILED INSTRUCTION")} ({previewResult.prompt_characters} {t("characters")}, {previewResult.lettering_count} {t("lettering")})
                </p>
                <p className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-body text-xs leading-5">
                  {previewResult.instruction}
                </p>
                <details className="mt-2">
                  <summary className="cursor-pointer font-meta text-xs font-bold text-ink-muted">
                    {t("Technical details")}
                  </summary>
                  <ul className="mt-1 space-y-1 font-mono text-[0.65rem] leading-4 text-ink-muted">
                    <li>{t("reserved")}: {previewResult.estimate.reserved_credits} · {previewResult.estimate.confidence}</li>
                    <li>{previewManualCount} {t(previewManualCount === 1 ? "manual request" : "manual requests")}</li>
                    <li>Mode: {previewResult.mode}</li>
                    <li>Selected issues: {previewResult.selected_issue_ids.join(", ") || "—"}</li>
                    <li>Manual change ids: {previewResult.pending_manual_change_ids.join(", ") || "—"}</li>
                    <li>Left-out issues: {previewResult.unselected_open_issue_ids.join(", ") || "—"}</li>
                  </ul>
                </details>
              </div>
              </details>
              {previewResult.warnings.length > 0 && (
                <div className="mt-2">
                  <p className="font-meta text-xs font-bold text-hero-red">{t("WARNINGS")}</p>
                  <ul className="mt-1 space-y-1 font-body text-xs leading-5">
                    {previewResult.warnings.map((warning, index) => (
                      <li key={`warning:${index}`}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}
              <Button
                className="mt-5 w-full"
                size="sm"
                onClick={runSubmit}
                disabled={locked || submit.isPending || !previewFresh || submittedJobId != null || !!manualInput.trim()}
              >
                {t(submit.isPending ? "Generating…" : "Generate revision")}
              </Button>
            </Surface>
          )}

          {(submitError || preview.error) && !submittedJobId && (
            <p role="alert" className="border-l-[3px] border-hero-red pl-3 font-body text-xs font-bold leading-5 text-hero-red">
              {submitError ?? (preview.error as Error).message}
            </p>
          )}
        </div>
        )}
      </div>
    </section>
  );
}
