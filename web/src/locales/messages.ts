import { IntlMessageFormat } from "intl-messageformat";
import en from "./en.json";
import type { LanguageCode } from "./languages";

export type MessageKey = keyof typeof en;
/** Mark deferred UI labels for extraction without translating at module load. */
export const msg = (message: MessageKey) => message;
export type MessageValues = Record<string, string | number | Date>;
export type Translator = (message: string, values?: MessageValues) => string;
type Catalog = Record<string, string>;
const englishCatalog: Catalog = en;
const catalogs: Partial<Record<LanguageCode, Catalog>> = { en };
const loads = new Map<LanguageCode, Promise<Catalog>>();
export const loadedCatalog = (locale: LanguageCode) => catalogs[locale];

/** Keep unused languages out of the startup bundle; cache each requested catalog. */
export function loadCatalog(locale: LanguageCode): Promise<Catalog> {
  let load = loads.get(locale);
  if (!load) {
    load = (locale === "en" ? Promise.resolve({ default: en })
      : locale === "es" ? import("./es.json") : import("./fr.json"))
      .then(({ default: catalog }) => {
        catalogs[locale] = catalog;
        // React's use() reads a settled thenable synchronously, so a
        // preloaded catalog never shows a Suspense fallback.
        Object.assign(load!, { status: "fulfilled", value: catalog });
        return catalog;
      }, (error: unknown) => {
        // A failed chunk may load after a retry (e.g. after a deploy reload).
        loads.delete(locale);
        throw error;
      });
    loads.set(locale, load);
  }
  return load;
}

/** One formatter/cache per provider locale, with no mutable global language. */
export function createTranslator(locale: LanguageCode, catalog: Catalog = catalogs[locale] ?? englishCatalog): Translator {
  const cache = new Map<string, IntlMessageFormat>();
  return (message, values) => {
    // Server/user text is data, not ICU syntax. Only catalog messages are parsed.
    if (!Object.hasOwn(en, message)) return message;
    let formatter = cache.get(message);
    if (!formatter) {
      formatter = new IntlMessageFormat(catalog[message] ?? englishCatalog[message], locale, undefined, { ignoreTag: true });
      cache.set(message, formatter);
    }
    return String(formatter.format(values));
  };
}
