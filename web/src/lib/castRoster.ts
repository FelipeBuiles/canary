import type { StoryBible } from "../types/api";

/** Source identities stay available while Cast selects a smaller recurring roster. */
export function castCharacters(bible: StoryBible) {
  if (bible.cast_character_ids === undefined) return bible.characters;
  const selected = new Set(bible.cast_character_ids);
  return bible.characters.filter((character) => selected.has(character.id));
}
