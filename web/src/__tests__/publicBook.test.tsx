import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PublicBookPage } from "../pages/PublicBookPage";
import { BookPublication } from "../components/book/BookPublication";
import { apiFetch } from "../api/client";
vi.mock("../i18n", () => ({ useI18n: () => ({ t: (value: string) => value }) }));
vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
const book = { id: "a".repeat(32), version: "v1", title: "A shared story", author: "Author", description: "A complete comic", allow_feature: false, featured: false, pages: [{ number: 1, width: 120, height: 180, url: "/public-page-1" }, { number: 2, width: 120, height: 180, url: "/public-page-2" }] };
function wrapper(child: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><MemoryRouter initialEntries={[`/read/${book.id}`]}>{child}</MemoryRouter></QueryClientProvider>);
}
afterEach(() => { vi.unstubAllGlobals(); vi.resetAllMocks(); });
describe("public books", () => {
  it("reads every published page without authentication and includes a back page in downloads", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => book }));
    wrapper(<Routes><Route path="/read/:id" element={<PublicBookPage />} /></Routes>);
    const reader = await screen.findByRole("dialog", { name: "Book reader" });
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
    fireEvent.click(screen.getByRole("button", { name: "SPREADS" }));
    expect(screen.getByRole("heading", { name: "Every book starts with a story." })).toBeTruthy();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByRole("img", { name: "Page 2 — Page 2" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close reader" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    expect(screen.getByRole("img", { name: "Page 1 — Page 1" })).toBeTruthy();
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
    await screen.findByRole("button", { name: "Unpublish" });
    const call = vi.mocked(apiFetch).mock.calls.find(([, options]) => options?.method === "POST");
    expect(JSON.parse(call![1]!.body as string)).toEqual({ title: "Working title", author: "Author", description: "", allow_feature: false });
    fireEvent.click(screen.getByRole("button", { name: "Unpublish" }));
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(true));
  });
});
