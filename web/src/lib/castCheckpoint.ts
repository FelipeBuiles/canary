import type { StageStatus } from "../types/api";

export type CastCheckpointAction = "approve" | "resume" | "continue" | "wait";

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
