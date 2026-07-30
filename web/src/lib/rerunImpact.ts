import { STAGE_ORDER, type StageName } from "../types/api";

export type RerunStageKey = StageName;

export interface RerunImpact {
  downstream: StageName[];
}

export const RERUN_IMPACT = Object.fromEntries(
  STAGE_ORDER.map((stage, index) => [
    stage,
    { downstream: STAGE_ORDER.slice(index + 1) },
  ]),
) as Record<RerunStageKey, RerunImpact>;
