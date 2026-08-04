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
