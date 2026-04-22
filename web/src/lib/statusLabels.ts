import type { StageStatus } from "../types/api";
import type { IconName } from "../components/ui/Icon";

type Tone = "neutral" | "red" | "gold" | "sage" | "ink";

/**
 * Semantic label, tone, and icon for a pipeline stage status.
 * Centralized so Library cards, sidebar rows, and room headers agree.
 */
export interface StatusPresentation {
  /** Short label shown in UI (uppercase, ≤ 8 chars). i18n-keyed via `t()`. */
  label: string;
  /** Longer description shown in tooltips / secondary copy. */
  description: string;
  tone: Tone;
  icon: IconName;
}

export const STATUS_PRESENTATION: Record<StageStatus, StatusPresentation> = {
  pending: {
    label: "WAITING",
    description: "Waiting on an upstream stage.",
    tone: "neutral",
    icon: "circle",
  },
  running: {
    label: "RUNNING",
    description: "In progress.",
    tone: "gold",
    icon: "loader",
  },
  awaiting_review: {
    label: "REVIEW",
    description: "Ready for your review.",
    tone: "red",
    icon: "alert",
  },
  complete: {
    label: "COMPLETE",
    description: "Finished.",
    tone: "sage",
    icon: "check",
  },
  failed: {
    label: "FAILED",
    description: "Failed — inspect the logs.",
    tone: "red",
    icon: "alert",
  },
};

export function statusLabel(status: StageStatus): string {
  return STATUS_PRESENTATION[status].label;
}

export function statusTone(status: StageStatus): Tone {
  return STATUS_PRESENTATION[status].tone;
}
