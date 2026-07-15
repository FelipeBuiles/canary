export const STAGE_LABELS: Record<string, string> = {
  extract:    "Story",
  style:      "Art Style",
  cast:       "Characters & Places",
  adapt:      "Story Draft",
  plan:       "Panel Plan",
  storyboard: "Panel Breakdown",
  direct:     "Image Instructions",
  draw:       "Draw Panels",
  compose:    "Pages & Export",
};

export function stageLabel(stage: string | null): string {
  if (!stage) return "System";
  return STAGE_LABELS[stage] ?? stage.charAt(0).toUpperCase() + stage.slice(1);
}
