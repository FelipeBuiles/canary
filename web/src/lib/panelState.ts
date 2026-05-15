import type { ImageStatus } from "../types/api";

export type PanelDisplayState =
  | "pending"
  | "queued"
  | "generating"
  | "generated"
  | "regenerated"
  | "accepted"
  | "failed";

export interface PanelStateInputs {
  /** True when the backend reports this panel is currently being generated. */
  inFlight?: boolean;
  /** True when this panel is part of an active run's target set but not yet started. */
  queuedInRun?: boolean;
  /** Active regen status for this specific panel (Quick Re-Do flow). */
  regenMode?: "queued" | "running" | null;
  /** True when the explicit Retry-Failed run is targeting this panel. */
  isRetryFailedRunning?: boolean;
}

export function getPanelDisplayState(
  img: Pick<ImageStatus, "status" | "accepted" | "version_count">,
  inputs: PanelStateInputs = {},
): PanelDisplayState {
  const {
    inFlight = false,
    queuedInRun = false,
    regenMode = null,
    isRetryFailedRunning = false,
  } = inputs;

  if (img.accepted) return "accepted";
  if (regenMode === "running" || inFlight) return "generating";
  if (isRetryFailedRunning && img.status === "failed") return "generating";
  if (regenMode === "queued") return "queued";
  if (img.status === "failed") return "failed";
  if (img.status === "done") {
    return (img.version_count ?? 0) > 1 ? "regenerated" : "generated";
  }
  if (queuedInRun) return "queued";
  return "pending";
}

export type PanelFilterBucket = "all" | "generated" | "pending" | "failed";

export function getPanelFilterBucket(state: PanelDisplayState): "generated" | "pending" | "failed" {
  if (state === "generated" || state === "regenerated" || state === "accepted") return "generated";
  if (state === "failed") return "failed";
  return "pending";
}
