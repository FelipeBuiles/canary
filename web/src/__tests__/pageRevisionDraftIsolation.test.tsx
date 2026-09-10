import { fireEvent, render, screen } from "@testing-library/react";
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
const previewState = vi.hoisted(() => ({ data: undefined as PageCorrectionPreview | undefined }));

vi.mock("../api/queries", () => ({
  useAdaptation: () => ({ data: { beats: [] }, isLoading: false, error: null }),
}));

vi.mock("../api/pageRevisions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/pageRevisions")>();
  return {
    ...actual,
    useCorrectionPreview: () => ({
      mutate: vi.fn((_vars: unknown, options?: { onSuccess?: () => void }) => options?.onSuccess?.()),
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
  return render(
    <QueryClientProvider client={new QueryClient()}>
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
          onDraftKeysChange={vi.fn()}
          onJobQueued={vi.fn()}
          {...overrides}
        />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  previewState.data = undefined;
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
    estimate: { estimate_credits: 10, reserved_credits: 10, reservation_multiplier: 1, confidence: "high" },
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

    // The stale-draft alert shows on the calm artwork view; requests stay closed.
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.queryByDisplayValue("Restore the approved face")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));

    // Fresh draft: the suggestion is present but carries no inherited marks.
    expect(screen.getAllByDisplayValue("Restore the approved face")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /copy wording/i }));

    // The copied wording arrives as a second, collapsed request: only the focused one stays editable.
    expect(screen.getAllByDisplayValue("Restore the approved face")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /edit request/i })).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();

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
    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));
    expect(screen.getByLabelText(/What would you like to change/)).toHaveProperty("value", "");
    expect(screen.queryByDisplayValue(pending)).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /include fix/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /copy wording/i }));

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
    expect(after.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("img", { name: "Complete page 1, current revision 2" }).getAttribute("src"))
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
    fireEvent.change(screen.getByPlaceholderText(/describe a fix in your own words/i), {
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
