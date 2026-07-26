import { apiFetch } from "./client";
import type {
  BookAdaptation,
  BookPlan,
  CompletePageDetail,
  CompletePagesResponse,
  FinishPreflight,
  GenerationJob,
  PageIssue,
} from "../types/api";

const projectPath = (project: string) => `/projects/${encodeURIComponent(project)}`;

export function getAdaptation(project: string): Promise<BookAdaptation> {
  return apiFetch(`${projectPath(project)}/adaptation`);
}

export function getBookPlan(project: string): Promise<BookPlan> {
  return apiFetch(`${projectPath(project)}/book-plan`);
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

export function generateCompletePage(
  project: string,
  pageNumber: number,
): Promise<{ status: "queued"; job: GenerationJob }> {
  return apiFetch(`${projectPath(project)}/pages/${pageNumber}/generate`, {
    method: "POST",
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
  return apiFetch(`${projectPath(project)}/files/finish/preflight.json`);
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
