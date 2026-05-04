export const STAGE_LABELS: Record<string, string> = {
  extract:    "Extract Story",
  style:      "Look & Feel",
  cast:       "Cast & Locations",
  adapt:      "Adapt Screenplay",
  plan:       "Shot Plan",
  storyboard: "Shot Plan",
  direct:     "Prompt Review",
  draw:       "Generate Panels",
  compose:    "Letter & Compose",
};

export function stageLabel(stage: string | null): string {
  if (!stage) return "System";
  return STAGE_LABELS[stage] ?? stage.charAt(0).toUpperCase() + stage.slice(1);
}
