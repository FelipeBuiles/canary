import type { Character, StoryBible, StorySequence } from "../../types/api";
import { narrativeScenes } from "./storyPhrases";

const STOP = new Set(["the", "and", "with", "from", "that", "this", "into", "when", "then", "their", "they", "them", "while", "after", "before", "over", "onto", "upon", "his", "her", "him", "she", "for", "was", "has", "had", "have", "are", "but", "not", "who", "what", "which", "where", "there"]);

function words(text: string): Set<string> {
  return new Set(text.toLowerCase().match(/\p{L}[\p{L}'’-]{2,}/gu)?.filter((word) => !STOP.has(word)) ?? []);
}

export interface EventGroup {
  /** Null when the story has no sequences to suggest from. */
  sequence: StorySequence | null;
  /** Indexes into the list that was grouped, in order. */
  items: number[];
}

/**
 * Suggests which sequence each essential event belongs to. The brief does not
 * record it, so each event goes to the sequence of the scene whose title and
 * summary share the most words with it, never earlier than the event before.
 */
export function groupEventsBySequence(events: string[], story: StoryBible): EventGroup[] {
  const scenes = narrativeScenes(story.scenes);
  const sceneIds = new Set(scenes.map((scene) => scene.id));
  const sequences = (story.sequences ?? []).filter((sequence) => sequence.scenes.some((id) => sceneIds.has(id)));
  if (sequences.length < 2) return [{ sequence: sequences[0] ?? null, items: events.map((_, index) => index) }];
  const sequenceOf = new Map<string, number>();
  sequences.forEach((sequence, index) => sequence.scenes.forEach((id) => sequenceOf.set(id, index)));
  const sceneWords = scenes.map((scene) => ({ id: scene.id, words: words(`${scene.title ?? ""} ${scene.summary ?? ""}`) }));
  const groups: EventGroup[] = sequences.map((sequence) => ({ sequence, items: [] }));
  let floor = 0;
  events.forEach((event, index) => {
    const eventWords = words(event);
    let best = -1;
    let bestScore = 0;
    for (const scene of sceneWords) {
      let score = 0;
      for (const word of eventWords) if (scene.words.has(word)) score += 1;
      const at = sequenceOf.get(scene.id);
      if (at !== undefined && score > bestScore) { bestScore = score; best = at; }
    }
    floor = Math.max(floor, best);
    groups[floor].items.push(index);
  });
  return groups;
}

export interface TurnGroup {
  /** Null for turns that name no cast character. */
  character: Character | null;
  items: number[];
}

/** The first mention that isn't possessive: "after Herbert's death" names Herbert in passing. */
function subjectMention(text: string, name: string): number {
  for (let at = text.indexOf(name); at >= 0; at = text.indexOf(name, at + 1)) {
    if (!/^['’]s\b/.test(text.slice(at + name.length))) return at;
  }
  return -1;
}

/** Groups character turns under the cast member each one names first. */
export function groupTurnsByCharacter(turns: string[], characters: Character[]): TurnGroup[] {
  const groups = new Map<string | null, TurnGroup>();
  turns.forEach((turn, index) => {
    const lower = turn.toLowerCase();
    let found: Character | null = null;
    let at = Infinity;
    for (const character of characters) {
      for (const name of [character.name, ...(character.aliases ?? [])]) {
        const position = name.trim() ? subjectMention(lower, name.toLowerCase()) : -1;
        if (position >= 0 && (position < at || (position === at && found && name.length > found.name.length))) {
          at = position;
          found = character;
        }
      }
    }
    const key = found?.id ?? null;
    if (!groups.has(key)) groups.set(key, { character: found, items: [] });
    groups.get(key)!.items.push(index);
  });
  // Named characters first, in order of their first turn; unnamed turns last.
  return [...groups.values()].sort((a, b) => Number(a.character === null) - Number(b.character === null));
}

const SCRIPTS = ["Latin", "Cyrillic", "Greek", "Arabic", "Hebrew", "Devanagari", "Bengali", "Han", "Hiragana", "Katakana", "Hangul", "Thai"] as const;
const SCRIPT_RE = Object.fromEntries(SCRIPTS.map((script) => [script, new RegExp(`\\p{Script=${script}}`, "gu")])) as Record<string, RegExp>;
const SCRIPT_TEST = Object.fromEntries(SCRIPTS.map((script) => [script, new RegExp(`\\p{Script=${script}}`, "u")])) as Record<string, RegExp>;
const EAST_ASIAN: readonly string[] = ["Han", "Hiragana", "Katakana", "Hangul"];

/** The writing system most of the brief is in. */
export function dominantScript(texts: string[]): string | null {
  const joined = texts.join(" ");
  let best: string | null = null;
  let most = 0;
  for (const script of SCRIPTS) {
    const count = joined.match(SCRIPT_RE[script])?.length ?? 0;
    if (count > most) { most = count; best = script; }
  }
  return best;
}

/**
 * Words written in a different script from the rest of the brief, such as a
 * stray "দ্বিতীয়" inside English events: usually a generation glitch.
 */
export function strayWords(text: string, script: string | null): string[] {
  if (!script) return [];
  // Japanese and Korean mix these scripts in ordinary text.
  const own: readonly string[] = EAST_ASIAN.includes(script) ? EAST_ASIAN : [script];
  return (text.match(/\p{L}[\p{L}\p{M}]*/gu) ?? []).filter((word) => {
    if (own.some((script) => SCRIPT_TEST[script].test(word))) return false;
    return SCRIPTS.some((other) => SCRIPT_TEST[other].test(word));
  });
}
