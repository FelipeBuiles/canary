import { useMutationState, useQuery } from "@tanstack/react-query";
import { useGenerationJobs } from "./queries";
import { apiFetch } from "./client";
import { seriesPath } from "./projectScope";

export type ReviewIssue = {
  character_ids: string[];
  /** Location plates a style note names; character notes leave this empty. */
  location_ids?: string[];
  concern: string;
  evidence: string;
  suggestion: string;
};

export type CastReview = {
  status: "missing" | "stale" | "current";
  issues: ReviewIssue[];
  /** Notes the author marked fine for the current sheets. */
  dismissed: number;
  /** A Character Check model call is in flight. */
  reviewing: boolean;
  characters?: number;
};

export const castReviewKey = (projectId: string) => ["cast-review", projectId];

/** The Character Check for the current sheets; polls faster while it runs. */
export function useCastReview(projectId: string, active = false) {
  return useQuery({
    queryKey: castReviewKey(projectId),
    queryFn: () => apiFetch<CastReview>(`${seriesPath(projectId)}/cast/review`),
    refetchInterval: (query) => (active || query.state.data?.reviewing ? 3000 : 10000),
  });
}

/**
 * Characters whose main sheet is being redrawn: submitted, queued or running.
 * Their Character Check notes are out of date until the redraw's re-check.
 */
export function useRedrawingCharacters(projectId: string): Set<string> {
  const { data } = useGenerationJobs(projectId, [], true);
  const submitting = useMutationState({
    filters: { status: "pending", predicate: (mutation) =>
      ["character-regen", "reference-instruction"].includes(String(mutation.options.mutationKey?.[0])) },
    select: (mutation) => mutation.state.variables as { project?: string; charId?: string; stateId?: string } | undefined,
  });
  const ids = new Set<string>();
  for (const vars of submitting) {
    if (vars?.project === projectId && vars.charId && !vars.stateId) ids.add(vars.charId);
  }
  for (const job of data?.jobs ?? []) {
    const charId = job.payload.char_id;
    if ((job.status === "queued" || job.status === "running") && typeof charId === "string" && !charId.includes(":")) ids.add(charId);
  }
  return ids;
}
