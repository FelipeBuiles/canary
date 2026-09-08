import { accountIdentity } from "../lib/accountEpoch";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getPageRenderCorrection,
  getPageVisualReview,
  getVisualReviewEstimate,
  previewPageCorrections,
  reviewPageVisuals,
  submitPageCorrections,
  type PageAnnotationKind,
  type PageCorrectionAnnotation,
  type PageCorrectionBody,
  type PageCorrectionChange,
  type PageCorrectionPreview,
  type PageCorrectionSubmission,
  type FrozenRenderCorrection,
} from "./pages";

export type {
  PageAnnotationKind,
  PageCorrectionAnnotation,
  PageCorrectionBody,
  PageCorrectionChange,
  PageCorrectionPreview,
  PageCorrectionSubmission,
  FrozenRenderCorrection,
};

function invalidatePageReview(qc: ReturnType<typeof useQueryClient>, project: string, pageNumber?: number) {
  qc.invalidateQueries({ queryKey: ["project", project, "complete-pages"] });
  if (pageNumber != null) {
    qc.invalidateQueries({ queryKey: ["project", project, "complete-pages", pageNumber] });
    qc.invalidateQueries({ queryKey: ["project", project, "page-visual-review", pageNumber] });
  }
  qc.invalidateQueries({ queryKey: ["project", project, "status"] });
  qc.invalidateQueries({ queryKey: ["project", project, "generation-jobs"] });
  qc.invalidateQueries({ queryKey: ["provider-usage", project] });
}

/** Explicit paid visual review. Findings persist as page issues. */
export function useReviewPageVisuals() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, pageNumber }: { project: string; pageNumber: number }) =>
      reviewPageVisuals(project, pageNumber),
    onSettled: (_data, _error, { project, pageNumber }) =>
      invalidatePageReview(qc, project, pageNumber),
  });
}

export function useVisualReviewEstimate(project: string, pageNumber: number, enabled: boolean) {
  return useQuery({
    queryKey: ["visual-review-estimate", project, pageNumber],
    queryFn: () => getVisualReviewEstimate(project, pageNumber),
    enabled,
    staleTime: 60_000,
  });
}

/** Saved visual-review envelope; read-only, never spends. Shown on reopen. */
export function useCachedVisualReview(project: string | undefined, pageNumber: number | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "page-visual-review", pageNumber],
    queryFn: () => getPageVisualReview(project!, pageNumber!),
    enabled: !!project && pageNumber != null && enabled,
    staleTime: 30_000,
  });
}
/** Exact submitted correction frozen into a render; null for initial draws. Never spends. */
export function useRenderCorrection(
  project: string | undefined,
  pageNumber: number | undefined,
  renderRevision: number | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "page-render-correction", pageNumber, renderRevision],
    queryFn: () => getPageRenderCorrection(project!, pageNumber!, renderRevision!),
    enabled: !!project && pageNumber != null && renderRevision != null && enabled,
    staleTime: 60_000,
  });
}

/** Explicit preview: compiled instruction, cost, context, references, warnings. No spend. */
export function useCorrectionPreview() {
  return useMutation({
    mutationFn: ({
      project,
      pageNumber,
      body,
    }: {
      project: string;
      pageNumber: number;
      body: PageCorrectionBody;
    }) => previewPageCorrections(project, pageNumber, body),
  });
}

/** The single submission: changes + note + marks -> one correction. */
export function useSubmitCorrections() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      project,
      pageNumber,
      body,
    }: {
      project: string;
      pageNumber: number;
      body: PageCorrectionBody;
    }) => submitPageCorrections(project, pageNumber, body),
    onSettled: (_data, _error, { project, pageNumber }) =>
      invalidatePageReview(qc, project, pageNumber),
  });
}

// ── Revision draft persistence ───────────────────────────────────────────────
// Keyed by project/page/canonical-revision/edit-source-render so annotations
// can never drift onto a newer render. A stored draft whose target no longer
// matches is stale and must be explicitly rebased or discarded, never
// silently migrated.

export interface PersistedDraftChange {
  id: string;
  issue_id?: string;
  instruction: string;
  selected: boolean;
  annotations: PageCorrectionAnnotation[];
}

export interface PersistedRevisionDraft {
  project: string;
  pageNumber: number;
  comicPageRevision: number;
  parentRenderRevision: number;
  comicPageSha256: string;
  changes: PersistedDraftChange[];
  note: string;
  contextSourceUnitIds: string[];
  updatedAt: string;
}

export interface DraftTarget {
  comicPageRevision: number;
  parentRenderRevision: number;
}

export function draftStorageKey(project: string, pageNumber: number, target: DraftTarget): string {
  return `${draftKeyPrefix(project, pageNumber)}${target.comicPageRevision}:${target.parentRenderRevision}`;
}

function draftKeyPrefix(project: string, pageNumber: number): string {
  return `canary.revision-draft:v2:${accountIdentity ?? "signed-out"}:${project}:${pageNumber}:`;
}

export function loadRevisionDraft(
  project: string,
  pageNumber: number,
  target: DraftTarget,
): PersistedRevisionDraft | null {
  try {
    const raw = window.localStorage.getItem(draftStorageKey(project, pageNumber, target));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedRevisionDraft;
    if (
      parsed.project !== project
      || parsed.pageNumber !== pageNumber
      || parsed.comicPageRevision !== target.comicPageRevision
      || parsed.parentRenderRevision !== target.parentRenderRevision
      || !Array.isArray(parsed.changes)
    ) {
      return null;
    }
    if (typeof parsed.note !== "string") parsed.note = "";
    if (!Array.isArray(parsed.contextSourceUnitIds)) parsed.contextSourceUnitIds = [];
    return parsed;
  } catch {
    return null;
  }
}

/** A draft stored under an older target: offered for explicit rebase, never auto-migrated. */
export function findStaleRevisionDraft(
  project: string,
  pageNumber: number,
  target: DraftTarget,
): PersistedRevisionDraft | null {
  try {
    let newest: PersistedRevisionDraft | null = null;
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (!key || !key.startsWith(draftKeyPrefix(project, pageNumber))) continue;
      if (key === draftStorageKey(project, pageNumber, target)) continue;
      const raw = window.localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw) as PersistedRevisionDraft;
      if (!Array.isArray(parsed.changes)) continue;
      if (
        !newest
        || parsed.comicPageRevision > newest.comicPageRevision
        || (parsed.comicPageRevision === newest.comicPageRevision
          && parsed.parentRenderRevision > newest.parentRenderRevision)
      ) {
        newest = parsed;
      }
    }
    return newest;
  } catch {
    return null;
  }
}

export function saveRevisionDraft(draft: PersistedRevisionDraft): void {
  try {
    window.localStorage.setItem(
      draftStorageKey(draft.project, draft.pageNumber, draft),
      JSON.stringify(draft),
    );
  } catch {
    // Storage pressure must never block the correction flow.
  }
}

export function clearRevisionDraft(project: string, pageNumber: number, target: DraftTarget): void {
  try {
    window.localStorage.removeItem(draftStorageKey(project, pageNumber, target));
  } catch {
    // Ignore: clearing is best-effort cleanup after a successful submission.
  }
}

export function newChangeId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `change-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;
}
