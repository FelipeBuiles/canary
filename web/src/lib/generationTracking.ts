import type { GenerationJob } from "../types/api";

export function isGenerationActive(job: Pick<GenerationJob, "status"> | null | undefined): boolean {
  return job?.status === "queued" || job?.status === "running";
}
export function isGenerationTerminal(job: Pick<GenerationJob, "status"> | null | undefined): boolean {
  return job?.status === "complete" || job?.status === "failed" || job?.status === "cancelled";
}
export function isCurrentReferenceJob(job: GenerationJob, styleHash?: string | null): boolean {
  return !styleHash || job.reference_style_hash === styleHash;
}
export type GenerationSubject = { kind?: string; currentStyle?: boolean; identity?: string; value?: string | number; currentStyleHash?: string | null; currentPage?: boolean; id?: string };
/** Admission seeds remain visible before polling catches up; a poll wins ties. */
export function generationStatus(subject: GenerationSubject, jobs: GenerationJob[], admitted?: GenerationJob | null): GenerationJob | null {
  let latest: GenerationJob | null = null;
  for (const job of [...(admitted ? [admitted] : []), ...jobs]) {
    if (subject.id && job.id !== subject.id) continue;
    if (subject.kind && job.kind !== subject.kind) continue;
    if (subject.identity && job.payload[subject.identity] !== subject.value) continue;
    if (subject.currentPage && job.is_current_page === false) continue;
    if (!isCurrentReferenceJob(job, subject.currentStyleHash)) continue;
    if (!latest || Date.parse(job.queued_at) >= Date.parse(latest.queued_at)) latest = job;
  }
  return latest;
}
