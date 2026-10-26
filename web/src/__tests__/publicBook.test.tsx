import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PublicBookPage } from "../pages/PublicBookPage";
import { BookPublication } from "../components/book/BookPublication";
import { apiFetch } from "../api/client";
vi.mock("../i18n", async () => ({
  useI18n: () => ({ t: (value: string, values?: Record<string, string | number>) => value.replace(/\{(\w+)\}/g, (match, key) => String(values?.[key] ?? match)) }),
  LANGUAGES: [{ code: "en", label: "English" }, { code: "es", label: "Español" }, { code: "fr", label: "Français" }],
}));
vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
const book = { id: "a".repeat(32), version: "v1", title: "A shared story", author: "Author", description: "A complete comic", allow_feature: false, featured: false, pages: [{ number: 1, width: 120, height: 180, url: "/public-page-1" }, { number: 2, width: 120, height: 180, url: "/public-page-2" }] };
function wrapper(child: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><MemoryRouter initialEntries={[`/read/${book.id}`]}>{child}</MemoryRouter></QueryClientProvider>);
}
afterEach(() => { vi.unstubAllGlobals(); vi.resetAllMocks(); vi.restoreAllMocks(); window.localStorage.clear(); });
const pageSet = (prefix: string) => book.pages.map(page => ({ ...page, url: `/${prefix}-page-${page.number}` }));
const multilingual = { ...book, locale: "source", translations: [{ locale: "es", pages: pageSet("es") }, { locale: "fr", pages: pageSet("fr") }] };
describe("public books", () => {
  it("reads every published page without authentication and includes a back page in downloads", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => book }));
    wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    const reader = await screen.findByRole("dialog", { name: "Book reader" });
    expect(document.title).toBe(`${book.title} — Scenewright`);
    expect(document.querySelectorAll("title")).toHaveLength(1);
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe(`https://scenewright.ink/read/${book.id}`);
    expect(document.querySelector('meta[name="description"]')?.getAttribute("content")).toBe(book.description);
    expect(within(reader).getByText(book.title)).toBeTruthy();
    expect(screen.getByRole("img", { name: "Page 1 — Page 1" }).getAttribute("src")).toBe("/public-page-1");
    expect(screen.queryByRole("img", { name: /— Page 2/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Every book starts with a story." })).toBeNull();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("img", { name: "Page 2 — Page 2" }).getAttribute("src")).toBe("/public-page-2");
    expect(screen.queryByRole("img", { name: /— Page 1/ })).toBeNull();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("heading", { name: "Every book starts with a story." })).toBeTruthy();
    expect(screen.getByText("Bring your story to life.")).toBeTruthy();
    expect(screen.queryByText("Every comic starts with a story.")).toBeNull();
    expect(screen.getByRole("link", { name: "Create yours with Scenewright" }).getAttribute("href")).toContain(`ref=book-${book.id}`);
    fireEvent.click(screen.getByText("Download this book"));
    expect(screen.getByRole("link", { name: "PDF" }).getAttribute("href")).toBe(`/api/public/books/${book.id}/download/pdf`);
    expect(screen.getByRole("link", { name: "CBZ" }).getAttribute("href")).toBe(`/api/public/books/${book.id}/download/cbz`);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByRole("img", { name: "Back page preview" })).toBeTruthy();
  });
  it("supports swipe navigation and retains the closing page across layout switches", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => book }));
    wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    const reader = await screen.findByRole("dialog", { name: "Book reader" });
    fireEvent.touchStart(reader, { touches: [{ clientX: 250, clientY: 100 }] });
    fireEvent.touchEnd(reader, { changedTouches: [{ clientX: 50, clientY: 100 }] });
    expect(screen.getByRole("img", { name: "Page 2 — Page 2" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "End" });
    fireEvent.click(screen.getByRole("button", { name: "SINGLE PAGE" }));
    expect(screen.getByRole("heading", { name: "Every book starts with a story." })).toBeTruthy();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByRole("img", { name: "Page 2 — Page 2" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close reader" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("img", { name: "First page of the book" }).getAttribute("src")).toBe("/public-page-1");
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    expect(screen.getByRole("img", { name: "Page 1 — Page 1" })).toBeTruthy();
  });

  it("shows SCP source attribution alongside the public comic", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      ...book,
      source_credit: {
        title: "Merrily, Merrily, Merrily", author: "TL333s",
        source_url: "https://scp-wiki.wikidot.com/merrily-merrily-merrily",
        license: "CC BY-SA 3.0", license_url: "https://creativecommons.org/licenses/by-sa/3.0/",
      },
    }) }));
    wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    await screen.findByRole("dialog", { name: "Book reader" });
    fireEvent.keyDown(window, { key: "End" });
    expect(screen.getByRole("heading", { name: "Source and license" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Merrily, Merrily, Merrily/ }).getAttribute("href")).toContain("scp-wiki.wikidot.com");
    expect(screen.getByRole("link", { name: "CC BY-SA 3.0" }).getAttribute("href")).toContain("creativecommons.org");
  });

  it("shows an unavailable state for an unpublished book", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    expect(await screen.findByRole("heading", { name: "Book unavailable" })).toBeTruthy();
    expect(screen.queryByRole("img", { name: "Page 1" })).toBeNull();
  });
  it("requires author metadata and explicitly publishes, then allows unpublishing", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(null).mockResolvedValueOnce(book).mockResolvedValueOnce(book).mockResolvedValueOnce(null).mockResolvedValueOnce(null);
    wrapper(<BookPublication project="project" title="Working title" ready onPreview={() => {}} />);
    const author = await screen.findByLabelText("Author credit");
    expect(screen.getByRole("button", { name: "Publish book" }).hasAttribute("disabled")).toBe(true);
    fireEvent.change(author, { target: { value: "Author" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish book" }));
    await screen.findByRole("button", { name: "Edit details" });
    expect(screen.queryByLabelText("Author credit")).toBeNull();
    expect(screen.getByRole("link", { name: "Open reader page" }).getAttribute("href")).toContain(`/read/${book.id}`);
    fireEvent.click(screen.getByRole("button", { name: "Edit details" }));
    await screen.findByRole("button", { name: "Unpublish" });
    const call = vi.mocked(apiFetch).mock.calls.find(([, options]) => options?.method === "POST");
    expect(JSON.parse(call![1]!.body as string)).toEqual({ title: "Working title", author: "Author", description: "", allow_feature: false });
    fireEvent.click(screen.getByRole("button", { name: "Unpublish" }));
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(true));
  });

  it("switches between published languages on the same page and remembers the choice", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => multilingual }));
    wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    const reader = await screen.findByRole("dialog", { name: "Book reader" });
    const languages = within(reader).getByRole("group", { name: "Book language" });
    expect(within(languages).getAllByRole("button").map(button => button.textContent)).toEqual(["Original", "ES", "FR"]);
    expect(within(languages).getByRole("button", { name: "Original language" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("img", { name: "Page 2 — Page 2 · Original language" }).getAttribute("src")).toBe("/public-page-2");

    fireEvent.click(within(languages).getByRole("button", { name: "Español" }));
    expect(within(languages).getByRole("button", { name: "Español" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(languages).getByRole("button", { name: "Español" }).getAttribute("lang")).toBe("es");
    expect(screen.getByRole("img", { name: "Page 2 — Page 2 · Español" }).getAttribute("src")).toBe("/es-page-2");
    expect(screen.queryByRole("img", { name: /· Original language/ })).toBeNull();
    expect(window.localStorage.getItem("canary.readerLanguage")).toBe("es");

    fireEvent.keyDown(window, { key: "End" });
    fireEvent.click(screen.getByText("Download this book"));
    expect(screen.getByRole("link", { name: "PDF" }).getAttribute("href")).toBe(`/api/public/books/${book.id}/download/pdf?locale=es`);
    fireEvent.click(screen.getByRole("button", { name: "Close reader" }));
    expect(screen.getByRole("img", { name: "First page of the book" }).getAttribute("src")).toBe("/es-page-1");
    expect(screen.getByRole("group", { name: "Book language" })).toBeTruthy();
  });

  it("labels the shared published part and requires confirmation before replacing it", async () => {
    const published = { ...book, source_part_id: "part_0001", source_part_title: "Part one" };
    vi.mocked(apiFetch).mockResolvedValue(published);
    wrapper(<BookPublication project="project~part_0002" title="Part two" ready />);
    await screen.findByText("Published part: Part one");
    expect(vi.mocked(apiFetch).mock.calls[0][0]).toBe("/projects/project/publication");
    fireEvent.click(screen.getByRole("button", { name: "Edit details" }));
    const submit = screen.getByRole("button", { name: "Update published version" });
    expect(submit.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByLabelText("Replace the series public book with this part"));
    expect(submit.hasAttribute("disabled")).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => {
      const call = vi.mocked(apiFetch).mock.calls.find(([, options]) => options?.method === "POST");
      expect(call?.[0]).toBe("/projects/project/parts/part_0002/publication");
      expect(JSON.parse(call![1]!.body as string).expected_publication_version).toBe("v1");
    });
  });

  it("opens in the viewer's stored language and ignores one this book lacks", async () => {
    window.localStorage.setItem("canary.readerLanguage", "fr");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => multilingual }));
    const { unmount } = wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    expect((await screen.findByRole("img", { name: "Page 1 — Page 1 · Français" })).getAttribute("src")).toBe("/fr-page-1");
    unmount();
    window.localStorage.setItem("canary.readerLanguage", "en");
    wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    expect((await screen.findByRole("img", { name: "Page 1 — Page 1 · Original language" })).getAttribute("src")).toBe("/public-page-1");
  });

  it("still switches languages when browser storage is unavailable", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => multilingual }));
    wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    fireEvent.click(await screen.findByRole("button", { name: "Français" }));
    expect(screen.getByRole("img", { name: "Page 1 — Page 1 · Français" }).getAttribute("src")).toBe("/fr-page-1");
  });

  it("offers no language choice for baked or single-language books", async () => {
    for (const record of [book, { ...book, locale: "es", translations: [] }]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => record }));
      const { unmount } = wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
      expect(await screen.findByRole("img", { name: "Page 1 — Page 1" })).toBeTruthy();
      expect(screen.queryByRole("group", { name: "Book language" })).toBeNull();
      unmount();
    }
  });

  it("tells the author which languages were left out of the publication", async () => {
    const published = { ...multilingual, unpublished_locales: { en: "missing" } };
    vi.mocked(apiFetch).mockResolvedValueOnce(null).mockResolvedValueOnce(published).mockResolvedValue(multilingual);
    wrapper(<BookPublication project="project" title="Working title" ready onPreview={() => {}} />);
    fireEvent.change(await screen.findByLabelText("Author credit"), { target: { value: "Author" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish book" }));
    expect(await screen.findByText(/Not published in EN\./)).toBeTruthy();
    expect(await screen.findByText("Reader languages: Original · ES · FR")).toBeTruthy();
  });
});
