export const STAGE_LABELS: Record<string, string> = {
  extract:    "Story",
  brief:      "Adaptation Brief",
  style:      "Art Style",
  cast:       "Characters & Places",
  adapt:      "Book Adaptation",
  plan:       "Page Plan",
  draw:       "Complete Pages",
  finish:     "Book & Export",
};

export function stageLabel(stage: string | null): string {
  if (!stage) return "System";
  return STAGE_LABELS[stage] ?? stage.charAt(0).toUpperCase() + stage.slice(1);
}
