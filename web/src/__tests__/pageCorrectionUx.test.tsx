import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n";
import { RevisionDraft } from "../components/pages/RevisionDraft";
import { AnnotationEditor } from "../components/pages/AnnotationEditor";
import { loadRevisionDraft, saveRevisionDraft } from "../api/pageRevisions";
import type { PageCorrectionAnnotation, PageCorrectionBody, PageCorrectionPreview } from "../api/pages";

const mocks = vi.hoisted(() => ({ preview: vi.fn(), submit: vi.fn(), jobStatus: "queued", refresh: vi.fn(), jobError: false, jobMissing: false }));
vi.mock("../api/pageRevisions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/pageRevisions")>();
  const { useState } = await import("react");
  return {
    ...actual,
    useCorrectionPreview: () => {
      const [data, setData] = useState<PageCorrectionPreview>();
      return { data, error: null, isPending: false, mutate: (args: { body: PageCorrectionBody }, options: { onSuccess: (result: PageCorrectionPreview) => void }) => {
        mocks.preview(args);
        const result: PageCorrectionPreview = {
          selected_issue_ids: [], unselected_open_issue_ids: [], pending_manual_change_ids: [],
          changes: args.body.changes.map((change) => ({ ...change, issue_id: change.issue_id ?? null })),
          note: args.body.note ?? null, mode: "instructed", instruction: "Compiled request",
          context: { adaptation_revision: 1, adaptation_sha256: "a".repeat(64), treatment_spine: [], beat_ids: [], beat_count: 0,
            appearance_chronology: [], continuity: [], source_unit_ids: [], selected_source_unit_ids: [], omitted_source_unit_ids: [], context_digest: "", truncated: false },
          references: [], profile: { id: "test", provider: "test", model: "test" }, lettering_count: 0, prompt_characters: 16,
          request_sha256: "b".repeat(64), warnings: [], estimate: { estimate_credits: 5, reserved_credits: 6, reservation_multiplier: 1.2, confidence: "variable" },
        };
        setData(result); options.onSuccess(result);
      } };
    },
    useSubmitCorrections: () => ({ isPending: false, error: null,
      mutate: (args: unknown, options: { onSuccess: (result: { job: { id: string } }) => void }) => {
        mocks.submit(args); options.onSuccess({ job: { id: "queued-job" } });
      } }),
    useSubmittedCorrectionJob: () => ({ data: { jobs: mocks.jobMissing ? [] : [{ id: "queued-job", status: mocks.jobStatus }] }, error: mocks.jobError ? new Error("offline") : null, refetch: mocks.refresh, isFetching: false }),
    useRenderCorrection: () => ({ data: null, isLoading: false, error: null }),
  };
});

const target = { comicPageRevision: 2, parentRenderRevision: 1 };
function saved(annotations: PageCorrectionAnnotation[], instruction = "Make his hair pink") {
  saveRevisionDraft({ project: "demo", pageNumber: 1, ...target, comicPageSha256: "a".repeat(64),
    changes: [{ id: "request-1", instruction, selected: true, annotations }],
    note: "", contextSourceUnitIds: [], updatedAt: new Date().toISOString() });
}
function renderDraft(openEditing = true) {
  render(<QueryClientProvider client={new QueryClient()}><I18nProvider>
    <RevisionDraft project="demo" pageNumber={1} {...target} comicPageSha256={"a".repeat(64)} compareRevision={null}
      issues={[]} seeds={[]} onSeedsConsumed={vi.fn()} onJobQueued={vi.fn()} />
  </I18nProvider></QueryClientProvider>);
  const edit = screen.queryByRole("button", { name: /make changes/i });
  if (edit && openEditing) fireEvent.click(edit);
}

beforeEach(() => { window.localStorage.clear(); vi.clearAllMocks(); mocks.jobStatus = "queued"; mocks.jobError = false; mocks.jobMissing = false; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("text-first page correction", () => {
  it("previews text directly, then submits the exact reviewed body only on confirmation", () => {
    renderDraft();
    expect(screen.queryByRole("toolbar", { name: /annotation tools/i })).toBeNull();
    fireEvent.change(screen.getByLabelText("What would you like to change?"), { target: { value: "Make the car a red sports car" } });
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(mocks.preview).toHaveBeenCalledTimes(1);
    const args = mocks.preview.mock.calls[0]![0];
    expect(args.body.changes).toEqual([expect.objectContaining({ instruction: "Make the car a red sports car", annotations: [] })]);
    expect(mocks.submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(mocks.submit).toHaveBeenCalledWith(args);
    expect(loadRevisionDraft("demo", 1, target)?.submittedJobId).toBe("queued-job");
  });
  it("retries a failed queued correction with the same change identity after reopening", () => {
    mocks.jobStatus = "failed";
    saved([]);
    const draft = loadRevisionDraft("demo", 1, target)!;
    saveRevisionDraft({ ...draft, submittedJobId: "queued-job" });
    renderDraft(false);
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(mocks.preview.mock.calls[0][0].body.changes[0].id).toBe("request-1");
    expect(mocks.submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(mocks.submit.mock.calls[0][0].body.changes[0].id).toBe("request-1");
    mocks.jobStatus = "queued";
  });
  it("restores Make changes on a completed request when returning to its original version", () => {
    mocks.jobStatus = "complete";
    saved([]);
    saveRevisionDraft({ ...loadRevisionDraft("demo", 1, target)!, submittedJobId: "queued-job" });
    renderDraft(false);
    expect(screen.queryByText(/correction.*queued/i)).toBeNull();
    expect(loadRevisionDraft("demo", 1, target)).toBeNull();
    const edit = screen.getByRole("button", { name: "MAKE CHANGES" });
    expect(edit).toHaveProperty("disabled", false);
    fireEvent.click(edit);
    expect(screen.getByLabelText("What would you like to change?")).toHaveProperty("value", "");
    fireEvent.change(screen.getByLabelText("What would you like to change?"), { target: { value: "Bare tip on the right" } });
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(mocks.preview.mock.calls[0][0].body.changes).toEqual([expect.objectContaining({ instruction: "Bare tip on the right" })]);
    expect(mocks.preview.mock.calls[0][0].body.changes[0].id).not.toBe("request-1");
    expect(loadRevisionDraft("demo", 1, target)?.submittedJobId).toBeUndefined();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it.each(["queued", "running"])("shows the redraw on the artwork while %s and asks for no action", (status) => {
    mocks.jobStatus = status;
    saved([]);
    saveRevisionDraft({ ...loadRevisionDraft("demo", 1, target)!, submittedJobId: "queued-job" });
    renderDraft(false);
    expect(screen.getByRole("button", { name: "REDRAWING…" })).toHaveProperty("disabled", true);
    expect(screen.getByText(status === "queued" ? "Redraw waiting to start" : "Redrawing this page")).toBeTruthy();
    expect(screen.getByText(/You can close this page/)).toBeTruthy();
    // Progress is polled; there is nothing to press.
    expect(screen.queryByRole("button", { name: "Check progress" })).toBeNull();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it.each(["missing", "error"])("does not pretend an unknown correction is queued: %s", (state) => {
    mocks.jobMissing = state === "missing";
    mocks.jobError = state === "error";
    saved([]);
    saveRevisionDraft({ ...loadRevisionDraft("demo", 1, target)!, submittedJobId: "queued-job" });
    renderDraft(false);
    expect(screen.getByText("Can’t confirm the redraw yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "REDRAWING…" })).toHaveProperty("disabled", true);
    expect(loadRevisionDraft("demo", 1, target)?.changes[0].id).toBe("request-1");
  });
  it("accepts the screenshot's saved marks without separate notes, preserving the full parent request", () => {
    saved([
      { id: "pin", kind: "pin", points: [{ x: 0.55, y: 0.07 }] },
      { id: "outline", kind: "freehand", points: [{ x: 0.6, y: 0.51 }, { x: 0.3, y: 0.72 }], note: "" },
    ], "a".repeat(1000));
    renderDraft();
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(mocks.preview).toHaveBeenCalledTimes(1);
    const change = mocks.preview.mock.calls[0]![0].body.changes[0];
    expect(change.instruction).toHaveLength(1000);
    expect(change.annotations).toHaveLength(2);
    for (const mark of change.annotations) expect(mark.note).toBe("Apply the enclosing change request at this location.");
  });
  it("adds optional context to pending text without requiring an Add request step", () => {
    renderDraft();
    fireEvent.change(screen.getByLabelText("What would you like to change?"), { target: { value: "Change only the coat" } });
    fireEvent.click(screen.getByRole("button", { name: "Add location (optional)" }));
    expect(screen.getByRole("toolbar", { name: "Annotation tools" })).toBeTruthy();
    expect(screen.queryByLabelText("What would you like to change?")).toBeNull();
    expect(screen.getByLabelText("Request")).toHaveProperty("value", "Change only the coat");
    fireEvent.click(screen.getByText("More"));
    fireEvent.click(screen.getByRole("button", { name: /without drawing/i }));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    const changes = mocks.preview.mock.calls[0]![0].body.changes;
    expect(changes).toHaveLength(1);
    expect(changes[0].instruction).toBe("Change only the coat");
    expect(changes[0].annotations).toHaveLength(1);
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it("requires another review after a location's optional detail changes", () => {
    saved([{ id: "pin", kind: "pin", points: [{ x: 0.5, y: 0.5 }] }]);
    renderDraft();
    fireEvent.click(screen.getByRole("button", { name: /mark on page/i }));
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(screen.getByRole("button", { name: "Generate revision" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Extra detail (optional)"), { target: { value: "Only the left side" } });
    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(screen.getByRole("button", { name: "Review changes" })).toBeTruthy();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it("lets the author finish marking after excluding a request", () => {
    saved([{ id: "pin", kind: "pin", points: [{ x: 0.5, y: 0.5 }] }]);
    renderDraft();
    fireEvent.click(screen.getByRole("button", { name: /mark on page/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /include fix/i }));
    const done = screen.getByRole("button", { name: /done marking/i });
    expect(done).toHaveProperty("disabled", false);
    fireEvent.click(done);
    expect(screen.queryByRole("toolbar", { name: "Annotation tools" })).toBeNull();
    expect(screen.getByLabelText("What would you like to change?")).toBeTruthy();
  });
  it("explains invalid stored geometry before requesting an estimate", () => {
    saved([{ id: "bad", kind: "rectangle", points: [{ x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 }] }]);
    renderDraft();
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(screen.getByRole("alert").textContent).toMatch(/too small/i);
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
});

function editor(initial: PageCorrectionAnnotation[] = []) {
  const changed = vi.fn();
  function Harness() {
    const [value, setValue] = useState(initial);
    return <I18nProvider><AnnotationEditor imageSrc="/page.png" alt="Example page" value={value}
      onChange={(next) => { changed(next); setValue(next); }} /></I18nProvider>;
  }
  const view = render(<Harness />);
  const canvas = screen.getByRole("group", { name: "Page locations" });
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 200, bottom: 300, width: 200, height: 300, toJSON: () => ({}) });
  // Keep the gesture assertions independent of jsdom's PointerEvent support.
  vi.stubGlobal("PointerEvent", class extends MouseEvent {
    pointerId = 1;
    isPrimary = true;
  });
  return { ...view, canvas, changed };
}

describe("optional location editor", () => {
  it("shows only three named drawing tools until More is opened", () => {
    editor();
    const toolbar = screen.getByRole("toolbar", { name: "Annotation tools" });
    // jsdom's accessibility queries do not implement closed <details> visibility.
    // Assert the native disclosure and the actual primary-toolbar boundary.
    expect([...toolbar.children].filter((child) => child.tagName === "BUTTON")
      .map((button) => button.textContent)).toEqual(["Pin", "Area", "Highlight"]);
    const more = screen.getByText("More").closest("details")!;
    expect(more.open).toBe(false);
    expect(more.contains(screen.getByRole("button", { name: "Undo mark" }))).toBe(true);
    fireEvent.click(screen.getByText("More"));
    expect(more.open).toBe(true);
  });
  it("keeps saved location names and optional detail, but never exposes coordinate dumps", () => {
    const { container } = editor([{ id: "old", kind: "freehand", points: [{ x: 0.1234, y: 0.5678 }, { x: 0.2222, y: 0.8888 }] }]);
    expect(screen.getByRole("button", { name: "1 · Outline" })).toBeTruthy();
    expect(screen.getByLabelText("Extra detail (optional)")).toBeTruthy();
    expect(container.textContent).not.toMatch(/0\.1234|0\.5678|NUMBERED NOTES/);
  });
  it("uses the release position even without a move event, and returns to selection", () => {
    const { canvas, changed } = editor();
    fireEvent.click(screen.getByRole("button", { name: "Pin" }));
    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 60, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 100, clientY: 90, button: 0 });
    expect(changed).toHaveBeenCalledTimes(1);
    expect(changed.mock.calls[0]![0][0].points).toEqual([{ x: 0.5, y: 0.3 }]);
    expect(screen.getByRole("button", { name: "Pin" }).getAttribute("aria-pressed")).toBe("false");
    fireEvent.pointerDown(canvas, { clientX: 120, clientY: 90, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 120, clientY: 90, button: 0 });
    expect(changed).toHaveBeenCalledTimes(1);
  });
  it("cancels interrupted gestures and refuses zero-area selections", () => {
    const { canvas, changed } = editor();
    fireEvent.click(screen.getByRole("button", { name: "Area" }));
    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 60, button: 0 });
    fireEvent.pointerCancel(canvas);
    fireEvent.pointerUp(canvas, { clientX: 100, clientY: 120, button: 0 });
    expect(changed).not.toHaveBeenCalled();
    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 60, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 50, clientY: 60, button: 0 });
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toMatch(/drag a little farther/i);
  });
  it("moves the keyboard-focused badge, not another selected location", () => {
    const { changed } = editor([
      { id: "first", kind: "pin", points: [{ x: 0.2, y: 0.2 }] },
      { id: "second", kind: "pin", points: [{ x: 0.8, y: 0.8 }] },
    ]);
    const first = screen.getByRole("button", { name: "Select location 1: Pin" });
    fireEvent.focus(first);
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(changed.mock.lastCall![0].map((mark: PageCorrectionAnnotation) => mark.points[0])).toEqual([
      { x: 0.21, y: 0.2 }, { x: 0.8, y: 0.8 },
    ]);
  });
  it("offers keyboard pin placement, movement, and removal without showing numbers as coordinates", () => {
    const { canvas, changed } = editor();
    fireEvent.click(screen.getByText("More"));
    fireEvent.click(screen.getByRole("button", { name: /without drawing/i }));
    fireEvent.keyDown(canvas, { key: "ArrowRight", shiftKey: true });
    expect(changed.mock.lastCall![0][0].points).toEqual([{ x: 0.55, y: 0.5 }]);
    fireEvent.keyDown(canvas, { key: "Delete" });
    expect(changed.mock.lastCall![0]).toEqual([]);
  });
});
