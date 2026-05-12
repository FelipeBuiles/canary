import type { ProjectStatus, StageName } from "../types/api";

export type UiStageKey =
  | "extract"
  | "style"
  | "cast"
  | "adapt"
  | "shot-plan"
  | "direct"
  | "draw"
  | "compose";

export type UiStage =
  | { key: "shot-plan"; route: "shot-plan"; label: string; backendStages: ["plan", "storyboard"] }
  | {
      key: Exclude<UiStageKey, "shot-plan">;
      route: string;
      label: string;
      backendStages: [StageName];
    };

export const UI_STAGES: UiStage[] = [
  { key: "extract", route: "extract", label: "Extract", backendStages: ["extract"] },
  { key: "style", route: "styles", label: "Look & Feel", backendStages: ["style"] },
  { key: "cast", route: "cast", label: "Cast & Places", backendStages: ["cast"] },
  { key: "adapt", route: "adapt", label: "Script", backendStages: ["adapt"] },
  { key: "shot-plan", route: "shot-plan", label: "Shot Plan", backendStages: ["plan", "storyboard"] },
  { key: "direct", route: "direct", label: "Prompt Review", backendStages: ["direct"] },
  { key: "draw", route: "draw", label: "Generate Panels", backendStages: ["draw"] },
  { key: "compose", route: "compose", label: "Letter & Compose", backendStages: ["compose"] },
];

export const BACKEND_STAGE_TO_UI_ROUTE: Record<StageName, string> = {
  extract: "extract",
  style: "styles",
  cast: "cast",
  adapt: "adapt",
  plan: "shot-plan",
  storyboard: "shot-plan",
  direct: "direct",
  draw: "draw",
  compose: "compose",
};

export function getBackendStageUiLabel(stage: StageName): string {
  const route = BACKEND_STAGE_TO_UI_ROUTE[stage];
  return UI_STAGES.find((uiStage) => uiStage.route === route)?.label ?? stage;
}

export function getUiCompletedCount(status: ProjectStatus | undefined): number {
  if (!status) return 0;
  return UI_STAGES.filter((stage) => {
    if (stage.key === "shot-plan") {
      return status.stages.plan?.status === "complete" && status.stages.storyboard?.status === "complete";
    }
    return status.stages[stage.backendStages[0]]?.status === "complete";
  }).length;
}

