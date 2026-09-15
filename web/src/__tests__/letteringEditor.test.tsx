import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { LetteringStyle, PageLettering } from "@lettering-engine";
import { ApiError } from "../api/client";
import { I18nProvider } from "../i18n";
import fixture from "./fixtures/lettering.json";
import { LetteringEditor } from "../components/lettering/LetteringEditor";
import { LetteringStyleControls } from "../components/lettering/LetteringStyleControls";
import { letteringDraftKey, writeLetteringDraft } from "../lib/letteringHistory";
import type { HybridLetteringResponse } from "../api/lettering";
const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), reset: vi.fn(), style: vi.fn(), putStyle: vi.fn() }));
vi.mock("../api/lettering", () => ({ getPageLettering: api.get, putPageLettering: api.put, resetPageLettering: api.reset, getBookLetteringStyle: api.style, putBookLetteringStyle: api.putStyle }));
vi.mock("../api/pages", () => ({ pageRenderUrl: () => "/fixture-art.png" }));
vi.mock("@lettering-engine", async (importOriginal) => ({
  ...await importOriginal<typeof import("@lettering-engine")>(), loadFonts: () => Promise.resolve(),
  canvasMeasure: () => ((text: string, _font: string, size: number) => text.length * size * .5),
}));
const initial = (): HybridLetteringResponse => ({
  mode: "hybrid", ...structuredClone(fixture) as {
    state: PageLettering;
    style: LetteringStyle;
  }, saved_revision: 1, render_revision: 1, render_image_sha256: "b".repeat(64), source_stale: false, needs_save: false, placement_review_needed: false,
  canonical: { "source-1": { text: "The door opened.", kind: "caption", speaker: null, delivery: "narration", panel_number: 1 } }
});
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><I18nProvider><LetteringEditor project="book" pageNumber={1} /></I18nProvider></QueryClientProvider>); }
async function ready() { await screen.findByLabelText(/Words on the page/); await waitFor(() => expect((screen.getByLabelText(/Words on the page/) as HTMLTextAreaElement).disabled).toBe(false)); }
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  api.get.mockResolvedValue(initial());
  api.style.mockResolvedValue({ style: initial().style, presets: { literary: initial().style } });
  api.put.mockImplementation(async (_project, _page, state) => ({ ...initial(), state: { ...state, revision: 2 }, saved_revision: 2 }));
});
afterEach(() => vi.restoreAllMocks());
describe("Pages-room lettering", () => {
  it("saves copy without claiming placement was reviewed on missing artwork", async () => {
    mount();
    await ready();
    fireEvent.error(screen.getByAltText("Immutable base artwork"));
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "A safe draft." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][4]).toBe(false);
  });
  it("records a visual review only once the current artwork is loaded", async () => {
    mount();
    await ready();
    fireEvent.load(screen.getByAltText("Immutable base artwork"));
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "Reviewed placement." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][4]).toBe(true);
  });
  it("keeps the local draft when optimistic concurrency rejects a stale save", async () => {
    api.put.mockRejectedValue(new ApiError(409, "revision conflict"));
    mount();
    await ready();
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "Do not overwrite newer work." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await screen.findByText(/A newer page, artwork, or book style/);
    expect(localStorage.getItem(letteringDraftKey("book", 1))).toContain("Do not overwrite newer work.");
    expect(api.put).toHaveBeenCalledTimes(1);
  });
  it("edits display copy, saves explicitly, and can undo even after saving", async () => {
    mount();
    await ready();
    const copy = screen.getByLabelText(/Words on the page/);
    fireEvent.focus(copy);
    fireEvent.change(copy, { target: { value: "A new sentence." } });
    fireEvent.blur(copy);
    await waitFor(() => expect(screen.getByText(/Unsaved · draft kept/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][2].elements[0].text_by_locale.source).toBe("A new sentence.");
    expect(api.put.mock.calls[0][2].comic_page_sha256).toBe(initial().state.comic_page_sha256);
    await waitFor(() => expect(screen.getByText("Saved")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Undo/ }));
    expect((copy as HTMLTextAreaElement).value).toBe("The door opened.");
  });
  it("keeps failed saves recoverable and never erases the draft", async () => {
    api.put.mockRejectedValue(new Error("Connection interrupted"));
    mount();
    await ready();
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "Recover these words." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await screen.findByText("Connection interrupted");
    expect(localStorage.getItem(letteringDraftKey("book", 1))).toContain("Recover these words.");
    expect((screen.getByLabelText(/Words on the page/) as HTMLTextAreaElement).value).toBe("Recover these words.");
  });
  it("offers an explicit recovery decision instead of overwriting saved text", async () => {
    const data = initial(), draft = structuredClone(data.state);
    draft.elements[0].text_by_locale.source = "Recovered draft.";
    writeLetteringDraft(letteringDraftKey("book", 1), { version: 1, baseRevision: 1, sourceSha: data.state.comic_page_sha256, styleSha: data.style.content_sha256, imageSha: data.render_image_sha256, state: draft, updatedAt: "2026-09-15T00:00:00Z" });
    mount();
    await screen.findByRole("button", { name: /Restore draft/ });
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Restore draft/ }));
    await ready();
    expect((screen.getByLabelText(/Words on the page/) as HTMLTextAreaElement).value).toBe("Recovered draft.");
  });
  it("does not offer overlays on a baked edition", async () => {
    api.get.mockResolvedValue({ mode: "baked", message: "Start a fresh Draw edition to use editable lettering." });
    mount();
    await screen.findByText("Lettering is part of this artwork");
    expect(screen.queryByRole("button", { name: "Save lettering" })).toBeNull();
    expect(api.put).not.toHaveBeenCalled();
  });
  it("allows clearing a numeric field without snapping back on the first key", () => {
    const onChange = vi.fn();
    render(<I18nProvider><LetteringStyleControls value={initial().style.roles.caption} onChange={onChange} /></I18nProvider>);
    const field = screen.getByLabelText("Preferred size") as HTMLInputElement;
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: "" } });
    expect(field.value).toBe("");
    fireEvent.change(field, { target: { value: "3" } });
    expect(field.value).toBe("3");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "32" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ max_font_size: 32 }));
  });
});
