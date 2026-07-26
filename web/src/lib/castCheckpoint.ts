import type { StageStatus } from "../types/api";

export type CastCheckpointAction = "approve" | "resume" | "continue" | "wait";

/**
 * Keep the Cast checkpoint action exhaustive so failed or incomplete work can
 * never fall through to the Pages navigation path.
 */
export function getCastCheckpointAction(status: StageStatus): CastCheckpointAction {
  if (status === "awaiting_review") return "approve";
  if (status === "failed") return "resume";
  if (status === "complete") return "continue";
  return "wait";
}
