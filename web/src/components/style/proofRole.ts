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

/** `favoriteId` is the look the author picked on their Cold Open pages. */
export function proofRole(suggestion: StyleSuggestion, favoriteId?: string | null): string {
  if (isAuthorDirection(suggestion)) return "Yours";
  if (suggestion.origin === "cold_open") return suggestion.id === favoriteId ? "Your pick" : "First pages";
  return ROLE_LABELS[suggestion.role ?? ""] ?? "Direction";
}
