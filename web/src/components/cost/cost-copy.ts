import type { CostConfidence } from "../../types/api";

export const CONFIDENCE_LABELS: Record<CostConfidence, string> = {
  low_variance: "Low variance",
  usually_within_estimate: "Usually within estimate",
  variable: "Variable",
};

export const RESERVATION_HELPER =
  "Reserved credits are held before the action starts. Unused reserved credits are released after the action finishes, resets, or fails.";

export const ESTIMATE_ONLY_HELPER =
  "This action is charged from reported model usage after it finishes. No separate credit hold is made before it starts.";

export const ZERO_COST_COPY = "No credit hold needed for this step.";
