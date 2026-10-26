import { isAuthorDirection, type StyleSuggestion } from "../../api/styles";

const ROLE_LABELS: Record<string, string> = {
  story_fit_primary: "Best fit",
  story_fit_secondary: "Strong fit",
  story_fit_tertiary: "Strong fit",
  adjacent: "Adjacent",
  contrast: "Contrast",
  wildcard: "Wildcard",
  faithful: "Your direction",
};

export function proofRole(suggestion: StyleSuggestion): string {
  return isAuthorDirection(suggestion) ? "Yours" : ROLE_LABELS[suggestion.role ?? ""] ?? "Direction";
}
