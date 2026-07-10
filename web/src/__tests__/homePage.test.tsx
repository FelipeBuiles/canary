import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { I18nProvider } from "../i18n";
import { HomePage } from "../pages/HomePage";

const storageValues = new Map<string, string>();
const storage: Storage = {
  get length() {
    return storageValues.size;
  },
  clear: () => storageValues.clear(),
  getItem: (key) => storageValues.get(key) ?? null,
  key: (index) => Array.from(storageValues.keys())[index] ?? null,
  removeItem: (key) => storageValues.delete(key),
  setItem: (key, value) => storageValues.set(key, value),
};

function renderHomePage() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <HomePage />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("Scenewright homepage", () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: storage,
    });
    storage.clear();
  });

  it("leads with the product outcome and a real signup path", () => {
    renderHomePage();

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Turn your novel into a graphic novel you direct.",
      }),
    ).toBeTruthy();

    const sampleLink = screen.getByRole("link", { name: /Start with a sample story/ });
    expect(sampleLink.getAttribute("href")).toBe("/signup");
    expect(screen.getByText(/AI-assisted visual adaptation/)).toBeTruthy();
    expect(screen.queryByText(/500 free credits/i)).toBeNull();
  });

  it("links rights language to the public terms and states the copyright caveat", () => {
    renderHomePage();

    const rightsLink = screen.getByRole("link", {
      name: /Read the full rights and copyright terms/,
    });
    expect(rightsLink.getAttribute("href")).toBe("/legal/terms");
    expect(screen.getByText(/Purely generated imagery may have limited copyright protection/)).toBeTruthy();
  });

  it("lets public visitors switch the marketing page to Spanish", () => {
    renderHomePage();

    fireEvent.click(screen.getByRole("button", { name: "ES" }));

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Convierte tu novela en una novela gráfica que tú diriges.",
      }),
    ).toBeTruthy();
    expect(document.documentElement.lang).toBe("es");
  });
});
