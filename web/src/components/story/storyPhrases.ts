import type { Scene } from "../../types/api";

/** Extract writes beats and affects as free-form snake_case or lowercase phrases. */
export function readablePhrase(value: string | null | undefined): string {
  const text = (value ?? "").replaceAll("_", " ").trim();
  return text ? `${text.charAt(0).toLocaleUpperCase()}${text.slice(1)}` : "";
}

export function known(value: string | null | undefined): value is string {
  return !!value && value.trim().toLocaleLowerCase() !== "unknown";
}

/** Non-story source ranges stay in the citation index but aren't story action to display or adapt. */
export function narrativeScenes(scenes: Scene[]): Scene[] {
  return scenes.filter((scene) => scene.scene_type !== "non_narrative");
}

/** Two-digit reading-order numbers for this part's story scenes. */
export function sceneNumbers(scenes: Scene[]): Map<string, string> {
  return new Map(narrativeScenes(scenes).map((scene, index) => [scene.id, String(index + 1).padStart(2, "0")]));
}
