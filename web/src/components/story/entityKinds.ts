import { msg } from "../../locales/messages";
import type { EntityKind } from "../../api/storyBible";

/** Labels for each kind of Story Bible entry, translated where they are shown. */
export const KIND_LABELS: Record<EntityKind, { one: string; add: string }> = {
  characters: { one: msg("character"), add: msg("Add a character") },
  locations: { one: msg("place"), add: msg("Add a place") },
  props: { one: msg("prop"), add: msg("Add a prop") },
};
