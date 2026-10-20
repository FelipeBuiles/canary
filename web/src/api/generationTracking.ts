import type { QueryClient } from "@tanstack/react-query";
import type { GenerationJob } from "../types/api";
import { invalidateProject } from "./projectScope";
import { invalidatePageReview } from "./pageCache";

/** Admission seeds the shared poll, so every observer sees a submitted job immediately. */
export function seedGenerationJob(qc: QueryClient, project: string, job: GenerationJob) {
  qc.setQueryData<GenerationJob[]>(["project", project, "generation-admissions"], current =>
    [...(current ?? []).filter(existing => existing.id !== job.id), job]);
  const key = ["project", project, "generation-jobs", []];
  qc.setQueryData<{ jobs: GenerationJob[]; current_reference_style_hash?: string }>(key, current => ({
    ...current,
    jobs: current?.jobs.some(existing => existing.id === job.id) ? current.jobs : [...(current?.jobs ?? []), job],
  }));
  void invalidateProject(qc, project, "generation-jobs");
}

/** Refresh dependent evidence for a settled job, including cancellation. */
export function invalidateGenerationResult(qc: QueryClient, project: string, job: GenerationJob) {
  const resources = job.kind === "complete_page_draw"
    ? []
    : job.kind === "lettering_translation"
      ? ["complete-pages", "lettering", "lettering-languages", "lettering-translation-estimate", "finish-preflight"]
      : job.kind.startsWith("style_") || job.kind === "suggest_styles"
        ? ["styles", "estimate"]
        : ["image-generation-meta", "asset-regen-estimate", "character-ref-versions", "location-plate-versions", "cast-asset-versions", "story-bible", "cast-freshness"];
  if (job.kind === "complete_page_draw") {
    const pageNumber = Number(job.payload.page_number);
    invalidatePageReview(qc, project, Number.isSafeInteger(pageNumber) && pageNumber > 0 ? pageNumber : undefined);
  }
  if (!["complete_page_draw", "lettering_translation"].includes(job.kind) && !job.kind.startsWith("style_") && job.kind !== "suggest_styles") {
    void qc.invalidateQueries({ queryKey: ["cast-review", project] });
  }
  for (const resource of [...resources, "status"]) void invalidateProject(qc, project, resource);
  void qc.invalidateQueries({ queryKey: ["credits"] });
}
