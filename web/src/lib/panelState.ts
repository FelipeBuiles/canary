import type { ImageStatus } from "../types/api";

export type PanelDisplayState =
  | "pending"
  | "queued"
  | "generating"
  | "generated"
  | "regenerated"
  | "flagged"
  | "failed";

export interface PanelStateInputs {
  /** True when the backend reports this panel is currently being generated. */
  inFlight?: boolean;
  /** True when this panel is part of an active run's target set but not yet started. */
  queuedInRun?: boolean;
  /** Active regen status for this specific panel (re-roll / fix flow). */
  regenMode?: "queued" | "running" | null;
  /** True when the explicit Retry-Failed run is targeting this panel. */
  isRetryFailedRunning?: boolean;
}

/**
 * Review-by-exception: generated panels are good by default — there is no
 * "accepted" display state. The user's action is flagging a panel for
 * re-work; activity states (generating/queued) win over the flag because a
 * regen in progress is already addressing it.
 */
export function getPanelDisplayState(
  img: Pick<ImageStatus, "status" | "flagged" | "version_count">,
  inputs: PanelStateInputs = {},
): PanelDisplayState {
  const {
    inFlight = false,
    queuedInRun = false,
    regenMode = null,
    isRetryFailedRunning = false,
  } = inputs;

  if (regenMode === "running" || inFlight) return "generating";
  if (isRetryFailedRunning && img.status === "failed") return "generating";
  if (regenMode === "queued") return "queued";
  if (img.status === "failed") return "failed";
  if (img.status === "done") {
    if (img.flagged) return "flagged";
    return (img.version_count ?? 0) > 1 ? "regenerated" : "generated";
  }
  if (queuedInRun) return "queued";
  return "pending";
}

export type PanelFilterBucket = "all" | "flagged" | "generated" | "pending" | "failed";

export function getPanelFilterBucket(
  state: PanelDisplayState,
): "flagged" | "generated" | "pending" | "failed" {
  if (state === "flagged") return "flagged";
  if (state === "generated" || state === "regenerated") return "generated";
  if (state === "failed") return "failed";
  return "pending";
}
