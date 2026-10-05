import type { GenerationJob } from "../../types/api";

export type StylePhase = "queued" | "directions" | "production" | "proofs";

export interface ShortlistEntry {
  label: string;
  medium: string;
  role: string;
  palette?: string;
  story_fit?: string;
}

export const STEPS: { phase: Exclude<StylePhase, "queued">; label: string }[] = [
  { phase: "directions", label: "Choose directions" },
  { phase: "production", label: "Design lettering" },
  { phase: "proofs", label: "Paint proofs" },
];

export function stylePhaseOf(job: GenerationJob | undefined, fallback: StylePhase): StylePhase {
  if (job?.status === "queued") return "queued";
  const phase = job?.payload.style_phase;
  return phase === "directions" || phase === "production" || phase === "proofs" ? phase : fallback;
}

export function shortlistOf(job: GenerationJob | undefined): ShortlistEntry[] {
  const entries = job?.payload.style_shortlist;
  return Array.isArray(entries)
    ? entries.filter((entry): entry is ShortlistEntry =>
      !!entry && typeof entry === "object" && typeof (entry as ShortlistEntry).label === "string")
    : [];
}

export function proofCounts(job: GenerationJob | undefined): { done: number; total: number } {
  const proofs = job?.payload.proofs;
  if (!proofs || typeof proofs !== "object") return { done: 0, total: 0 };
  const values = Object.values(proofs as Record<string, { status?: string }>);
  return { done: values.filter((proof) => proof?.status === "complete").length, total: values.length };
}

/**
 * A one-line summary of a style batch for progress views outside the Look
 * room: the current step, and proof counts only once proofs are being painted,
 * since the earlier steps are not proofs.
 */
export function styleBatchSummary(job: GenerationJob | undefined): {
  step: number; steps: number; label: string; proofs: { done: number; total: number } | null;
} | null {
  if (!job || typeof job.payload?.style_phase !== "string") return null;
  const phase = stylePhaseOf(job, "directions");
  if (phase === "queued") return null;
  const step = STEPS.findIndex((item) => item.phase === phase);
  const counts = proofCounts(job);
  return { step: step + 1, steps: STEPS.length, label: STEPS[step].label,
    proofs: phase === "proofs" && counts.total > 0 ? counts : null };
}
