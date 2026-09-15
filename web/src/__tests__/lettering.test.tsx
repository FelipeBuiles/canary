import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EditableLettering, LetteringRole, PageLettering } from "../api/lettering";
import { getLettering, getLetteringPresets, letteringBody, previewLettering, saveLettering } from "../api/lettering";
import { LetteringEditor, LetteringWorkspace } from "../components/lettering/LetteringWorkspace";
import { draftIdentity, elementCopy, letteringHistory, moveBox, resizeBox } from "../components/lettering/letteringHistory";

vi.mock("../api/lettering", async (original) => ({
  ...await original<typeof import("../api/lettering")>(),
  getLettering: vi.fn(), getLetteringPresets: vi.fn(), previewLettering: vi.fn(),
  saveLettering: vi.fn(), applyBookLetteringStyle: vi.fn(), resetLettering: vi.fn(),
}));
const role: LetteringRole = { font: "ComicNeue-Bold", min_size: 13, max_size: 22, line_height: 1.12, padding: 8,
  align: "center", color: "#171717", fill: "#ffffff", outline: "#171717", border: 1.6, radius: 0, letter_spacing: 0, stroke: 0 };
function fixture(): EditableLettering {
  const placement = { x: .1, y: .1, width: .35, height: .16 };
  const state: PageLettering = { schema_version: 1, revision: 1, content_sha256: "b".repeat(64), page_number: 1,
    comic_page_sha256: "a".repeat(64), locale: "", reviewed_against_render_revision: 1,
    style: { preset: "literary", direction: "Compact classic narration", caption: role, dialogue: role, thought: role, sfx: role },
    elements: [{ id: "letter-1", source_lettering_item_id: "letter-1", kind: "caption", copies: {}, suggested_placement: placement,
      placement, tail_target: null, style_override: null, hidden: false, rotation: 0, scale: 1, z_index: 0,
      resolved: { lines: ["The door opened."], widths: [150], font_size: 22, body_height: .04, overflow: false, reason: "", signature: "measured" } }] };
  return { mode: "editable", state, svg: '<svg viewBox="0 0 1000 1500"><g data-lettering-id="letter-1"><text>The door opened.</text></g></svg>',
    aspect: 1.5, render_revision: 1, saved_sha256: state.content_sha256, saved_revision: 1,
    canonical_copy: { "letter-1": "The door opened." }, placement_needs_review: false };
}
function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}
function mount() { return wrap(<LetteringEditor project="book" initial={fixture()} onDirtyChange={vi.fn()} />); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear();
  vi.mocked(getLetteringPresets).mockResolvedValue({ literary: fixture().state.style });
  vi.mocked(getLettering).mockResolvedValue(fixture());
  vi.mocked(previewLettering).mockImplementation(async (_project, state) => ({ ...fixture(), state }));
  vi.mocked(saveLettering).mockImplementation(async (_project, state) => ({ ...fixture(), state: { ...state, revision: 2, content_sha256: "c".repeat(64) }, saved_sha256: "c".repeat(64), saved_revision: 2 }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("lettering state and geometry", () => {
  it("keeps normalized movement/resize inside the page, including tiny edge boxes", () => {
    expect(moveBox({ x: .1, y: .1, width: .3, height: .2 }, 2, -2)).toEqual({ x: .7, y: 0, width: .3, height: .2 });
    const tiny = resizeBox({ x: .99, y: .99, width: .01, height: .01 }, -.2, -.2);
    expect(tiny.x + tiny.width).toBeLessThanOrEqual(1);
    expect(tiny.y + tiny.height).toBeLessThanOrEqual(1);
  });
  it("separates resolved layout from edit identity and coalesces typing into one undo", () => {
    const initial = fixture().state;
    const edited = { ...initial, locale: "es" };
    let history = letteringHistory({ past: [], present: initial, future: [] }, { type: "edit", value: edited });
    history = letteringHistory(history, { type: "edit", coalesce: true, value: { ...edited, locale: "fr" } });
    expect(history.past).toHaveLength(1);
    expect(letteringHistory(history, { type: "undo" }).present).toEqual(initial);
    expect(draftIdentity({ ...initial, revision: 10, content_sha256: "new" })).toBe(draftIdentity(initial));
  });
  it("never substitutes canonical source copy for a missing translation", () => {
    const initial = fixture();
    expect(elementCopy(initial.state.elements[0], { ...initial.state, locale: "es" }, initial.canonical_copy)).toBe("");
  });
  it("does not send a stale content hash as the identity of an edited payload", () => {
    const initial = fixture();
    const body = JSON.parse(letteringBody(initial.state, initial.saved_sha256));
    expect(body.state.content_sha256).toBeUndefined();
    expect(body.expected_sha256).toBe(initial.saved_sha256);
  });
});

describe("Pages lettering workspace", () => {
  it("shows an explicit retained-edition message rather than duplicate overlays", async () => {
    vi.mocked(getLettering).mockResolvedValue({ mode: "baked", message: "Create a new Draw edition." });
    wrap(<LetteringWorkspace project="book" pageNumber={1} onDirtyChange={vi.fn()} />);
    expect(await screen.findByText("Lettering is part of this artwork")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save lettering" })).toBeNull();
    expect(previewLettering).not.toHaveBeenCalled();
  });
  it("edits display copy, retains source links, and supports undo/redo without generation", async () => {
    mount();
    const copy = screen.getByLabelText("Display text");
    fireEvent.focus(copy);
    fireEvent.change(copy, { target: { value: "The" } });
    fireEvent.change(copy, { target: { value: "The window opened." } });
    fireEvent.click(screen.getByRole("button", { name: "Undo lettering edit" }));
    expect((copy as HTMLTextAreaElement).value).toBe("The door opened.");
    fireEvent.click(screen.getByRole("button", { name: "Redo lettering edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(saveLettering).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(saveLettering).mock.calls[0];
    expect(sent[1].elements[0].copies[""]).toBe("The window opened.");
    expect(sent[1].elements[0].source_lettering_item_id).toBe("letter-1");
    expect(sent[1].reviewed_against_render_revision).toBeNull();
    expect(sent[2]).toBe(fixture().saved_sha256);
  });
  it("keeps a newer edit when an older save completes", async () => {
    const saved = deferred<EditableLettering>();
    vi.mocked(saveLettering).mockReturnValueOnce(saved.promise);
    mount();
    const input = screen.getByLabelText("Display text");
    fireEvent.change(input, { target: { value: "First edit" } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    const submitted = vi.mocked(saveLettering).mock.calls[0][1];
    fireEvent.change(input, { target: { value: "Newer unsaved edit" } });
    await act(async () => saved.resolve({ ...fixture(), state: submitted, saved_sha256: "c".repeat(64) }));
    expect((input as HTMLTextAreaElement).value).toBe("Newer unsaved edit");
    expect(screen.getByText("Unsaved lettering edits")).toBeTruthy();
  });
  it("retains failed drafts and never automatically retries a conflicting save", async () => {
    vi.mocked(saveLettering).mockRejectedValueOnce(new Error("Changed in another session"));
    mount();
    fireEvent.change(screen.getByLabelText("Display text"), { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect((screen.getByLabelText("Display text") as HTMLTextAreaElement).value).toBe("Keep this draft");
    expect(saveLettering).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Reload saved page" })).toBeTruthy();
  });
  it("allows clearing and entering negative numeric values before committing", async () => {
    mount();
    const rotation = screen.getByLabelText("Rotation °");
    fireEvent.change(rotation, { target: { value: "" } });
    fireEvent.change(rotation, { target: { value: "-15" } });
    fireEvent.keyDown(rotation, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(saveLettering).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveLettering).mock.calls[0][1].elements[0].rotation).toBe(-15);
  });
  it("recovers an unsaved local draft explicitly after remount", async () => {
    const view = mount();
    fireEvent.change(screen.getByLabelText("Display text"), { target: { value: "Recover me" } });
    view.unmount();
    mount();
    expect(screen.getByText(/A local unsaved draft was recovered/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restore local draft" }));
    expect((screen.getByLabelText("Display text") as HTMLTextAreaElement).value).toBe("Recover me");
  });
  it("nudges via keyboard and resets placement independently from copy", async () => {
    mount();
    const hit = screen.getByRole("button", { name: "Select caption: The door opened." });
    fireEvent.keyDown(hit, { key: "ArrowRight", shiftKey: true });
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(saveLettering).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveLettering).mock.calls[0][1].elements[0].placement.x).toBe(.11);
    fireEvent.click(screen.getByRole("button", { name: "Reset placement" }));
    fireEvent.click(screen.getByRole("button", { name: "Save lettering" }));
    await waitFor(() => expect(saveLettering).toHaveBeenCalledTimes(2));
    expect(vi.mocked(saveLettering).mock.calls[1][1].elements[0].placement.x).toBe(.1);
  });
  it("does not let a late preview replace newer copy", async () => {
    const first = deferred<EditableLettering>();
    vi.mocked(previewLettering).mockReturnValueOnce(first.promise);
    mount();
    fireEvent.change(screen.getByLabelText("Display text"), { target: { value: "Older preview" } });
    await waitFor(() => expect(previewLettering).toHaveBeenCalledTimes(1));
    const old = vi.mocked(previewLettering).mock.calls[0][1];
    fireEvent.change(screen.getByLabelText("Display text"), { target: { value: "Newest copy" } });
    await act(async () => first.resolve({ ...fixture(), state: old }));
    expect((screen.getByLabelText("Display text") as HTMLTextAreaElement).value).toBe("Newest copy");
  });
});
