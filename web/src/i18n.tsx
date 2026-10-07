/* eslint-disable react-refresh/only-export-components */
import { createContext, startTransition, Suspense, use, useContext, useDeferredValue, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { StageName, StageStatus } from "./types/api";
import { createTranslator, loadCatalog, loadedCatalog, type Translator } from "./locales/messages";
import { languageCode, type LanguageCode } from "./locales/languages";
import { LoadingBlock } from "./components/ui/StateBlock";
export { LANGUAGES, type LanguageCode } from "./locales/languages";

const STORAGE_KEY = "canary.uiLanguage";
interface I18nValue {
  language: LanguageCode;
  setLanguage: (language: LanguageCode) => void;
  t: Translator;
  stageName: (stage: StageName) => string;
  statusName: (status: StageStatus) => string;
}
const I18nContext = createContext<I18nValue | null>(null);

export function readStoredLanguage(): LanguageCode {
  try {
    const stored = languageCode(globalThis.localStorage?.getItem(STORAGE_KEY));
    if (stored) return stored;
  } catch { /* Storage may be blocked; language selection still works in memory. */ }
  return globalThis.navigator?.languages?.map(languageCode).find(Boolean) ?? "en";
}

/** Start fetching a catalog on intent (hover/focus) so switching never waits. */
export function preloadLanguage(language: LanguageCode): Promise<unknown> {
  return loadCatalog(language).catch(() => {});
}

/**
 * `pageLanguage` pins a public page's language (its URL decides it, for
 * search engines); elsewhere the reader's stored preference applies. The
 * provider is never remounted: switching language keeps the current screen
 * until the next catalog is ready, rather than flashing a loading state.
 */
export function I18nProvider({ children, pageLanguage }: { children: ReactNode; pageLanguage?: LanguageCode }) {
  return <Suspense fallback={<LoadingBlock label="LOADING…" />}><LocalizedProvider pageLanguage={pageLanguage}>{children}</LocalizedProvider></Suspense>;
}

function LocalizedProvider({ children, pageLanguage }: { children: ReactNode; pageLanguage?: LanguageCode }) {
  const [preferred, setPreferred] = useState<LanguageCode>(readStoredLanguage);
  const language = useDeferredValue(pageLanguage ?? preferred);
  const catalog = language === "en" ? loadedCatalog("en")! : use(loadCatalog(language));
  useEffect(() => {
    try { globalThis.localStorage?.setItem(STORAGE_KEY, preferred); } catch { /* optional persistence */ }
  }, [preferred]);
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) startTransition(() => setPreferred(languageCode(event.newValue) ?? "en"));
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  const value = useMemo<I18nValue>(() => {
    const t = createTranslator(language, catalog);
    return { language, setLanguage: (next: LanguageCode) => startTransition(() => setPreferred(next)), t,
      stageName: (stage) => t(`stage.${stage}`),
      statusName: (status) => t(`status.${status}`),
    };
  }, [language, catalog]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider");
  return ctx;
}
