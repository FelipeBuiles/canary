import type { ComponentProps } from "react";
import type * as ProjectLanguageModule from "../components/lettering/ProjectLetteringLanguage";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import type { LetteringStyle, PageLettering } from "@lettering-engine";
import { ApiError } from "../api/client";
import { I18nProvider } from "../i18n";
import fixture from "./fixtures/lettering.json";
import { LetteringEditor } from "../components/lettering/LetteringEditor";
import { LetteringStyleControls } from "../components/lettering/LetteringStyleControls";
import { letteringDraftKey, writeLetteringDraft } from "../lib/letteringHistory";
import type { HybridLetteringResponse, LetteringTranslationEstimate } from "../api/lettering";
import type { GenerationJob } from "../types/api";
const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), reset: vi.fn(), style: vi.fn(), putStyle: vi.fn(), language: vi.fn(), estimate: vi.fn(), translate: vi.fn(), jobs: [] as GenerationJob[] }));
vi.mock("../api/lettering", () => ({ getPageLettering: api.get, putPageLettering: api.put, resetPageLettering: api.reset, getBookLetteringStyle: api.style, putBookLetteringStyle: api.putStyle, getLetteringTranslationEstimate: api.estimate, translateProjectLettering: api.translate }));
vi.mock("../api/pages", () => ({ pageRenderUrl: () => "/fixture-art.png" }));
vi.mock("../api/queries", () => ({
  useGenerationJobs: (project: string) => useQuery({ queryKey: ["project", project, "generation-jobs", []], queryFn: async () => ({ jobs: api.jobs }) }),
  useCreditBalance: () => useQuery({ queryKey: ["credits", "balance"], queryFn: async () => ({ balance_credits: 100 }) }),
}));
vi.mock("../components/lettering/ProjectLetteringLanguage", async (importOriginal) => {
  const { ProjectLetteringLanguage } = await importOriginal<typeof ProjectLanguageModule>();
  return { ProjectLetteringLanguage: (props: ComponentProps<typeof ProjectLetteringLanguage>) => { api.language(props); return <ProjectLetteringLanguage {...props} />; } };
});
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
const translationEstimate: LetteringTranslationEstimate = {
  estimate_credits: 12, reserved_credits: 18, reservation_multiplier: 1.5, confidence: "variable", funding: "api",
  target_locale: "es", snapshot_sha256: "saved-snapshot", page_count: 1, element_count: 1, translate_count: 0, preserved_target_count: 1,
};
const translationJob: GenerationJob = {
  id: "translation", project_name: "book", kind: "lettering_translation", label: "Translation", payload: { target_locale: "es" },
  status: "queued", queue_position: 1, queued_at: "2099-01-01T00:00:00Z", started_at: null, finished_at: null, error: null,
};
const clients: QueryClient[] = [];
function mount(disabled = false, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  clients.push(client);
  return { client, ...render(<QueryClientProvider client={client}><I18nProvider><LetteringEditor project="book" pageNumber={1} disabled={disabled} /></I18nProvider></QueryClientProvider>) };
}
async function ready() { await screen.findByLabelText(/Words on the page/); await waitFor(() => expect((screen.getByLabelText(/Words on the page/) as HTMLTextAreaElement).disabled).toBe(false)); }
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  api.jobs = [];
  api.estimate.mockResolvedValue(translationEstimate);
  api.translate.mockResolvedValue({ job: translationJob });
  api.get.mockResolvedValue(initial());
  api.style.mockResolvedValue({ style: initial().style, presets: { literary: initial().style } });
  api.put.mockImplementation(async (_project, _page, state) => ({ ...initial(), state: { ...state, revision: 2 }, saved_revision: 2 }));
});
afterEach(() => { clients.forEach(client => client.clear()); clients.length = 0; vi.restoreAllMocks(); });
describe("Pages-room lettering", () => {
  it("recovers a read conflict through explicit project translation without losing saved wording or placement", async () => {
    api.get.mockRejectedValue(new ApiError(409, "Page locale differs from project lettering language. Translate project before editing/export."));
    const view = mount();
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.getAllByRole("region", { name: "Project language" })).toHaveLength(1);
    expect(api.translate).not.toHaveBeenCalled();
    expect(api.estimate).not.toHaveBeenCalled();
    const disclosure = screen.getByText("Project language", { selector: "summary" }).parentElement!;
    disclosure.setAttribute("open", "");
    fireEvent(disclosure, new Event("toggle"));
    fireEvent.change(screen.getByLabelText("Translate to"), { target: { value: "es" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /Translate project/ })).toHaveProperty("disabled", false));
    fireEvent.click(screen.getByRole("button", { name: /Translate project/ }));
    expect(api.translate).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Translate project" }));
    await screen.findByText(/Project translation queued/);
    expect(api.translate).toHaveBeenCalledTimes(1);
    const translated = initial();
    translated.state.locale = "es";
    translated.state.elements[0].text_by_locale = { source: "Saved source edit.", es: "Texto conservado.", fr: "Texte conservé." };
    translated.state.elements[0].placement = { x: .31, y: .42, width: .35, height: .2 };
    translated.state.elements[0].rotation = 12;
    api.get.mockResolvedValue(translated);
    api.jobs = [{ ...translationJob, status: "complete" }];
    await act(async () => { await view.client.invalidateQueries({ queryKey: ["project", "book", "generation-jobs"] }); });
    await ready();
    await screen.findByText(/Project language applied/);
    expect((screen.getByLabelText(/Words on the page/) as HTMLTextAreaElement).value).toBe("Texto conservado.");
    expect(screen.getByLabelText("Rotation")).toHaveProperty("value", "12");
    expect(screen.getAllByRole("region", { name: "Project language" })).toHaveLength(1);
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "Texto revisado." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][2].elements[0]).toEqual(expect.objectContaining({
      text_by_locale: { source: "Saved source edit.", es: "Texto revisado.", fr: "Texte conservé." },
      placement: translated.state.elements[0].placement, rotation: 12,
    }));
    expect(api.translate).toHaveBeenCalledTimes(1);
  });
  it("keeps failed translation refreshes recoverable instead of claiming success", async () => {
    api.get.mockRejectedValue(new ApiError(409, "Page locale still conflicts with project language."));
    const view = mount();
    const readError = await screen.findByRole("alert");
    api.jobs = [{ ...translationJob, status: "complete" }];
    await act(async () => { await view.client.invalidateQueries({ queryKey: ["project", "book", "generation-jobs"] }); });
    await screen.findByText(/The job finished, but the editor could not refresh/);
    expect(readError.isConnected).toBe(true);
    expect(screen.queryByText(/Project language applied/)).toBeNull();
    expect(screen.queryByLabelText(/Words on the page/)).toBeNull();
    expect(api.translate).not.toHaveBeenCalled();
    api.get.mockResolvedValue(initial());
    fireEvent.click(screen.getByRole("button", { name: "Refresh lettering" }));
    await ready();
    expect(api.translate).not.toHaveBeenCalled();
  });
  it("retains generation locks and retry when a page cannot open", async () => {
    api.get.mockRejectedValue(new ApiError(409, "Page locale conflict"));
    mount(true);
    await screen.findByRole("alert");
    const disclosure = screen.getByText("Project language", { selector: "summary" }).parentElement!;
    disclosure.setAttribute("open", "");
    fireEvent(disclosure, new Event("toggle"));
    expect(screen.getByLabelText("Translate to")).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: /Translate project/ })).toHaveProperty("disabled", true);
    api.get.mockResolvedValue(initial());
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByLabelText(/Words on the page/);
    expect(screen.getByLabelText(/Words on the page/).matches(":disabled")).toBe(true);
    expect(api.translate).not.toHaveBeenCalled();
  });
  it("rejects translation adoption when the refreshed edition is baked", async () => {
    api.get.mockRejectedValue(new ApiError(409, "Page locale conflict"));
    mount();
    await screen.findByRole("alert");
    const language = api.language.mock.lastCall![0] as { onApplied: () => Promise<void> };
    api.get.mockResolvedValue({ mode: "baked", message: "This edition has baked lettering." });
    await act(async () => { await expect(language.onApplied()).rejects.toThrow("This edition has baked lettering."); });
    await screen.findByText("Lettering is part of this artwork");
    expect(screen.queryByRole("region", { name: "Project language" })).toBeNull();
    expect(screen.queryByText(/Project language applied/)).toBeNull();
    expect(api.translate).not.toHaveBeenCalled();
  });
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
    const rejection = new ApiError(409, "revision conflict");
    api.put.mockRejectedValue(rejection);
    mount();
    await ready();
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "Do not overwrite newer work." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    expect((await screen.findByRole("alert")).textContent).toContain(rejection.message);
    expect(screen.getByRole("button", { name: "Reload saved version" })).toHaveProperty("disabled", false);
    expect(localStorage.getItem(letteringDraftKey("book", 1))).toContain("Do not overwrite newer work.");
    expect(api.put).toHaveBeenCalledTimes(1);
  });
  it("preserves unsaved placement and style while showing a language rejection without retrying", async () => {
    const data = initial();
    data.state.locale = "es";
    data.state.elements[0].text_by_locale.es = "La puerta se abrió.";
    api.get.mockResolvedValue(data);
    const rejection = new ApiError(409, "Page locale differs from project lettering language. Translate project before editing/export.");
    api.put.mockRejectedValue(rejection);
    mount();
    await ready();
    const hit = document.querySelector<HTMLButtonElement>("[data-element-id]")!;
    fireEvent.keyDown(hit, { key: "ArrowRight", shiftKey: true });
    fireEvent.click(screen.getByText("Style · this element only", { selector: "summary" }));
    const size = data.style.roles.caption.max_font_size + 4;
    fireEvent.change(screen.getByRole("spinbutton", { name: "Size" }), { target: { value: String(size) } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    expect((await screen.findByRole("alert")).textContent).toContain(rejection.message);
    expect(parseFloat(hit.style.left) / 100).toBeCloseTo(data.state.elements[0].placement.x + .01, 5);
    expect(screen.getByRole("spinbutton", { name: "Size" })).toHaveProperty("value", String(size));
    expect(screen.getByRole("button", { name: "Save lettering" })).toHaveProperty("disabled", false);
    expect(screen.getByRole("button", { name: "Reload saved version" })).toHaveProperty("disabled", false);
    const draft = JSON.parse(localStorage.getItem(letteringDraftKey("book", 1))!);
    expect(draft.state.locale).toBe("es");
    expect(draft.state.elements[0]).toEqual(expect.objectContaining({
      placement: { ...data.state.elements[0].placement, x: data.state.elements[0].placement.x + .01 },
      style_override: { ...data.style.roles.caption, max_font_size: size },
    }));
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.translate).not.toHaveBeenCalled();
  });
  it("reloads saved lettering from the server and retains its revision and locale across remounts", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const stale = initial();
    api.get.mockResolvedValue(stale);
    api.put.mockRejectedValueOnce(new ApiError(409, "revision conflict"));
    const view = mount();
    await ready();
    expect(view.client.getQueryData(["page-lettering", "book", 1])).toEqual(stale);
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "Keep my unsaved draft." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await screen.findByRole("alert");
    const fresh = initial();
    fresh.saved_revision = 7;
    fresh.state.revision = 7;
    fresh.state.locale = "es";
    fresh.state.elements[0].text_by_locale.es = "La puerta se abrió.";
    api.get.mockResolvedValue(fresh);
    expect(api.get).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Reload saved version" }));
    await screen.findByRole("button", { name: "Keep saved version" });
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText(/Words on the page/)).toHaveProperty("value", "La puerta se abrió.");
    expect(screen.getByLabelText(/Words on the page/).matches(":disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: "Restore draft" })).toBeNull();
    expect(localStorage.getItem(letteringDraftKey("book", 1))).toContain("Keep my unsaved draft.");
    expect(api.put).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Keep saved version" }));
    view.unmount();
    mount(false, view.client);
    await ready();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText(/Words on the page/)).toHaveProperty("value", "La puerta se abrió.");
    api.put.mockImplementationOnce(async (_project, _page, state) => ({ ...fresh, state: { ...state, revision: 8 }, saved_revision: 8 }));
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "La puerta estaba abierta." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await screen.findByText("Saved");
    expect(api.put).toHaveBeenCalledTimes(2);
    expect(api.put.mock.calls[1][2]).toEqual(expect.objectContaining({ revision: 7, locale: "es" }));
    expect(api.put.mock.calls[1][2].elements[0].text_by_locale).toEqual({ source: "The door opened.", es: "La puerta estaba abierta." });
    expect(api.put.mock.calls[1][3]).toEqual(expect.objectContaining({ saved_revision: 7 }));
    expect(localStorage.getItem(letteringDraftKey("book", 1))).toBeNull();
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
    expect(screen.queryByRole("region", { name: "Project language" })).toBeNull();
    expect(api.put).not.toHaveBeenCalled();
  });
  it("starts keyboard resizing at the fitted edge, and undo restores snug sizing", async () => {
    mount();
    await ready();
    const hit = document.querySelector<HTMLButtonElement>("[data-element-id]")!;
    const before = parseFloat(hit.style.width) / 100;
    expect(before).toBeLessThan(initial().state.elements[0].placement.width);
    fireEvent.keyDown(screen.getByRole("button", { name: "Resize selected lettering" }), { key: "ArrowRight" });
    expect(parseFloat(hit.style.width) / 100).toBeCloseTo(before + .001, 5);
    fireEvent.click(screen.getByRole("button", { name: /Undo/ }));
    expect(parseFloat(hit.style.width) / 100).toBeCloseTo(before, 5);
  });
  it("allows clearing a numeric field without snapping back on the first key", () => {
    const onChange = vi.fn();
    render(<I18nProvider><LetteringStyleControls value={initial().style.roles.caption} onChange={onChange} /></I18nProvider>);
    const field = screen.getByRole("spinbutton", { name: "Size" }) as HTMLInputElement;
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: "" } });
    expect(field.value).toBe("");
    fireEvent.change(field, { target: { value: "3" } });
    expect(field.value).toBe("3");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "32" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ max_font_size: 32 }));
  });
  it("keeps translated editing separate from canonical source reset", async () => {
    const data = initial();
    data.state.locale = "es";
    data.state.elements[0].text_by_locale.es = "La puerta se abrió.";
    api.get.mockResolvedValue(data);
    mount();
    await ready();
    expect(screen.queryByRole("button", { name: "Reset copy" })).toBeNull();
    expect(screen.queryByLabelText("Language")).toBeNull();
    expect(screen.queryByLabelText("Add a language")).toBeNull();
    fireEvent.change(screen.getByLabelText(/Words on the page/), { target: { value: "La puerta estaba abierta." } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][2].elements[0].text_by_locale).toEqual({ source: "The door opened.", es: "La puerta estaba abierta." });
  });
  it("adds the chosen role and immediately edits its words", async () => {
    mount();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Add lettering" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Type of lettering" }), { target: { value: "thought" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const copy = screen.getByLabelText(/Words on the page/) as HTMLTextAreaElement;
    await waitFor(() => expect(document.activeElement).toBe(copy));
    expect(copy.value).toBe("");
    fireEvent.change(copy, { target: { value: "Could it be?" } });
    fireEvent.blur(copy);
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][2].elements[1]).toEqual(expect.objectContaining({ role: "thought", text_by_locale: { source: "Could it be?" } }));
  });
  it("previews role changes without saving and discards them on cancel", async () => {
    mount();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Book lettering style" }));
    const book = within(screen.getByRole("group", { name: "Book lettering style" }));
    const preview = book.getByRole("img", { name: /^Live sample:/ });
    const size = initial().style.roles.caption.max_font_size + 10;
    fireEvent.change(book.getByRole("spinbutton", { name: "Size" }), { target: { value: String(size) } });
    expect(Number(preview.querySelector("text")?.getAttribute("font-size"))).toBe(size);
    expect(api.putStyle).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Book lettering style" }));
    expect(Number(screen.getByRole("img", { name: /^Live sample:/ }).querySelector("text")?.getAttribute("font-size"))).toBe(initial().style.roles.caption.max_font_size);
  });
  it("does not carry an unfinished size draft into another book role", async () => {
    mount();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Book lettering style" }));
    const book = within(screen.getByRole("group", { name: "Book lettering style" }));
    const size = book.getByRole("spinbutton", { name: "Size" }) as HTMLInputElement;
    fireEvent.focus(size);
    fireEvent.change(size, { target: { value: "" } });
    expect(size.value).toBe("");
    fireEvent.change(book.getByRole("combobox", { name: "Type of lettering" }), { target: { value: "sfx" } });
    expect((book.getByRole("spinbutton", { name: "Size" }) as HTMLInputElement).value).toBe(String(initial().style.roles.sfx.max_font_size));
  });
  it("keeps page edits locked until translated lettering is adopted", async () => {
    mount();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Add lettering" }));
    const language = api.language.mock.lastCall![0] as { onBusyChange: (busy: boolean) => void; onApplied: () => Promise<void> };
    let finish!: (value: HybridLetteringResponse) => void;
    api.get.mockReturnValueOnce(new Promise<HybridLetteringResponse>(resolve => { finish = resolve; }));
    act(() => language.onBusyChange(true));
    const adopting = language.onApplied();
    expect((screen.getByLabelText(/Words on the page/) as HTMLTextAreaElement).matches(":disabled")).toBe(true);
    expect((screen.getByRole("combobox", { name: "Type of lettering" }) as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Book lettering style" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Save lettering" }) as HTMLButtonElement).disabled).toBe(true);
    const translated = initial();
    translated.state.locale = "es";
    translated.state.elements[0].text_by_locale.es = "La puerta se abrió.";
    await act(async () => { finish(translated); await adopting; language.onBusyChange(false); });
    expect((screen.getByLabelText(/Words on the page/) as HTMLTextAreaElement).value).toBe("La puerta se abrió.");
    expect((screen.getByRole("button", { name: "Undo" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.put).not.toHaveBeenCalled();
  });
});
