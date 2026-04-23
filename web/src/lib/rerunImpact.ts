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
    downstream: ["index", "screenplay", "layout-plan", "panels", "prompts", "generate", "assemble"],
    cost: "~$4.10",
    costIsPlaceholder: true,
  },
  style: {
    downstream: ["index", "screenplay", "layout-plan", "panels", "prompts", "generate", "assemble"],
    cost: "~$0.30",
    costIsPlaceholder: true,
  },
  index: {
    downstream: ["screenplay", "layout-plan", "panels", "prompts", "generate", "assemble"],
    cost: "~$0.80",
    costIsPlaceholder: true,
  },
  screenplay: {
    downstream: ["layout-plan", "panels", "prompts", "generate", "assemble"],
    cost: "~$0.25",
    costIsPlaceholder: true,
  },
  "layout-plan": {
    downstream: ["panels", "prompts", "generate", "assemble"],
    cost: "~$0.05",
    costIsPlaceholder: true,
  },
  panels: {
    downstream: ["prompts", "generate", "assemble"],
    cost: "~$0.15",
    costIsPlaceholder: true,
  },
  prompts: {
    downstream: ["generate", "assemble"],
    cost: "~$0.10",
    costIsPlaceholder: true,
  },
  generate: {
    downstream: ["assemble"],
    cost: "~$3.20",
    costIsPlaceholder: true,
  },
  assemble: {
    downstream: [],
    cost: "~$0.05",
    costIsPlaceholder: true,
  },
};
