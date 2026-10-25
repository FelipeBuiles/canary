import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n";
import { RevisionDraft } from "../components/pages/RevisionDraft";
import { PageMarker, type MarkGroup } from "../components/pages/PageMarker";
import { loadRevisionDraft, saveRevisionDraft } from "../api/pageRevisions";
import type { PageCorrectionAnnotation, PageCorrectionBody, PageCorrectionPreview } from "../api/pages";
import type { PageIssue } from "../types/api";

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
          note: null, mode: "instructed", instruction: "Compiled request",
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
    changes: [{ id: "request-1", instruction, annotations }],
    contextSourceUnitIds: [], updatedAt: new Date().toISOString() });
}
function issue(id: string, requested: string): PageIssue {
  return {
    id, issue_type: "visual_prop", classification: "editorial_issue", correction_kind: "render_fidelity",
    correction_owner: "draw", page_number: 1, render_revision: 1, evidence: [], requested_correction: requested,
    status: "open", resolution_revision: null,
  };
}
/** A minimal checks rail: each finding shows its change card once included, or a Fix button. */
function renderDraft(issues: PageIssue[] = []) {
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><I18nProvider>
    <RevisionDraft project="demo" pageNumber={1} {...target} comicPageSha256={"a".repeat(64)} compareRevision={null}
      issues={issues} onJobQueued={vi.fn()}
      checks={issues.length === 0 ? undefined : (draft) => (
        <ul aria-label="Checks">
          {issues.map((finding) => <li key={finding.id}>
            {draft.included(finding.id) ?? <button type="button" onClick={() => draft.include(finding)}>Fix {finding.requested_correction}</button>}
          </li>)}
        </ul>
      )} />
  </I18nProvider></QueryClientProvider>);
}
function stubPointer(canvas: HTMLElement) {
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 200, bottom: 300, width: 200, height: 300, toJSON: () => ({}) });
  // Keep the gesture assertions independent of jsdom's PointerEvent support.
  vi.stubGlobal("PointerEvent", class extends MouseEvent {
    pointerId = 1;
    isPrimary = true;
  });
}

beforeEach(() => { window.localStorage.clear(); vi.clearAllMocks(); mocks.jobStatus = "queued"; mocks.jobError = false; mocks.jobMissing = false; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("page revision draft", () => {
  it("previews text directly, then submits the exact reviewed body only on confirmation", () => {
    renderDraft();
    fireEvent.change(screen.getByLabelText("Describe a change"), { target: { value: "Make the car a red sports car" } });
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    expect(mocks.preview).toHaveBeenCalledTimes(1);
    const args = mocks.preview.mock.calls[0]![0];
    expect(args.body.changes).toEqual([expect.objectContaining({ instruction: "Make the car a red sports car", annotations: [] })]);
    expect(args.body).not.toHaveProperty("note");
    expect(mocks.submit).not.toHaveBeenCalled();
    expect(screen.getByText("~5 credits")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(mocks.submit).toHaveBeenCalledWith(args);
    expect(loadRevisionDraft("demo", 1, target)?.submittedJobId).toBe("queued-job");
  });
  it("includes only the finding the author fixes, never every open finding", () => {
    renderDraft([issue("issue-1", "Draw the blinds closed"), issue("issue-2", "Frame over Herbert's shoulder")]);
    expect(screen.getByRole("button", { name: "REVIEW CHANGES" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Fix Frame over Herbert's shoulder" }));
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "Frame over Herbert's shoulder");
    expect(screen.getByRole("button", { name: "Fix Draw the blinds closed" })).toBeTruthy();
    // The fixed finding becomes the active change: the page is ready to mark.
    expect(screen.getByText("Click or drag on the page to show where.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    expect(mocks.preview.mock.calls[0]![0].body.changes).toEqual([
      { id: "issue:issue-2", issue_id: "issue-2", instruction: "Frame over Herbert's shoulder", annotations: [] },
    ]);
  });
  it("takes a removed finding back out of the revision", () => {
    renderDraft([issue("issue-1", "Draw the blinds closed")]);
    fireEvent.click(screen.getByRole("button", { name: "Fix Draw the blinds closed" }));
    fireEvent.click(screen.getByRole("button", { name: "REMOVE" }));
    expect(screen.queryByLabelText("Change 1")).toBeNull();
    expect(screen.getByRole("button", { name: "Fix Draw the blinds closed" })).toBeTruthy();
    expect(loadRevisionDraft("demo", 1, target)).toBeNull();
  });
  it("adds a written change with Enter and numbers it after the fixed findings", () => {
    renderDraft([issue("issue-1", "Draw the blinds closed")]);
    fireEvent.change(screen.getByLabelText("Describe a change"), { target: { value: "Warmer firelight" } });
    fireEvent.keyDown(screen.getByLabelText("Describe a change"), { key: "Enter" });
    expect(screen.getByLabelText("Describe a change")).toHaveProperty("value", "");
    fireEvent.click(screen.getByRole("button", { name: "Fix Draw the blinds closed" }));
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "Draw the blinds closed");
    expect(screen.getByLabelText("Change 2")).toHaveProperty("value", "Warmer firelight");
    expect(within(screen.getByRole("region", { name: "Your changes" })).getByLabelText("Change 2")).toBeTruthy();
  });
  it("marks the active change by clicking or dragging on the page, with no tool to choose", () => {
    renderDraft();
    fireEvent.change(screen.getByLabelText("Describe a change"), { target: { value: "Change only the coat" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const canvas = screen.getByRole("group", { name: "Page marks" });
    stubPointer(canvas);
    fireEvent.pointerDown(canvas, { clientX: 100, clientY: 150, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 100, clientY: 150, button: 0 });
    fireEvent.pointerDown(canvas, { clientX: 20, clientY: 30, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 80, clientY: 90, button: 0 });
    expect(screen.getAllByRole("button", { name: "Mark for change 1" })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    const marks = mocks.preview.mock.calls[0]![0].body.changes[0].annotations;
    expect(marks.map((mark: PageCorrectionAnnotation) => [mark.kind, mark.points])).toEqual([
      ["pin", [{ x: 0.5, y: 0.5 }]],
      ["rectangle", [{ x: 0.1, y: 0.1 }, { x: 0.4, y: 0.3 }]],
    ]);
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it("retries a failed correction with the same change identity", () => {
    mocks.jobStatus = "failed";
    saved([]);
    saveRevisionDraft({ ...loadRevisionDraft("demo", 1, target)!, submittedJobId: "queued-job" });
    renderDraft();
    expect(screen.getByText("The redraw didn’t finish. Your changes are still here.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    expect(mocks.preview.mock.calls[0][0].body.changes[0].id).toBe("request-1");
    expect(mocks.submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(mocks.submit.mock.calls[0][0].body.changes[0].id).toBe("request-1");
  });
  it.each([true, false])("reconnects a failed manual request to its tracked issue, retaining wording and marks (saved job: %s)", (savedJob) => {
    mocks.jobStatus = "failed";
    const marks: PageCorrectionAnnotation[] = [{ id: "pin", kind: "pin", points: [{ x: 0.4, y: 0.5 }], note: "Keep the coat" }];
    saved(marks, "Give the audience member a different face");
    if (savedJob) saveRevisionDraft({ ...loadRevisionDraft("demo", 1, target)!, submittedJobId: "queued-job" });
    const manual: PageIssue = { ...issue("page-issue-manual-1-1-request-1", "Original wording"), issue_type: "manual_change" };
    renderDraft([manual]);
    // The reconnected request shows inside its tracked finding, not as a separate copy.
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "Give the audience member a different face");
    expect(screen.queryByLabelText("Change 2")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    expect(mocks.preview.mock.calls[0][0].body.changes).toEqual([{
      id: "request-1", issue_id: manual.id, instruction: "Give the audience member a different face", annotations: marks,
    }]);
    expect(loadRevisionDraft("demo", 1, target)?.changes[0].issue_id).toBe(manual.id);
    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(mocks.submit.mock.calls[0][0]).toEqual(mocks.preview.mock.calls[0][0]);
  });
  it("starts fresh after a completed request on its original version", () => {
    mocks.jobStatus = "complete";
    saved([]);
    saveRevisionDraft({ ...loadRevisionDraft("demo", 1, target)!, submittedJobId: "queued-job" });
    renderDraft();
    expect(loadRevisionDraft("demo", 1, target)).toBeNull();
    expect(screen.queryByLabelText("Change 1")).toBeNull();
    fireEvent.change(screen.getByLabelText("Describe a change"), { target: { value: "Bare tip on the right" } });
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    expect(mocks.preview.mock.calls[0][0].body.changes).toEqual([expect.objectContaining({ instruction: "Bare tip on the right" })]);
    expect(mocks.preview.mock.calls[0][0].body.changes[0].id).not.toBe("request-1");
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it.each(["queued", "running"])("shows the redraw on the artwork while %s and asks for no action", (status) => {
    mocks.jobStatus = status;
    saved([]);
    saveRevisionDraft({ ...loadRevisionDraft("demo", 1, target)!, submittedJobId: "queued-job" });
    renderDraft();
    expect(screen.getByText(status === "queued" ? "Redraw waiting to start" : "Redrawing this page")).toBeTruthy();
    expect(screen.getByText(/You can close this page/)).toBeTruthy();
    // Progress is polled; there is nothing to press, and the sent change is frozen.
    expect(screen.queryByRole("button", { name: /REVIEW/ })).toBeNull();
    expect(screen.queryByLabelText("Describe a change")).toBeNull();
    expect(screen.getByLabelText("Change 1")).toHaveProperty("disabled", true);
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it.each(["missing", "error"])("does not pretend an unknown correction is queued: %s", (state) => {
    mocks.jobMissing = state === "missing";
    mocks.jobError = state === "error";
    saved([]);
    saveRevisionDraft({ ...loadRevisionDraft("demo", 1, target)!, submittedJobId: "queued-job" });
    renderDraft();
    expect(screen.getByText("Can’t confirm the redraw yet")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /REVIEW/ })).toBeNull();
    expect(loadRevisionDraft("demo", 1, target)?.changes[0].id).toBe("request-1");
  });
  it("accepts saved marks without separate notes, preserving the full parent request", () => {
    saved([
      { id: "pin", kind: "pin", points: [{ x: 0.55, y: 0.07 }] },
      { id: "outline", kind: "freehand", points: [{ x: 0.6, y: 0.51 }, { x: 0.3, y: 0.72 }], note: "" },
    ], "a".repeat(1000));
    renderDraft();
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    expect(mocks.preview).toHaveBeenCalledTimes(1);
    const change = mocks.preview.mock.calls[0]![0].body.changes[0];
    expect(change.instruction).toHaveLength(1000);
    expect(change.annotations).toHaveLength(2);
    for (const mark of change.annotations) expect(mark.note).toBeUndefined();
  });
  it("requires another review after a mark's note changes", () => {
    saved([{ id: "pin", kind: "pin", points: [{ x: 0.5, y: 0.5 }] }]);
    renderDraft();
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    expect(screen.getByRole("button", { name: "Generate revision" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mark for change 1" }));
    fireEvent.change(screen.getByLabelText("Note for mark 1 (optional)"), { target: { value: "Only the left side" } });
    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(screen.getByRole("button", { name: "REVIEW 1 CHANGE" })).toBeTruthy();
    expect(screen.getByText("Changed since your last review.")).toBeTruthy();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it("explains invalid stored geometry before requesting an estimate", () => {
    saved([{ id: "bad", kind: "rectangle", points: [{ x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 }] }]);
    renderDraft();
    fireEvent.click(screen.getByRole("button", { name: "REVIEW 1 CHANGE" }));
    expect(screen.getByRole("alert").textContent).toMatch(/too small/i);
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
});

function marker(initial: MarkGroup[], activeId: string | null = initial[0]?.id ?? null) {
  const changed = vi.fn();
  function Harness() {
    const [groups, setGroups] = useState(initial);
    const [active, setActive] = useState(activeId);
    return <I18nProvider><PageMarker imageSrc="/page.png" alt="Example page" groups={groups} activeId={active}
      remaining={24} onActivate={setActive}
      onChange={(id, marks) => { changed(id, marks); setGroups((current) => current.map((group) => group.id === id ? { ...group, marks } : group)); }} /></I18nProvider>;
  }
  render(<Harness />);
  const canvas = screen.getByRole("group", { name: "Page marks" });
  stubPointer(canvas);
  return { canvas, changed };
}

describe("page marker", () => {
  it("places a pin on click and an area on drag, without a toolbar", () => {
    const { canvas, changed } = marker([{ id: "a", number: 1, marks: [] }]);
    expect(screen.queryByRole("toolbar")).toBeNull();
    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 60, button: 0 });
    // The release position counts even without a move event.
    fireEvent.pointerUp(canvas, { clientX: 51, clientY: 61, button: 0 });
    expect(changed.mock.lastCall![1].map((mark: PageCorrectionAnnotation) => mark.kind)).toEqual(["pin"]);
    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 60, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 100, clientY: 120, button: 0 });
    expect(changed.mock.lastCall![1].map((mark: PageCorrectionAnnotation) => mark.kind)).toEqual(["pin", "rectangle"]);
  });
  it("cancels interrupted gestures", () => {
    const { canvas, changed } = marker([{ id: "a", number: 1, marks: [] }]);
    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 60, button: 0 });
    fireEvent.pointerCancel(canvas);
    fireEvent.pointerUp(canvas, { clientX: 100, clientY: 120, button: 0 });
    expect(changed).not.toHaveBeenCalled();
  });
  it("only shows marks when no change is active", () => {
    const { canvas, changed } = marker([{ id: "a", number: 1, marks: [] }], null);
    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 60, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 50, clientY: 60, button: 0 });
    expect(changed).not.toHaveBeenCalled();
  });
  it("selecting another change's mark activates that change, and undo stays with the mark's change", () => {
    const { canvas, changed } = marker([
      { id: "a", number: 1, marks: [] },
      { id: "b", number: 2, marks: [{ id: "b-pin", kind: "pin", points: [{ x: 0.8, y: 0.8 }] }] },
    ]);
    fireEvent.pointerDown(canvas, { clientX: 20, clientY: 30, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 20, clientY: 30, button: 0 });
    expect(changed.mock.lastCall![0]).toBe("a");
    fireEvent.click(screen.getByRole("button", { name: "Mark for change 2" }));
    fireEvent.pointerDown(canvas, { clientX: 100, clientY: 30, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: 100, clientY: 30, button: 0 });
    expect(changed.mock.lastCall![0]).toBe("b");
    expect(changed.mock.lastCall![1]).toHaveLength(2);
    fireEvent.keyDown(canvas, { key: "z", metaKey: true });
    expect(changed.mock.lastCall).toEqual(["b", [{ id: "b-pin", kind: "pin", points: [{ x: 0.8, y: 0.8 }] }]]);
    fireEvent.keyDown(canvas, { key: "z", metaKey: true });
    expect(changed.mock.lastCall).toEqual(["a", []]);
  });
  it("offers keyboard pin placement, movement, and removal", () => {
    const { canvas, changed } = marker([{ id: "a", number: 1, marks: [] }]);
    fireEvent.keyDown(canvas, { key: "Enter" });
    expect(changed.mock.lastCall![1][0].points).toEqual([{ x: 0.5, y: 0.5 }]);
    fireEvent.keyDown(canvas, { key: "ArrowRight", shiftKey: true });
    expect(changed.mock.lastCall![1][0].points).toEqual([{ x: 0.55, y: 0.5 }]);
    fireEvent.keyDown(canvas, { key: "Delete" });
    expect(changed.mock.lastCall![1]).toEqual([]);
  });
  it("keeps an edited note when geometry is undone", () => {
    const { canvas, changed } = marker([{ id: "a", number: 1, marks: [] }]);
    fireEvent.keyDown(canvas, { key: "Enter" });
    fireEvent.change(screen.getByLabelText("Note for mark 1 (optional)"), { target: { value: "Only the coat" } });
    fireEvent.keyDown(canvas, { key: "ArrowRight" });
    fireEvent.keyDown(canvas, { key: "z", metaKey: true });
    expect(changed.mock.lastCall![1][0]).toEqual(expect.objectContaining({ points: [{ x: 0.5, y: 0.5 }], note: "Only the coat" }));
  });
});
