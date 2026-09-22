import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>
      <I18nProvider>
        <HomePage />
      </I18nProvider>
    </MemoryRouter></QueryClientProvider>,
  );
}

describe("Scenewright homepage", () => {
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: storage,
    });
    storage.clear();
  });


  it("places finished books immediately after the scene sample", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        id: "sample", title: "A complete story", author: "An author", description: "A finished edition.",
        pages: [{ number: 1, url: "/page.jpg", width: 120, height: 180 }],
      }],
    }));
    renderHomePage();
    const heading = await screen.findByRole("heading", { name: "Read a finished book" });
    const section = heading.closest("section");
    expect(section?.previousElementSibling?.id).toBe("continuity");
    expect(section?.nextElementSibling?.id).toBe("process");
    expect(screen.getByRole("link", { name: "Read book" }).getAttribute("href")).toBe("/read/sample");
  });

  it("leads with the product outcome and a real signup path", () => {
    renderHomePage();

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Your story. Its first comic scene.",
      }),
    ).toBeTruthy();

    const sampleLink = screen.getAllByRole("link", { name: /Create my first scene/ })[0];
    expect(sampleLink.getAttribute("href")).toBe("/signup");
    expect(screen.getByText(/AI-assisted visual adaptation/)).toBeTruthy();
    expect(screen.queryByText(/500 free credits/i)).toBeNull();
  });

  it("makes provisional development pages readable without claiming customer or production proof", () => {
    renderHomePage();

    expect(screen.getByText(/Not customer work; results vary/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Read a development sample" }).getAttribute("href")).toBe("#continuity");
    expect(screen.getAllByRole("link", { name: "Read page 20 at full size" })[0].getAttribute("href")).toBe("/api/public/books/d1cb0ec790244ce6849974daa586146b/ccf1a606bd1747c4864d8a4770000891/pages/20");
    expect(screen.getByText(/Automated checks do not guarantee visual quality/)).toBeTruthy();
    expect(screen.getByText(/not a fixed number of pages/)).toBeTruthy();
  });

  it("localizes the new entry point and sample links in French", () => {
    renderHomePage();
    fireEvent.click(screen.getByRole("button", { name: "FR" }));

    expect(screen.getByRole("heading", { level: 1, name: "Votre récit. Sa première scène de BD." })).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /Créer ma première scène/ })[0].getAttribute("href")).toBe("/signup");
    expect(screen.getAllByRole("link", { name: "Lire la page 21 en taille réelle" })[0].getAttribute("href")).toBe("/api/public/books/d1cb0ec790244ce6849974daa586146b/ccf1a606bd1747c4864d8a4770000891/pages/21");
    expect(screen.getByRole("link", { name: "Aller au contenu" })).toBeTruthy();
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
        name: "Tu historia. Su primera escena de cómic.",
      }),
    ).toBeTruthy();
    expect(document.documentElement.lang).toBe("es");
  });
});
