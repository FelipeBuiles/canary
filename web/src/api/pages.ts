import { apiFetch } from "./client";
import type {
  BookAdaptation,
  BookPlan,
  CompletePageDetail,
  CompletePagesResponse,
  FinishPreflight,
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

export function pageRenderUrl(project: string, pageNumber: number, revision: number): string {
  return `/api${projectPath(project)}/pages/${pageNumber}/renders/${revision}`;
}

export type PageRenderRendition = "thumbnail" | "reader";

export function pageRenderPreviewUrl(
  project: string,
  pageNumber: number,
  revision: number,
  rendition: PageRenderRendition,
): string {
  return `/api${projectPath(project)}/pages/${pageNumber}/renders/${revision}/preview/${rendition}`;
}

export function analyzeCompletePage(
  project: string,
  pageNumber: number,
): Promise<CompletePageDetail["analyses"][number]> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/analyze`, {
    method: "POST",
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

export function createPageIssue(
  project: string,
  pageNumber: number,
  requestedCorrection: string,
): Promise<PageIssue> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/issues`, {
    method: "POST",
    body: JSON.stringify({
      issue_type: "author_review",
      classification: "editorial_issue",
      correction_kind: "render_fidelity",
      correction_owner: "draw",
      evidence: [requestedCorrection],
      requested_correction: requestedCorrection,
    }),
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

export function correctPageIssue(
  project: string,
  pageNumber: number,
  issueId: string,
): Promise<{ status: "queued"; job: GenerationJob }> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/issues/${encodeURIComponent(issueId)}/correct`, {
    method: "POST",
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

export interface VisualReviewReport {
  page_number: number;
  render_revision: number;
  findings: { category: string; panel_number: number; observation: string; expected: string; correction: string }[];
  uncertain: string[];
}

export function reviewPageVisuals(project: string, pageNumber: number): Promise<VisualReviewReport> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/visual-review`, { method: "POST" });
}

export interface ProviderUsageSummary {
  artifact_link_error: string | null;
  cost_sources: Record<string, number>;
  known_cost_usd: number;
  call_count: number;
  failed_call_count: number;
  unknown_cost_count: number;
  artifact_calls_missing_from_events: number;
  complete: boolean;
  groups: { page_number: number | null; category: string; call_count: number; known_cost_usd: number; unknown_cost_count: number }[];
}

export function getProviderUsage(project: string): Promise<ProviderUsageSummary> {
  return apiFetch(`${projectPath(project)}/provider-usage`);
}

export function getVisualReviewEstimate(project: string, pageNumber: number): Promise<{ estimate_credits: number }> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/visual-review/estimate`);
}
