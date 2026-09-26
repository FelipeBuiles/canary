/** Product-supported languages. UI preference and book language are independent. */
export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "fr", label: "Français" },
] as const;
export type LanguageCode = typeof LANGUAGES[number]["code"];
export type LetteringLocale = "source" | LanguageCode;

/** Match regional browser preferences using Intl's BCP 47 parser. */
export function languageCode(value: string | null | undefined): LanguageCode | undefined {
  if (!value) return undefined;
  try {
    const language = new Intl.Locale(value).language;
    return LANGUAGES.find(item => item.code === language)?.code;
  } catch { return undefined; }
}
