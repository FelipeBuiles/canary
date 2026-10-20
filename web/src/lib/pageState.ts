import type { CompletePageSummary, GenerationJob } from "../types/api";
import { pageCompositePreviewUrl } from "../api/lettering";
import { pageRenderPreviewUrl } from "../api/pages";
import { isGenerationActive } from "./generationTracking";

export function pageDisplayImage(project: string, page: { pageNumber: number; revision: number; hybrid?: boolean; letteringRevision?: number | null }, size: "reader" | "thumbnail" = "reader") {
  return page.hybrid
    ? pageCompositePreviewUrl(project, page.pageNumber, page.revision, size, page.letteringRevision)
    : pageRenderPreviewUrl(project, page.pageNumber, page.revision, size);
}

export function pageState(item: CompletePageSummary, input: { starting?: boolean; batch?: boolean; drawFailed?: boolean; submitted?: boolean; job?: GenerationJob; failure?: GenerationJob } = {}) {
  const revision = item.active_render?.render.revision;
  const drawing = !!(input.starting || (input.batch && !input.drawFailed) || input.submitted || isGenerationActive(input.job));
  const revised = item.issues.some(issue => issue.status === "revised");
  const openIssues = item.issues.filter(issue => issue.status === "open").length;
  const failure = item.analysis_recovery?.status === "checked" ? null
    : item.failure ?? input.failure ?? (input.job?.status === "failed" ? input.job : null);
  const failurePhase = revision && item.analysis_recovery?.status !== "checked" ? "analysis" : failure?.phase;
  const badge = drawing && revision ? "revising"
    : revision && item.analysis_recovery?.status === "stale_render" ? "stale"
    : revision && item.redraw?.changed_references.length ? "earlier-look"
    : revised ? "confirm-fix"
    : openIssues > 0 ? "flagged"
    : item.lettering_placement_review_needed ? "placement" : null;
  return { revision, drawing, failure, failurePhase, badge, openIssues, needsReview: revised || openIssues > 0,
    failed: !drawing && !item.active_render && !!(input.job?.status === "failed" || input.failure || item.failure),
    canRetryGeneration: !!failure?.recoverable && !revision && !drawing && failure.classification !== "provider_blocked" };
}
