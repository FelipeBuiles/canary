import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n";
import type { ComponentProps } from "react";
import {
  clearRevisionDraft,
  draftStorageKey,
  findStaleRevisionDraft,
  loadRevisionDraft,
  saveRevisionDraft,
  type DraftTarget,
  type PersistedRevisionDraft,
} from "../api/pageRevisions";
import { RevisionDraft } from "../components/pages/RevisionDraft";
import type { PageCorrectionPreview } from "../api/pages";
import type { PageIssue } from "../types/api";

// Controllable preview result: the component only shows the preview surface
// (and SELECT ALL OPEN) once the preview hash matches the draft body, so the
// mock mutate resolves onSuccess exactly like the real query would.
const previewState = vi.hoisted(() => ({
  data: undefined as PageCorrectionPreview | undefined,
  mutate: vi.fn(),
}));

// Saved renders for the page; empty unless a test lists revisions.
const pageState = vi.hoisted(() => ({
  renders: [] as { revision: number; comic_page_revision?: number }[],
  select: vi.fn(),
}));

vi.mock("../api/queries", () => ({
  useAdaptation: () => ({ data: { beats: [] }, isLoading: false, error: null }),
  useCompletePage: () => ({
    data: { renders: pageState.renders.map((item) => ({ render: {
      revision: item.revision,
      comic_page_revision: item.comic_page_revision ?? 2,
      comic_page_sha256: "a".repeat(64),
    } })) },
  }),
}));

vi.mock("../api/pages", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/pages")>()),
  selectPageRender: (...args: unknown[]) => pageState.select(...args),
}));

vi.mock("../api/pageRevisions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/pageRevisions")>();
  return {
    ...actual,
    useCorrectionPreview: () => ({
      mutate: previewState.mutate,
      isPending: false,
      data: previewState.data,
      error: null,
    }),
    useSubmitCorrections: () => ({ mutate: vi.fn(), isPending: false, error: null }),
    useRenderCorrection: () => ({ data: null, isLoading: false, error: null }),
  };
});

const PROJECT = "demo";
const PAGE = 1;
const SHA = "a".repeat(64);

function target(comicPageRevision: number, parentRenderRevision: number): DraftTarget {
  return { comicPageRevision, parentRenderRevision };
}

function storedDraft(overrides: Partial<PersistedRevisionDraft> = {}): PersistedRevisionDraft {
  return {
    project: PROJECT,
    pageNumber: PAGE,
    comicPageRevision: 2,
    parentRenderRevision: 1,
    comicPageSha256: SHA,
    changes: [],
    note: "",
    contextSourceUnitIds: [],
    updatedAt: new Date("2026-09-01T00:00:00.000Z").toISOString(),
    ...overrides,
  };
}
const FACE_ISSUE: PageIssue = {
  id: "issue-9",
  issue_type: "identity",
  classification: "editorial_issue",
  correction_kind: "render_fidelity",
  correction_owner: "draw",
  page_number: PAGE,
  render_revision: 1,
  evidence: ["Face differs from approved reference"],
  requested_correction: "Restore the approved face",
  status: "open",
  resolution_revision: null,
};

function renderDraft(overrides: Partial<ComponentProps<typeof RevisionDraft>> = {}) {
  const client = new QueryClient();
  const draft = (props: Partial<ComponentProps<typeof RevisionDraft>>) => (
    <QueryClientProvider client={client}>
      <I18nProvider>
        <RevisionDraft
          project={PROJECT}
          pageNumber={PAGE}
          comicPageRevision={2}
          parentRenderRevision={2}
          comicPageSha256={SHA}
          compareRevision={null}
          issues={[]}
          seeds={[]}
          onSeedsConsumed={vi.fn()}
         
          onJobQueued={vi.fn()}
          {...props}
        />
      </I18nProvider>
    </QueryClientProvider>
  );
  const result = render(draft(overrides));
  return {
    ...result,
    rerenderDraft: (props: Partial<ComponentProps<typeof RevisionDraft>>) => result.rerender(draft({ ...overrides, ...props })),
  };
}

beforeEach(() => {
  pageState.renders = [];
  pageState.select = vi.fn(() => Promise.resolve({ active_render_revision: 1 }));
  previewState.data = undefined;
  previewState.mutate.mockReset();
  previewState.mutate.mockImplementation((_vars: unknown, options?: { onSuccess?: () => void }) => options?.onSuccess?.());
});

function previewStub(overrides: Partial<PageCorrectionPreview> = {}): PageCorrectionPreview {
  return {
    selected_issue_ids: [],
    unselected_open_issue_ids: [],
    pending_manual_change_ids: [],
    changes: [],
    note: null,
    mode: "full",
    instruction: "compiled instruction",
    context: {
      adaptation_revision: 1,
      adaptation_sha256: "b".repeat(64),
      treatment_spine: [],
      beat_ids: [],
      beat_count: 0,
      appearance_chronology: [],
      continuity: [],
      source_unit_ids: [],
      selected_source_unit_ids: [],
      omitted_source_unit_ids: [],
      context_digest: "",
      truncated: false,
    },
    references: [],
    profile: { id: "p", provider: "test", model: "test" },
    lettering_count: 0,
    prompt_characters: 20,
    request_sha256: "c".repeat(64),
    warnings: [],
    estimate: { estimate_credits: 10, reserved_credits: 10, reservation_multiplier: 1, confidence: "low_variance" },
    ...overrides,
  };
}

describe("revision draft storage scoping", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("never loads a newer render from an older render's draft", () => {
    saveRevisionDraft(storedDraft({
      changes: [{
        id: "issue:issue-9",
        issue_id: "issue-9",
        instruction: "Restore the approved face",
        selected: true,
        annotations: [{ id: "m1", kind: "pin", points: [{ x: 0.2, y: 0.3 }], note: "glow spills past the panel" }],
      }],
      note: "overall guidance",
    }));

    expect(draftStorageKey(PROJECT, PAGE, target(2, 1))).not.toBe(
      draftStorageKey(PROJECT, PAGE, target(2, 2)),
    );
    // Same canonical revision, newer render: no automatic inheritance.
    expect(loadRevisionDraft(PROJECT, PAGE, target(2, 2))).toBeNull();
    // The original target still reads its own draft back intact.
    expect(loadRevisionDraft(PROJECT, PAGE, target(2, 1))?.changes).toHaveLength(1);
    expect(loadRevisionDraft(PROJECT, PAGE, target(2, 1))?.note).toBe("overall guidance");
  });

  it("offers the older draft for explicit rebase instead of migrating it", () => {
    saveRevisionDraft(storedDraft({
      changes: [{
        id: "issue:issue-9",
        issue_id: "issue-9",
        instruction: "Restore the approved face",
        selected: true,
        annotations: [{ id: "m1", kind: "pin", points: [{ x: 0.2, y: 0.3 }], note: "glow spills past the panel" }],
      }],
    }));

    const stale = findStaleRevisionDraft(PROJECT, PAGE, target(2, 2));
    expect(stale?.parentRenderRevision).toBe(1);
    // Wording stays available for an explicit copy; geometry is never moved over.
    expect(stale?.changes).toHaveLength(1);
    expect(stale?.changes[0]?.annotations).toHaveLength(1);
    expect(loadRevisionDraft(PROJECT, PAGE, target(2, 2))).toBeNull();
  });

  it("never offers suggestions alone, or a sent draft a newer render replaced", () => {
    saveRevisionDraft(storedDraft({
      changes: [{ id: "issue:issue-9", issue_id: "issue-9", instruction: "Restore the approved face", selected: true, annotations: [] }],
    }));
    expect(findStaleRevisionDraft(PROJECT, PAGE, target(2, 2))).toBeNull();
    saveRevisionDraft(storedDraft({ submittedJobId: "job-1", pendingRequest: "", note: "sent with the job" }));
    expect(findStaleRevisionDraft(PROJECT, PAGE, target(2, 2))).toBeNull();
    // Both were cleaned up rather than kept around.
    expect(loadRevisionDraft(PROJECT, PAGE, target(2, 1))).toBeNull();
  });

  it("discarding removes the earlier draft for good", () => {
    saveRevisionDraft(storedDraft({ pendingRequest: "Make the sky darker" }));
    const first = renderDraft({ parentRenderRevision: 2 });
    fireEvent.click(screen.getByRole("button", { name: "DISCARD" }));
    first.unmount();
    renderDraft({ parentRenderRevision: 2 });
    expect(screen.queryByText("You have unsent changes from an earlier version of this page.")).toBeNull();
  });

  it("clears only the targeted draft", () => {
    saveRevisionDraft(storedDraft({ note: "old render note" }));
    saveRevisionDraft(storedDraft({ parentRenderRevision: 2, note: "new render note" }));

    clearRevisionDraft(PROJECT, PAGE, target(2, 1));

    expect(loadRevisionDraft(PROJECT, PAGE, target(2, 1))).toBeNull();
    expect(loadRevisionDraft(PROJECT, PAGE, target(2, 2))?.note).toBe("new render note");
  });
});

describe("RevisionDraft across render targets", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it.each(["dismissed", "accepted", "resolved", "removed"] as const)(
    "excludes a %s finding when fixing another issue after the checks refresh",
    (status) => {
      const glowIssue: PageIssue = { ...FACE_ISSUE, id: "issue-10", requested_correction: "Fix the background glow" };
      const { rerenderDraft } = renderDraft({ issues: [FACE_ISSUE, glowIssue] });

      // The checks update while the draft remains mounted beside the artwork.
      const issues = status === "removed" ? [glowIssue] : [{ ...FACE_ISSUE, status }, glowIssue];
      rerenderDraft({ issues });
      rerenderDraft({ issues, seeds: [{ key: "issue:issue-10", issueId: glowIssue.id, instruction: glowIssue.requested_correction }] });

      expect(screen.queryByRole("checkbox", { name: /restore the approved face/i })).toBeNull();
      expect(screen.getByRole("checkbox", { name: /background glow/i })).toHaveProperty("checked", true);
      fireEvent.click(screen.getByRole("button", { name: /review changes/i }));
      expect(previewState.mutate.mock.calls[0][0].body.changes).toEqual([
        { id: "issue:issue-10", issue_id: glowIssue.id, instruction: glowIssue.requested_correction, annotations: [] },
      ]);
    },
  );

  it("cleans dismissed findings from a saved draft while preserving active edits and manual requests", () => {
    const glowIssue: PageIssue = { ...FACE_ISSUE, id: "issue-10", requested_correction: "Fix the background glow" };
    const annotations = [{ id: "m1", kind: "pin" as const, points: [{ x: 0.2, y: 0.3 }], note: "Keep this lighting" }];
    saveRevisionDraft(storedDraft({
      parentRenderRevision: 2,
      changes: [
        { id: "issue:issue-9", issue_id: FACE_ISSUE.id, instruction: FACE_ISSUE.requested_correction, selected: true, annotations: [] },
        { id: "issue:issue-10", issue_id: glowIssue.id, instruction: "Dim the glow without changing the cape", selected: false, annotations },
        { id: "manual-1", instruction: "Keep the hands visible", selected: true, annotations: [] },
      ],
      note: "Keep the scene warm",
      pendingRequest: "Keep the framing",
    }));
    renderDraft({
      issues: [{ ...FACE_ISSUE, status: "dismissed" }, glowIssue],
      // A stale seed must not restore the dismissed issue either.
      seeds: [{ key: "issue:issue-9", issueId: FACE_ISSUE.id, instruction: FACE_ISSUE.requested_correction }],
    });

    expect(screen.queryByRole("checkbox", { name: /restore the approved face/i })).toBeNull();
    expect(screen.getByRole("checkbox", { name: /dim the glow/i })).toHaveProperty("checked", false);
    expect(screen.getByRole("checkbox", { name: /hands visible/i })).toHaveProperty("checked", true);
    const saved = loadRevisionDraft(PROJECT, PAGE, target(2, 2));
    expect(saved?.changes).toEqual([
      { id: "issue:issue-10", issue_id: glowIssue.id, instruction: "Dim the glow without changing the cape", selected: false, annotations },
      { id: "manual-1", instruction: "Keep the hands visible", selected: true, annotations: [] },
    ]);
    expect(saved?.note).toBe("Keep the scene warm");
    expect(saved?.pendingRequest).toBe("Keep the framing");
  });

  it("starts the newer render empty and copies wording only on request", () => {
    saveRevisionDraft(storedDraft({
      changes: [{
        id: "issue:issue-9",
        issue_id: "issue-9",
        instruction: "Restore the approved face",
        selected: true,
        annotations: [{ id: "m1", kind: "pin", points: [{ x: 0.2, y: 0.3 }], note: "glow spills past the panel" }],
      }],
      note: "overall guidance",
    }));

    const { container } = renderDraft({ issues: [FACE_ISSUE] });

    // The earlier-draft notice shows beside the artwork; requests stay closed.
    expect(screen.getByText("You have unsent changes from an earlier version of this page.")).toBeTruthy();
    expect(screen.queryByDisplayValue("Restore the approved face")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));

    // Fresh draft: the suggestion is present but carries no inherited marks.
    expect(screen.getAllByDisplayValue("Restore the approved face")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /use on this version/i }));

    // The copied wording arrives as a second, collapsed request: only the focused one stays editable.
    expect(screen.getAllByDisplayValue("Restore the approved face")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /edit request/i })).toHaveLength(1);
    expect(screen.queryByText("You have unsent changes from an earlier version of this page.")).toBeNull();
    // Used once, the earlier draft is gone for good.
    expect(findStaleRevisionDraft(PROJECT, PAGE, target(2, 2))).toBeNull();

    // Expanding the copy shows the retained wording with no marks, excluded by default.
    fireEvent.click(screen.getByRole("button", { name: /edit request/i }));
    expect(screen.getByDisplayValue("Restore the approved face")).toBeTruthy();
    const boxes = screen.getAllByRole("checkbox", { name: /include fix/i });
    expect(boxes).toHaveLength(2);
    expect((boxes[0] as HTMLInputElement).checked).toBe(true);
    expect((boxes[1] as HTMLInputElement).checked).toBe(false);
    expect(container.querySelectorAll('[id^="mark-note-"]')).toHaveLength(0);
    expect(screen.queryByDisplayValue("glow spills past the panel")).toBeNull();

    // The overall guidance carries over behind its optional-note disclosure.
    fireEvent.click(container.querySelector("details summary")!);
    expect(screen.getByDisplayValue("overall guidance")).toBeTruthy();
  });

  it("restores pending wording only for the same render and copies it unselected on request", () => {
    const pending = "Keep the hands in view without changing the face";
    const first = renderDraft({ parentRenderRevision: 1 });
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));
    fireEvent.change(screen.getByLabelText(/What would you like to change/), {
      target: { value: pending },
    });
    first.unmount();

    const reopened = renderDraft({ parentRenderRevision: 1 });
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));
    expect(screen.getByLabelText(/What would you like to change/)).toHaveProperty("value", pending);
    reopened.unmount();

    const next = renderDraft({ parentRenderRevision: 2 });
    expect(screen.getByText(pending, { selector: "li" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));
    expect(screen.getByLabelText(/What would you like to change/)).toHaveProperty("value", "");
    expect(screen.queryByDisplayValue(pending)).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /include fix/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /use on this version/i }));

    expect(screen.getByRole("checkbox", { name: `Include fix: ${pending}` })).toHaveProperty("checked", false);
    const copied = loadRevisionDraft(PROJECT, PAGE, target(2, 2));
    expect(copied?.changes).toHaveLength(1);
    expect(copied?.changes[0]?.instruction).toBe(pending);
    expect(copied?.changes[0]?.selected).toBe(false);
    expect(copied?.changes[0]?.annotations).toHaveLength(0);
    expect(next.container.querySelectorAll('[id^="mark-note-"]')).toHaveLength(0);
  });

  it("lets the author compare real revisions without changing the correction draft", () => {
    renderDraft({ parentRenderRevision: 2, compareRevision: 1, issues: [FACE_ISSUE] });
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));
    fireEvent.change(screen.getByDisplayValue("Restore the approved face"), {
      target: { value: "Restore the approved face without changing the cape" },
    });
    fireEvent.click(screen.getByText(/compare with previous render/i));

    const after = screen.getByRole("button", { name: /after.*revision 2/i });
    const before = screen.getByRole("button", { name: /before.*revision 1/i });
    // The wipe opens first and overlays both real revisions.
    expect(screen.getByRole("button", { name: "WIPE" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(screen.getByTestId("revision-wipe")).getByRole("img", { name: "Complete page 1, previous revision 1" }).getAttribute("src"))
      .toContain("/renders/1/");
    expect(within(screen.getByTestId("revision-wipe")).getByRole("img", { name: "Complete page 1, current revision 2" }).getAttribute("src"))
      .toContain("/renders/2/");

    fireEvent.click(before);
    expect(before.getAttribute("aria-pressed")).toBe("true");
    expect(after.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("img", { name: "Complete page 1, previous revision 1" }).getAttribute("src"))
      .toContain("/renders/1/");
    expect(screen.getByDisplayValue("Restore the approved face without changing the cape")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: /include fix/i })).toHaveProperty("checked", true);

    fireEvent.click(after);
    expect(after.getAttribute("aria-pressed")).toBe("true");
    expect(before.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("img", { name: "Complete page 1, current revision 2" }).getAttribute("src"))
      .toContain("/renders/2/");
    expect(screen.getByDisplayValue("Restore the approved face without changing the cape")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: /include fix/i })).toHaveProperty("checked", true);
  });

  it("steps through every saved version and selects the viewed one", async () => {
    pageState.renders = [{ revision: 1 }, { revision: 2 }, { revision: 3 }];
    renderDraft({ parentRenderRevision: 3, compareRevision: 2 });
    const canvas = () => screen.getAllByRole("img", { name: /complete page 1, render revision/i })[0];
    expect(canvas().getAttribute("src")).toContain("/renders/3/");
    expect(screen.queryByRole("button", { name: /use this version/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Previous version" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous version" }));
    expect(canvas().getAttribute("src")).toContain("/renders/1/");
    expect(screen.getByText("1 / 3")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Previous version" })).toHaveProperty("disabled", true);

    fireEvent.click(screen.getByRole("button", { name: /use this version/i }));
    await vi.waitFor(() => expect(pageState.select).toHaveBeenCalledWith(PROJECT, PAGE, 1, 3));

    fireEvent.click(screen.getByRole("button", { name: /back to selected/i }));
    expect(canvas().getAttribute("src")).toContain("/renders/3/");
  });

  it("never selects a version drawn from an earlier page plan", () => {
    pageState.renders = [{ revision: 1, comic_page_revision: 1 }, { revision: 2 }];
    renderDraft({ parentRenderRevision: 2 });
    fireEvent.change(screen.getByLabelText("Version"), { target: { value: "1" } });
    expect(screen.getByRole("button", { name: /use this version/i })).toHaveProperty("disabled", true);
    expect(screen.getByText("This version belongs to an earlier page plan.")).toBeTruthy();
  });

  it("compares the shown version with any other saved version", () => {
    pageState.renders = [{ revision: 1 }, { revision: 2 }, { revision: 3 }];
    renderDraft({ parentRenderRevision: 3, compareRevision: 2 });
    fireEvent.click(screen.getByText(/compare with previous render/i));
    expect(screen.getByRole("button", { name: /before.*revision 2/i })).toBeTruthy();

    fireEvent.change(screen.getByRole("combobox", { name: /compare with/i }), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: /before.*revision 1/i }));
    expect(screen.getByRole("img", { name: "Complete page 1, previous revision 1" }).getAttribute("src"))
      .toContain("/renders/1/");
  });

  it("drafts changes on the selected version even after browsing another", () => {
    pageState.renders = [{ revision: 1 }, { revision: 2 }];
    renderDraft({ parentRenderRevision: 2 });
    fireEvent.click(screen.getByRole("button", { name: "Previous version" }));
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));
    expect(screen.queryByRole("button", { name: /use this version/i })).toBeNull();
    expect(screen.getAllByRole("img", { name: /render revision 2/i }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("img", { name: /render revision 1/i })).toBeNull();
  });

  it("offers only findings the selected render can link and sends the rest as new requests", async () => {
    const laterIssue: PageIssue = { ...FACE_ISSUE, id: "issue-later", render_revision: 2, requested_correction: "Close the upper eye" };
    renderDraft({
      parentRenderRevision: 1,
      issues: [FACE_ISSUE, laterIssue],
      correctableIssueIds: [FACE_ISSUE.id],
      // Fix pressed on a finding from render 2 after reselecting render 1.
      seeds: [{ key: "issue:issue-later", issueId: laterIssue.id, instruction: laterIssue.requested_correction }],
    });
    expect(screen.getByRole("checkbox", { name: /restore the approved face/i })).toHaveProperty("checked", true);
    expect(screen.getByRole("checkbox", { name: /close the upper eye/i })).toHaveProperty("checked", true);

    fireEvent.click(screen.getByRole("button", { name: /review changes/i }));
    await vi.waitFor(() => expect(previewState.mutate).toHaveBeenCalled());
    const changes = previewState.mutate.mock.calls[0][0].body.changes;
    expect(changes.find((change: { instruction: string }) => change.instruction === "Close the upper eye").issue_id).toBeUndefined();
    expect(changes.find((change: { instruction: string }) => change.instruction === "Restore the approved face").issue_id).toBe(FACE_ISSUE.id);
  });

  it("keeps an edited fix for a later render's finding as a new request after reselecting", () => {
    const laterIssue: PageIssue = { ...FACE_ISSUE, id: "issue-later", render_revision: 2, requested_correction: "Close the upper eye" };
    saveRevisionDraft(storedDraft({
      parentRenderRevision: 1,
      changes: [
        { id: "issue:issue-later", issue_id: laterIssue.id, instruction: "Close the upper eye fully", selected: true, annotations: [] },
        { id: "issue:untouched", issue_id: "issue-untouched", instruction: "Dim the lamp", selected: true, annotations: [] },
      ],
    }));
    renderDraft({
      parentRenderRevision: 1,
      issues: [laterIssue, { ...laterIssue, id: "issue-untouched", requested_correction: "Dim the lamp" }],
      correctableIssueIds: [],
    });
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));
    expect(screen.getByDisplayValue("Close the upper eye fully")).toBeTruthy();
    expect(screen.queryByDisplayValue("Dim the lamp")).toBeNull();
    expect(loadRevisionDraft(PROJECT, PAGE, target(2, 1))?.changes).toEqual([
      { id: "issue:issue-later", instruction: "Close the upper eye fully", selected: true, annotations: [] },
    ]);
  });

  it("select all open reselects kept fixes and adds missing suggestions", () => {
    const glowIssue: PageIssue = { ...FACE_ISSUE, id: "issue-10", requested_correction: "Fix the background glow" };
    saveRevisionDraft(storedDraft({
      parentRenderRevision: 2,
      changes: [{
        id: "issue:issue-9",
        issue_id: "issue-9",
        instruction: "Restore the approved face",
        selected: true,
        annotations: [{ id: "m1", kind: "pin", points: [{ x: 0.2, y: 0.3 }], note: "glow spills past the panel" }],
      }],
    }));
    previewState.data = previewStub({ unselected_open_issue_ids: ["issue-9", "issue-10"] });

    renderDraft({ parentRenderRevision: 2, issues: [FACE_ISSUE, glowIssue] });
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));

    // A manual request keeps the draft previewable after the kept fix is deselected.
    fireEvent.change(screen.getByLabelText(/what would you like to change/i), {
      target: { value: "Check the cape edge" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add request/i }));
    const faceBox = screen.getByRole("checkbox", { name: /include fix: restore the approved face/i });
    fireEvent.click(faceBox);
    expect((faceBox as HTMLInputElement).checked).toBe(false);

    // Explicit preview makes the left-out findings actionable.
    fireEvent.click(screen.getByRole("button", { name: /review changes/i }));
    fireEvent.click(screen.getByRole("button", { name: /select all open/i }));

    // Every fix ends up selected; the missing suggestion joins the draft.
    const boxes = screen.getAllByRole("checkbox", { name: /include fix/i });
    expect(boxes).toHaveLength(3);
    for (const box of boxes) expect((box as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("button", { name: /edit request.*background glow/i })).toBeTruthy();

    // The kept fix is reselected with its edited wording and marks intact.
    const stored = loadRevisionDraft(PROJECT, PAGE, target(2, 2));
    const face = stored?.changes.find((change) => change.issue_id === "issue-9");
    expect(face?.selected).toBe(true);
    expect(face?.instruction).toBe("Restore the approved face");
    expect(face?.annotations).toHaveLength(1);
    const glow = stored?.changes.find((change) => change.issue_id === "issue-10");
    expect(glow?.selected).toBe(true);
    expect(glow?.instruction).toBe("Fix the background glow");
  });
});
