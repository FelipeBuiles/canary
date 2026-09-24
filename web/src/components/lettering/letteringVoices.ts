import { ROLE_DEFAULTS, type RoleName, type RoleStyle } from "@lettering-engine";
import voices from "@lettering-voices";

/** A voice is a letterer's convention for HOW words are said: a shout, a
 * radio call, a flashback caption. Voices restyle the book's own role style,
 * so a book's fonts and colors carry through unless the voice is about them. */
export interface LetteringVoice {
  id: string;
  label: string;
  hint: string;
  patch: Partial<RoleStyle>;
}

// Effects are cleared before each voice so switching voices never stacks them.
// Case and tail width belong to the book's lettering and are kept.
const CLEAR_EFFECTS = Object.fromEntries(Object.entries(ROLE_DEFAULTS).filter(([key]) => key !== "text_case" && key !== "tail_width")) as Partial<RoleStyle>;

// One catalogue for the editor and for page seeding (lettering/voices.json).
export const VOICES: Record<RoleName, LetteringVoice[]> = { speech: voices.speech, thought: voices.thought, caption: voices.caption, sfx: voices.sfx } as Record<RoleName, LetteringVoice[]>;

export function voiceStyle(base: RoleStyle, voice: LetteringVoice): RoleStyle {
  return { ...base, ...CLEAR_EFFECTS, ...voice.patch };
}

const signature = (style: RoleStyle) => JSON.stringify(Object.keys(style).sort().map(key => [key, style[key as keyof RoleStyle]]));
export function sameStyle(a: RoleStyle, b: RoleStyle) {
  return signature(a) === signature(b);
}

/** Short specimen copy for previews: the author's own words when there are some. */
export function sampleWords(text: string | undefined, role: RoleName) {
  const fallback = { speech: "Hey, you!", thought: "Hmm…", caption: "Later that night", sfx: "BOOM!" }[role];
  const words = (text ?? "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  if (!words.length) return fallback;
  const limit = role === "sfx" ? 1 : 3;
  return words.slice(0, limit).join(" ") + (words.length > limit ? "…" : "");
}
