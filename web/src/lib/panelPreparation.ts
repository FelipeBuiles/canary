import type { ProjectStatus, StageInfo, StageName } from "../types/api";

export const PANEL_PREPARATION_STAGES = [
  "adapt",
  "plan",
  "storyboard",
  "direct",
] as const satisfies readonly StageName[];

export type PanelPreparationStage = (typeof PANEL_PREPARATION_STAGES)[number];
export type PanelPreparationStepState = "done" | "running" | "waiting" | "failed";

export interface PanelPreparationStep {
  stage: PanelPreparationStage;
  state: PanelPreparationStepState;
  itemsDone: number;
  itemsTotal: number;
}

export interface PanelPreparationState {
  steps: PanelPreparationStep[];
  completedCount: number;
  isReady: boolean;
  failedStage: PanelPreparationStage | null;
  runningStage: PanelPreparationStage | null;
}

function hasFailed(info: StageInfo | undefined): boolean {
  if (!info) return false;
  return info.status === "failed"
    || (info.status === "complete" && info.items_failed.length > 0);
}

function hasProgressed(info: StageInfo | undefined): boolean {
  return Boolean(info && info.status !== "pending");
}

/**
 * Build the stable, user-facing state for the automatic panel-preparation
 * chain. Each stage owns its own totals, so the chain deliberately exposes
 * completed steps instead of manufacturing one aggregate percentage.
 */
export function getPanelPreparationState(
  status: ProjectStatus | undefined,
): PanelPreparationState {
  const steps = PANEL_PREPARATION_STAGES.map((stage, index): PanelPreparationStep => {
    const info = status?.stages[stage];
    const laterStageHasProgressed = PANEL_PREPARATION_STAGES
      .slice(index + 1)
      .some((laterStage) => hasProgressed(status?.stages[laterStage]));

    let state: PanelPreparationStepState = "waiting";
    if (laterStageHasProgressed) state = "done";
    else if (hasFailed(info)) state = "failed";
    else if (info?.status === "running") state = "running";
    else if (info?.status === "complete") state = "done";

    return {
      stage,
      state,
      itemsDone: info?.items_done ?? 0,
      itemsTotal: info?.items_total ?? 0,
    };
  });

  return {
    steps,
    completedCount: steps.filter((step) => step.state === "done").length,
    isReady: steps.every((step) => step.state === "done"),
    failedStage: steps.find((step) => step.state === "failed")?.stage ?? null,
    runningStage: steps.find((step) => step.state === "running")?.stage ?? null,
  };
}
