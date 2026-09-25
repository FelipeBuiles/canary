import { apiFetch, isNotFoundError } from "./client";
import type {
  BookAdaptation,
  BookPlan,
  CompletePageDetail,
  CompletePagesResponse,
  CostEstimate,
  FinishPreflight,
  PageSourceView,
  GenerationJob,
  PageIssue,
  StageValidation,
} from "../types/api";

const projectPath = (project: string) => `/projects/${encodeURIComponent(project)}`;

export function getAdaptation(project: string): Promise<BookAdaptation> {
  return apiFetch(`${projectPath(project)}/adaptation`);
}

export function getBookPlan(project: string): Promise<BookPlan> {
  return apiFetch(`${projectPath(project)}/book-plan`);
}

/** Adapt and Plan persist their own verdict so a block can explain itself. */
export function getStageValidation(
  project: string,
  stage: "adapt" | "plan",
): Promise<StageValidation> {
  return apiFetch(`${projectPath(project)}/validation/${stage}`);
}

export function listCompletePages(project: string): Promise<CompletePagesResponse> {
  return apiFetch(`${projectPath(project)}/pages`);
}

export function getCompletePage(project: string, pageNumber: number): Promise<CompletePageDetail> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}`);
}

/** Provider-free read of the manuscript passages this page adapts. */
export function getPageSource(project: string, pageNumber: number): Promise<PageSourceView> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/source`);
}

// The delivery version bypasses previously year-cached URLs. The server now
// requires revalidation because a restart can reuse a page/revision number.
export function pageRenderUrl(project: string, pageNumber: number, revision: number): string {
  return `/api${projectPath(project)}/pages/${pageNumber}/renders/${revision}?delivery=2`;
}

export type PageRenderRendition = "thumbnail" | "reader";

export function pageRenderPreviewUrl(
  project: string,
  pageNumber: number,
  revision: number,
  rendition: PageRenderRendition,
): string {
  return `/api${projectPath(project)}/pages/${pageNumber}/renders/${revision}/preview/${rendition}?delivery=2`;
}

export function analyzeCompletePage(
  project: string,
  pageNumber: number,
): Promise<CompletePageDetail["analyses"][number]> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/analyze`, {
    method: "POST",
  });
}

export function getCompletePageBatchEstimate(project: string): Promise<CostEstimate> {
  return apiFetch(`${projectPath(project)}/pages/generate/estimate`);
}

export function getCompletePageEstimate(
  project: string,
  pageNumber: number,
  depiction: "canonical" | "less_graphic" = "canonical",
): Promise<CostEstimate> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/generate/estimate?depiction=${depiction}`);
}

export function getPageAnalysisEstimate(project: string, pageNumber: number): Promise<CostEstimate> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/analyze/estimate`);
}

export interface PageCheckEstimate extends CostEstimate {
  pages: Array<{ page_number: number; status: string; requires_paid_call: boolean; render_image_sha256: string | null }>;
  paid_pages: number;
}

export function getPageCheckEstimate(project: string): Promise<PageCheckEstimate> {
  return apiFetch(`${projectPath(project)}/pages/checks/estimate`);
}

export function recoverPageChecks(project: string, allowPaid = false, renders: Record<number, string> = {}): Promise<{
  pages: Array<{ page_number: number; status: string; error?: string }>;
}> {
  return apiFetch(`${projectPath(project)}/pages/checks/recover`, {
    method: "POST", body: JSON.stringify({ allow_paid: allowPaid, renders }),
  });
}

export function generateCompletePage(
  project: string,
  pageNumber: number,
  depiction: "canonical" | "less_graphic" = "canonical",
): Promise<{ status: "queued"; job: GenerationJob }> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/generate`, {
    method: "POST",
    body: JSON.stringify({ depiction }),
  });
}
export function acceptPageIssue(
  project: string,
  pageNumber: number,
  issueId: string,
): Promise<PageIssue> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/issues/${encodeURIComponent(issueId)}/accept`, {
    method: "POST",
  });
}

export function dismissPageIssue(
  project: string,
  pageNumber: number,
  issueId: string,
): Promise<PageIssue> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/issues/${encodeURIComponent(issueId)}/dismiss`, {
    method: "POST",
  });
}

/** Normalized annotation geometry. Points are 0..1 fractions of the full page
 * image (x right, y down). Notes render into the redraw prompt and are never
 * dropped. */
export interface PageAnnotationPoint {
  x: number;
  y: number;
}

export type PageAnnotationKind = "pin" | "rectangle" | "highlight" | "freehand" | "arrow";

export interface PageCorrectionAnnotation {
  id: string;
  kind: PageAnnotationKind;
  points: PageAnnotationPoint[];
  note?: string;
  label?: string;
}

export interface PageCorrectionChange {
  /** Client-generated stable id, unique within the submission. */
  id: string;
  /** Existing tracked issue this change answers. */
  issue_id?: string;
  /** Editable instruction for the redraw. */
  instruction: string;
  annotations: PageCorrectionAnnotation[];
}

/**
 * Correction body: editable changes with marks, an overall manual note, and
 * explicitly selected passages. Preview and submit take identical bodies;
 * preview never creates issues, submit creates real PageIssues then queues.
 */
export interface PageCorrectionBody {
  changes: PageCorrectionChange[];
  note?: string;
  context_source_unit_ids?: string[];
  parent_render_revision: number;
  comic_page_revision: number;
  comic_page_sha256: string;
}

export interface PageCorrectionReference {
  order: number;
  id: string;
  entity_id: string;
  appearance_state_id: string | null;
  label: string;
  display_label?: string | null;
  visual_anchor: string | null;
  media_type: string;
  image_path?: string | null;
}

/** Project-relative reference bytes served by the generic files route. */
export function referenceFileUrl(project: string, imagePath: string): string {
  const segments = imagePath.split("/").map((segment) => encodeURIComponent(segment));
  return `/api${projectPath(project)}/files/${segments.join("/")}`;
}

/** Exact submitted correction frozen into the render's generation request. */
export interface FrozenRenderCorrection {
  page_number: number;
  render_revision: number;
  parent_render_revision: number;
  request_sha256: string;
  correction: {
    mode: string;
    changes: Array<{
      id: string;
      issue_id: string | null;
      instruction: string;
      annotations: PageCorrectionAnnotation[];
    }>;
    note: string;
  } | null;
}

/** Null when the render was an initial draw or the record is missing. Never spends. */
export async function getPageRenderCorrection(
  project: string,
  pageNumber: number,
  renderRevision: number,
): Promise<FrozenRenderCorrection | null> {
  try {
    return await apiFetch(
      `${projectPath(project)}/pages/${pageNumber}/renders/${renderRevision}/correction`,
    );
  } catch (error) {
    if (isNotFoundError(error)) return null;
    throw error;
  }
}

export interface PageCorrectionPreviewChange {
  id: string;
  issue_id: string | null;
  instruction: string;
}

export interface PageCorrectionPreview {
  selected_issue_ids: string[];
  unselected_open_issue_ids: string[];
  pending_manual_change_ids: string[];
  changes: PageCorrectionPreviewChange[];
  note: string | null;
  mode: string;
  instruction: string;
  context: {
    adaptation_revision: number;
    adaptation_sha256: string;
    treatment_spine: string[];
    beat_ids: string[];
    beat_count: number;
    appearance_chronology: string[];
    continuity: string[];
    source_unit_ids: string[];
    selected_source_unit_ids: string[];
    omitted_source_unit_ids: string[];
    context_digest: string;
    truncated: boolean;
  };
  references: PageCorrectionReference[];
  profile: { id: string; provider: string; model: string };
  lettering_count: number;
  prompt_characters: number;
  request_sha256: string;
  warnings: string[];
  estimate: CostEstimate;
}

export interface PageCorrectionSubmission {
  status: "queued";
  job: GenerationJob;
  selected_issue_ids: string[];
}

export function previewPageCorrections(
  project: string,
  pageNumber: number,
  body: PageCorrectionBody,
): Promise<PageCorrectionPreview> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/corrections/preview`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function submitPageCorrections(
  project: string,
  pageNumber: number,
  body: PageCorrectionBody,
): Promise<PageCorrectionSubmission> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/corrections`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getFinishPreflight(project: string): Promise<FinishPreflight> {
  return apiFetch(`${projectPath(project)}/export/preflight`);
}

export function runFinishPreflight(
  project: string,
): Promise<{ status: "done"; preflight: FinishPreflight }> {
  return apiFetch(`${projectPath(project)}/export/preflight`, {
    method: "POST",
  });
}

export function triggerExport(
  project: string,
  format: "pdf" | "cbz",
  force = false,
): Promise<{
  status: string;
  path: string;
  url: string | null;
  preflight?: FinishPreflight;
}> {
  const params = new URLSearchParams({ format });
  if (force) params.set("force", "1");
  return apiFetch(`${projectPath(project)}/export/?${params.toString()}`, {
    method: "POST",
  });
}

export function downloadExportUrl(project: string, format: "pdf" | "cbz"): string {
  return `/api${projectPath(project)}/export/${format}`;
}

export interface VisualReviewFinding {
  category: string;
  panel_number: number;
  observation: string;
  expected: string;
  correction: string;
  /** Present once the finding has persisted as a page issue. */
  issue_id?: string | null;
}

export interface VisualFindingIssue {
  finding_index: number;
  category: string;
  panel_number: number;
  issue_id: string;
  issue_type: string;
  correction_owner: string;
  issue_status: string | null;
  /** False when no persisted issue exists: never seed drafts from these. */
  available?: boolean;
}

export interface VisualReviewReference {
  order: number;
  id: string;
  entity_id: string;
  appearance_state_id: string | null;
  label: string;
  display_label?: string | null;
  visual_anchor: string | null;
  media_type: string;
  image_path: string | null;
}

export interface VisualReviewReport {
  page_number: number;
  render_revision: number;
  findings: VisualReviewFinding[];
  uncertain: string[];
}

export interface CachedVisualReview {
  cached: boolean;
  page_number: number;
  render_revision: number;
  render_image_sha256: string;
  report: VisualReviewReport | null;
  finding_issues: VisualFindingIssue[];
  references: VisualReviewReference[];
}

export function reviewPageVisuals(project: string, pageNumber: number): Promise<VisualReviewReport> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/visual-review`, { method: "POST" });
}

/** Read-only cached visual review envelope; never spends. Report is null when none saved. */
export async function getPageVisualReview(
  project: string,
  pageNumber: number,
): Promise<CachedVisualReview | null> {
  try {
    return await apiFetch(`${projectPath(project)}/pages/${pageNumber}/visual-review`);
  } catch (error) {
    if (isNotFoundError(error)) return null;
    throw error;
  }
}

export function getVisualReviewEstimate(project: string, pageNumber: number): Promise<CostEstimate> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/visual-review/estimate`);
}

/** Price one page's plan repair; rejects when the page's plan has nothing to repair. */
export function getPageReplanEstimate(project: string, pageNumber: number): Promise<CostEstimate> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/replan/estimate`);
}

/** Rewrite one page's plan; its artwork then needs a redraw from Pages. */
export function replanPage(project: string, pageNumber: number): Promise<{ page_number: number; revision: number }> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/replan`, { method: "POST" });
}
