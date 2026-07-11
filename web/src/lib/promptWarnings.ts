import type { ImagePrompt, PromptWarning } from "../types/api";

const DIALOGUE_PATTERN = /\b(said|asked|replied|shouted|whispered|cried|muttered)\b.{0,20}[""“”]/i;
const QUOTE_CHARS = /["“”]/;

export function detectPromptWarnings(prompt: ImagePrompt): PromptWarning[] {
  const warnings: PromptWarning[] = [];
  const { scene_id, panel_number } = prompt;

  function warn(
    code: PromptWarning["code"],
    label: string,
    detail: string,
  ) {
    warnings.push({ code, label, detail, scene_id, panel_number });
  }

  // thin_composition
  const comp = prompt.composition ?? "";
  if (comp.trim().length < 20) {
    warn(
      "thin_composition",
      "Thin composition",
      "The composition description is very short. Consider expanding it.",
    );
  }

  // thin_setting
  const setting = prompt.setting ?? "";
  if (setting.trim().length < 15) {
    warn(
      "thin_setting",
      "Thin setting",
      "The setting description is very short. The background may be vague.",
    );
  }

  // text_in_prompt
  const fullPromptHasQuotes = QUOTE_CHARS.test(prompt.full_prompt);
  const compositionHasDialogue = DIALOGUE_PATTERN.test(comp);
  const settingHasDialogue = DIALOGUE_PATTERN.test(setting);
  if (fullPromptHasQuotes || compositionHasDialogue || settingHasDialogue) {
    warn(
      "text_in_prompt",
      "Dialogue text in prompt",
      "Dialogue or speech text was found in the image prompt. This often causes unwanted text to appear in the generated image.",
    );
  }

  // missing_style
  if (!prompt.style) {
    warn(
      "missing_style",
      "No style or reference",
      "Neither a style template nor a reference image is attached. Generated art direction will vary.",
    );
  }

  // inconsistent_dimensions
  const missingDimensions =
    !prompt.width ||
    !prompt.height ||
    prompt.width === 0 ||
    prompt.height === 0 ||
    !prompt.steps ||
    prompt.steps === 0;
  if (missingDimensions) {
    warn(
      "inconsistent_dimensions",
      "Missing generation parameters",
      "Width, height, or step count is unset. Generation may fail or use defaults.",
    );
  }

  return warnings;
}

export function detectAllWarnings(prompts: ImagePrompt[]): PromptWarning[] {
  return prompts.flatMap((p) => detectPromptWarnings(p));
}
