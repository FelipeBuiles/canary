/** Unsent pasted manuscript text, kept in this browser until a project is created. */
const KEY = "canary.manuscriptDraft";
// Storage quotas are a few MB; a larger paste is not worth a failed write per keystroke.
const MAX_CHARACTERS = 1_000_000;

export function readManuscriptDraft(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function writeManuscriptDraft(text: string) {
  try {
    if (text.trim() && text.length <= MAX_CHARACTERS) localStorage.setItem(KEY, text);
    else localStorage.removeItem(KEY);
  } catch {
    // Private windows and full storage simply keep no draft.
  }
}

export function clearManuscriptDraft() {
  writeManuscriptDraft("");
}
