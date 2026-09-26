/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { StageName, StageStatus } from "./types/api";
import { createTranslator, type Translator } from "./locales/messages";
import { languageCode, type LanguageCode } from "./locales/languages";
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

function readStoredLanguage(): LanguageCode {
  try {
    const stored = languageCode(globalThis.localStorage?.getItem(STORAGE_KEY));
    if (stored) return stored;
  } catch { /* Storage may be blocked; language selection still works in memory. */ }
  return globalThis.navigator?.languages?.map(languageCode).find(Boolean) ?? "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<LanguageCode>(readStoredLanguage);
  useEffect(() => {
    try { globalThis.localStorage?.setItem(STORAGE_KEY, language); } catch { /* optional persistence */ }
    document.documentElement.lang = language;
  }, [language]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) setLanguage(languageCode(event.newValue) ?? "en");
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  const value = useMemo<I18nValue>(() => {
    const t = createTranslator(language);
    return { language, setLanguage, t,
      stageName: (stage) => t(`stage.${stage}`),
      statusName: (status) => t(`status.${status}`),
    };
  }, [language]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider");
  return ctx;
}
