import type { StageStatus } from "../types/api";

export type CastCheckpointAction = "approve" | "resume" | "continue" | "wait";

/** The blocker left when every reference exists but corrections made the
 * character comparison out of date. Resuming mostly re-runs that review. */
export const CAST_REVIEW_BLOCKER =
  "Compare the current character references before approving Cast. Resume Cast to run its visual review.";

export function isCastReviewBlocker(approvalBlocker?: string | null): boolean {
  return approvalBlocker === CAST_REVIEW_BLOCKER;
}

/**
 * Keep the Cast checkpoint action exhaustive so failed or incomplete work can
 * never fall through to the Pages navigation path.
 */
export function getCastCheckpointAction(status: StageStatus, approvalBlocker?: string | null): CastCheckpointAction {
  if (approvalBlocker && (status === "awaiting_review" || status === "complete")) return "resume";
  if (status === "awaiting_review") return "approve";
  if (status === "failed") return "resume";
  if (status === "complete") return "continue";
  return "wait";
}
