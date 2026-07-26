import type { ProjectStatus, StageName } from "../types/api";

export interface UiStage {
  key: "story" | "look" | "pages" | "book";
  route: "story" | "styles" | "pages" | "book";
  label: string;
  backendStages: StageName[];
}

export const UI_STAGES: UiStage[] = [
  { key: "story", route: "story", label: "Story", backendStages: ["extract", "brief"] },
  { key: "look", route: "styles", label: "Look", backendStages: ["style", "cast"] },
  { key: "pages", route: "pages", label: "Pages", backendStages: ["adapt", "plan", "draw"] },
  { key: "book", route: "book", label: "Book", backendStages: ["finish"] },
];

export const BACKEND_STAGE_TO_UI_ROUTE: Record<StageName, string> = {
  extract: "story",
  brief: "story",
  style: "styles",
  cast: "styles",
  adapt: "pages",
  plan: "pages",
  draw: "pages",
  finish: "book",
};

export function getBackendStageUiLabel(stage: StageName): string {
  const route = BACKEND_STAGE_TO_UI_ROUTE[stage];
  return UI_STAGES.find((uiStage) => uiStage.route === route)?.label ?? stage;
}

export function getUiCompletedCount(status: ProjectStatus | undefined): number {
  if (!status) return 0;
  return UI_STAGES.filter((station) =>
    station.backendStages.every((stage) => status.stages[stage]?.status === "complete"),
  ).length;
}
