import type { StageName } from "../types/api";

export type RerunStageKey = StageName | "style";

export interface RerunImpact {
  downstream: StageName[];
  credits: string;
  creditsAreEstimated: boolean;
}

// Backend computes the actual hold dynamically from project inputs and config.
const DYNAMIC_HOLD = "Calculated before run";

export const RERUN_IMPACT: Record<RerunStageKey, RerunImpact> = {
  extract: {
    downstream: ["cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
  style: {
    downstream: ["cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
  cast: {
    downstream: ["adapt", "plan", "storyboard", "direct", "draw", "compose"],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
  adapt: {
    downstream: ["plan", "storyboard", "direct", "draw", "compose"],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
  plan: {
    downstream: ["storyboard", "direct", "draw", "compose"],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
  storyboard: {
    downstream: ["direct", "draw", "compose"],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
  direct: {
    downstream: ["draw", "compose"],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
  draw: {
    downstream: ["compose"],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
  compose: {
    downstream: [],
    credits: DYNAMIC_HOLD,
    creditsAreEstimated: true,
  },
};
