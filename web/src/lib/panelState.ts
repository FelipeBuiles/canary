import type { ImageStatus } from "../types/api";

export type PanelDisplayState =
  | "pending"
  | "generating"
  | "generated"
  | "regenerated"
  | "accepted"
  | "failed"
  | "stale";

export function getPanelDisplayState(
  img: Pick<ImageStatus, "status" | "accepted" | "version_count">,
  regenMode: "queued" | "running" | null,
  isDrawRunning: boolean,
): PanelDisplayState {
  if (img.accepted) return "accepted";
  if (regenMode === "queued" || regenMode === "running") return "generating";
  if (img.status === "failed") return "failed";
  if (img.status === "stale") return "stale";
  if (isDrawRunning && img.status === "pending") return "generating";
  if (img.status === "done") {
    return (img.version_count ?? 0) > 1 ? "regenerated" : "generated";
  }
  return "pending";
}

export type PanelFilterBucket = "all" | "generated" | "pending" | "failed";

export function getPanelFilterBucket(state: PanelDisplayState): "generated" | "pending" | "failed" {
  if (state === "generated" || state === "regenerated" || state === "accepted") return "generated";
  if (state === "failed") return "failed";
  return "pending";
}
