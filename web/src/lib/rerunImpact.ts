import type { StageName } from "../types/api";

export type RerunStageKey = StageName | "style";

export interface RerunImpact {
  downstream: StageName[];
}

export const RERUN_IMPACT: Record<RerunStageKey, RerunImpact> = {
  extract: { downstream: ["cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"] },
  style: { downstream: ["cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"] },
  cast: { downstream: ["adapt", "plan", "storyboard", "direct", "draw", "compose"] },
  adapt: { downstream: ["plan", "storyboard", "direct", "draw", "compose"] },
  plan: { downstream: ["storyboard", "direct", "draw", "compose"] },
  storyboard: { downstream: ["direct", "draw", "compose"] },
  direct: { downstream: ["draw", "compose"] },
  draw: { downstream: ["compose"] },
  compose: { downstream: [] },
};
