import type { StageName } from "../types/api";

export type RerunStageKey = StageName | "style";

export interface RerunImpact {
  downstream: StageName[];
  cost: string;
  costIsPlaceholder: boolean;
}

// Placeholder cost estimates copied from the redesign prototype. Replace with
// backend-derived stage history or project cost estimates when available.
export const RERUN_IMPACT: Record<RerunStageKey, RerunImpact> = {
  extract: {
    downstream: ["cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"],
    cost: "~$4.10",
    costIsPlaceholder: true,
  },
  style: {
    downstream: ["cast", "adapt", "plan", "storyboard", "direct", "draw", "compose"],
    cost: "~$0.30",
    costIsPlaceholder: true,
  },
  cast: {
    downstream: ["adapt", "plan", "storyboard", "direct", "draw", "compose"],
    cost: "~$0.80",
    costIsPlaceholder: true,
  },
  adapt: {
    downstream: ["plan", "storyboard", "direct", "draw", "compose"],
    cost: "~$0.25",
    costIsPlaceholder: true,
  },
  plan: {
    downstream: ["storyboard", "direct", "draw", "compose"],
    cost: "~$0.05",
    costIsPlaceholder: true,
  },
  storyboard: {
    downstream: ["direct", "draw", "compose"],
    cost: "~$0.15",
    costIsPlaceholder: true,
  },
  direct: {
    downstream: ["draw", "compose"],
    cost: "~$0.10",
    costIsPlaceholder: true,
  },
  draw: {
    downstream: ["compose"],
    cost: "~$3.20",
    costIsPlaceholder: true,
  },
  compose: {
    downstream: [],
    cost: "~$0.05",
    costIsPlaceholder: true,
  },
};
