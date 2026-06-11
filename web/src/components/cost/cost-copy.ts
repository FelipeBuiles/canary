import type { CostConfidence } from "../../types/api";

export const CONFIDENCE_LABELS: Record<CostConfidence, string> = {
  low_variance: "Low variance",
  usually_within_estimate: "Usually within estimate",
  variable: "Variable",
};

export const RESERVATION_HELPER =
  "You only pay for what's used — any unused part of the hold is released when the action finishes.";

export const ESTIMATE_ONLY_HELPER =
  "Charged from actual usage after it finishes — nothing is held up front.";

export const ZERO_COST_COPY = "This step is free.";
