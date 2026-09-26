import { IntlMessageFormat } from "intl-messageformat";
import en from "./en.json";
import es from "./es.json";
import fr from "./fr.json";
import type { LanguageCode } from "./languages";

export type MessageKey = keyof typeof en;
/** Mark deferred UI labels for extraction without translating at module load. */
export const msg = (message: MessageKey) => message;
export type MessageValues = Record<string, string | number | Date>;
export type Translator = (message: string, values?: MessageValues) => string;
const catalogs: Record<LanguageCode, Record<string, string>> = { en, es, fr };

/** One formatter/cache per provider locale, with no mutable global language. */
export function createTranslator(locale: LanguageCode): Translator {
  const cache = new Map<string, IntlMessageFormat>();
  return (message, values) => {
    // Server/user text is data, not ICU syntax. Only catalog messages are parsed.
    if (!Object.hasOwn(en, message)) return message;
    let formatter = cache.get(message);
    if (!formatter) {
      formatter = new IntlMessageFormat(catalogs[locale][message] ?? catalogs.en[message], locale, undefined, { ignoreTag: true });
      cache.set(message, formatter);
    }
    return String(formatter.format(values));
  };
}
