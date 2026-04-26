import { useStoryBible } from "../api/queries";

/**
 * Returns a resolver that maps char_NNN / loc_NNN IDs to display names from
 * the story bible. Falls back to the raw ID if the bible hasn't loaded yet.
 */
export function useCharacterName(project: string | undefined) {
  const { data: bible } = useStoryBible(project);

  return (id: string): string => {
    if (!id) return id;
    const char = bible?.characters.find((c) => c.id === id);
    if (char) return char.name;
    const loc = bible?.locations.find((l) => l.id === id);
    if (loc) return loc.name;
    return id;
  };
}
