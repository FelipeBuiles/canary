import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider, useI18n } from "../i18n";
import { createTranslator } from "../locales/messages";
import { languageCode } from "../locales/languages";

function LanguageProbe() {
  const { language, setLanguage, t } = useI18n();
  return <><span data-testid="locale">{language}</span><span>{t("Save lettering")}</span>
    <button onClick={() => setLanguage("fr")}>French</button></>;
}
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("ICU localization", () => {
  it("formats values once without interpreting their content as a template", () => {
    const t = createTranslator("es");
    expect(t("Jump to page {number}", { number: 12 })).toBe("Ir a la página 12");
    expect(t("Check {email} for the confirmation link.", { email: "x{email}'<b>@mail.test" })).toContain("x{email}'<b>@mail.test");
    expect(t("Unknown user text {with} 'syntax' <b>" )).toBe("Unknown user text {with} 'syntax' <b>");
  });
  it("uses locale plural rules, repeated values, and localized numbers", () => {
    const t = createTranslator("fr");
    expect(t("{count, plural, one {Check {n}: # issue to fix.} other {Check {n}: # issues to fix.}}", { count: 2, n: 7 })).toBe("Vérification 7 : 2 problèmes à corriger.");
    expect(t("{count, plural, one {# activity} other {# activities}}", { count: 0 })).toBe("0 activité");
    expect(t("{count, plural, one {# activity} other {# activities}}", { count: 2 })).toBe("2 activités");
    expect(createTranslator("en")("{count, plural, one {# activity} other {# activities}}", { count: 1200 })).toBe("1,200 activities");
  });
  it("parses regional preferences and rejects invalid or unsupported tags", () => {
    expect(languageCode("FR-ca")).toBe("fr");
    expect(languageCode("es-419")).toBe("es");
    expect(languageCode("frankenstein")).toBeUndefined();
    expect(languageCode("ja")).toBeUndefined();
  });
  it("keeps language selection usable when browser storage is denied", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
    render(<I18nProvider><LanguageProbe /></I18nProvider>);
    fireEvent.click(screen.getByText("French"));
    expect(screen.getByText("Enregistrer le lettrage")).toBeTruthy();
    expect(document.documentElement.lang).toBe("fr");
  });
  it("synchronizes the UI preference across tabs without project API writes", () => {
    render(<I18nProvider><LanguageProbe /></I18nProvider>);
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: "canary.uiLanguage", newValue: "es" })));
    expect(screen.getByTestId("locale").textContent).toBe("es");
    expect(screen.getByText("Guardar rotulación")).toBeTruthy();
  });
});
