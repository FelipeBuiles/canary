import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

afterEach(() => sessionStorage.clear());

const updateBrief = vi.fn();
const approveBrief = vi.fn();
const storyDecision = {
  story_bible: {
    title: "The Last Incantation",
    author: "H. P. Lovecraft",
    total_scenes: 1,
    characters: [{ id: "char_1", name: "Elena", visual_anchor: "Silver-streaked dark hair" }],
    locations: [{ id: "loc_1", name: "The Archive", visual_anchor: "Salt-stained stone stacks" }],
    scenes: [{ id: "scene_1", chapter: 1, title: "The Locked Shelf", character_ids: ["char_1"], location_id: "loc_1", summary: "Elena finds the forbidden ledger." }],
    narrative_arcs: [],
    style_notes: null,
    props: [],
  },
  brief: {
    revision: 3,
    content_sha256: "a".repeat(64),
    status: "draft",
    story_promises: ["The investigation closes its causal loop"],
    themes: ["Forbidden knowledge"],
    point_of_view: "Close third person",
    narrator_treatment: "Sparse captions",
    tone: "Mounting dread",
    ambiguities: [],
    motifs: ["Salt air"],
    protected_language: [],
    essential_events: ["The final discovery"],
    character_turns: ["Defiance becomes terror"],
    transformation_level: "medium_specific",
    desired_emphasis: ["The aftermath"],
    target_page_min: 22,
    target_page_max: 28,
  },
};
const runPipeline = vi.fn();

let storyState: { data: typeof storyDecision | null; isLoading: boolean; error: Error | null } = {
  data: storyDecision,
  isLoading: false,
  error: null,
};

let projectStages: Record<string, Record<string, unknown>> = {
  extract: { status: "complete" },
  brief: { status: "awaiting_review" },
};

vi.mock("../api/queries", () => ({
  useStory: () => storyState,
  useProjectStatus: () => ({
    data: {
      stages: projectStages,
    },
  }),
  useUpdateBrief: () => ({ mutate: updateBrief, isPending: false }),
  useApproveStage: () => ({ mutate: approveBrief, isPending: false }),
  useRunPipeline: () => ({ mutate: runPipeline, isPending: false }),
  useCreditBalance: () => ({ data: undefined }),
  useStageEstimate: () => ({ data: undefined }),
}));

// The shared Story Bible editor has its own tests; here no Bible editor loads.
vi.mock("../api/seriesQueries", () => ({
  useStoryBibleEditor: () => ({ data: undefined, error: null, isLoading: false }),
  useRemoveEntity: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useRestoreExcluded: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));

import { StoryRoom } from "../pages/rooms/StoryRoom";

function renderRoom() {
  const view = render(<StoryRoom />, {
    wrapper: ({ children }) => (
      <MemoryRouter initialEntries={["/project/demo/story"]}>
        <I18nProvider>
          <Routes>
            <Route path="/project/:id/story" element={children} />
          </Routes>
        </I18nProvider>
      </MemoryRouter>
    ),
  });
  return { rerender: () => view.rerender(<StoryRoom />) };
}

function editStoryPromises() {
  fireEvent.click(screen.getByRole("button", { name: "Edit STORY PROMISES" }));
  return screen.getByLabelText("STORY PROMISES") as HTMLTextAreaElement;
}

describe("StoryRoom", () => {
  beforeEach(() => {
    sessionStorage.clear();
    updateBrief.mockReset();
    approveBrief.mockReset();
    runPipeline.mockReset();
    storyState = { data: storyDecision, isLoading: false, error: null };
    projectStages = {
      extract: { status: "complete" },
      brief: { status: "awaiting_review" },
    };
  });

  it("reviews the Story Bible and adaptation Brief together", () => {
    renderRoom();

    expect(screen.getByRole("heading", { name: "CONFIRM THE STORY & BRIEF" })).toBeTruthy();
    expect(screen.getByText("The Last Incantation")).toBeTruthy();
    expect(screen.getByText("The investigation closes its causal loop")).toBeTruthy();
    // Essential events are ordered requirements; the other lists are not.
    expect(screen.getByText("The final discovery").closest("ol")).toBeTruthy();
    expect(screen.getByText("The investigation closes its causal loop").closest("ul")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Inside your story" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Scenes\s*1$/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Elena finds the forbidden ledger.")).toBeTruthy();
    expect(screen.getByText("Elena")).toBeTruthy();
    expect(screen.getByText("The Archive")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Characters\s*1$/ }));
    expect(screen.getByText("Silver-streaked dark hair.")).toBeTruthy();
    expect(screen.queryByText("Elena finds the forbidden ledger.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Places\s*1$/ }));
    expect(screen.getByText("Salt-stained stone stacks.")).toBeTruthy();
    expect(screen.queryByText("a".repeat(64))).toBeNull();
  });

  it("opens a focused editor, previews the changes, and saves them explicitly", () => {
    renderRoom();
    expect(screen.queryByRole("textbox", { name: "STORY PROMISES" })).toBeNull();
    const promises = editStoryPromises();
    expect(document.activeElement).toBe(promises);
    fireEvent.change(promises, { target: { value: "A new promise\nA second promise" } });
    fireEvent.click(screen.getByRole("button", { name: "Done editing STORY PROMISES" }));
    expect(screen.queryByRole("textbox", { name: "STORY PROMISES" })).toBeNull();
    expect(screen.getByText("A new promise")).toBeTruthy();
    expect(screen.getByText("A second promise")).toBeTruthy();
    expect(updateBrief).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "SAVE BRIEF" }));
    expect(updateBrief).toHaveBeenCalledWith({
      project: "demo",
      expectedRevision: 3,
      changes: expect.objectContaining({ story_promises: ["A new promise", "A second promise"] }),
    }, expect.any(Object));
  });

  it("returns focus to Edit on Escape and keeps the visible draft", () => {
    renderRoom();
    const promises = editStoryPromises();
    fireEvent.change(promises, { target: { value: "Keep this draft" } });
    fireEvent.keyDown(promises, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "STORY PROMISES" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Edit STORY PROMISES" }));
    expect(screen.getByText("Keep this draft")).toBeTruthy();
    expect(editStoryPromises().value).toBe("Keep this draft");
    expect(updateBrief).not.toHaveBeenCalled();
  });

  it("saves an edited target page range against the current Brief revision", () => {
    renderRoom();

    fireEvent.change(screen.getByLabelText("Page target: from"), { target: { value: "24" } });
    fireEvent.change(screen.getByLabelText("Page target: to"), { target: { value: "32" } });
    fireEvent.click(screen.getByRole("button", { name: "SAVE BRIEF" }));

    expect(updateBrief).toHaveBeenCalledWith({
      project: "demo",
      expectedRevision: 3,
      changes: expect.objectContaining({
        target_page_min: 24,
        target_page_max: 32,
      }),
    }, expect.any(Object));
  });

  it("approves Brief rather than Extract", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "APPROVE BRIEF — CONTINUE" }));

    expect(approveBrief).toHaveBeenCalledWith(
      { project: "demo", stage: "brief" },
      expect.any(Object),
    );
  });

  it("keeps blank lines while editing and saves the visible draft before approval", () => {
    renderRoom();
    const promises = editStoryPromises();
    fireEvent.change(promises, { target: { value: "A promise\n\nA second promise\n" } });
    expect(promises.value).toBe("A promise\n\nA second promise\n");
    fireEvent.click(screen.getByRole("button", { name: "SAVE & APPROVE BRIEF — CONTINUE" }));
    expect(approveBrief).not.toHaveBeenCalled();
    expect(updateBrief.mock.calls[0][0].changes.story_promises).toEqual(["A promise", "A second promise"]);
    act(() => updateBrief.mock.calls[0][1].onSuccess({
      ...storyDecision.brief, revision: 4, story_promises: ["A promise", "A second promise"],
    }));
    expect(approveBrief).toHaveBeenCalledWith({ project: "demo", stage: "brief" }, expect.any(Object));
  });

  it("preserves an edited draft after a failed save and never approves it", () => {
    renderRoom();
    fireEvent.change(editStoryPromises(), { target: { value: "Do not lose this\n" } });
    fireEvent.click(screen.getByRole("button", { name: "SAVE & APPROVE BRIEF — CONTINUE" }));
    act(() => updateBrief.mock.calls[0][1].onError(new Error("Revision conflict")));
    expect(screen.getByRole("alert").textContent).toContain("Revision conflict");
    expect((screen.getByLabelText("STORY PROMISES") as HTMLTextAreaElement).value).toBe("Do not lose this\n");
    expect(approveBrief).not.toHaveBeenCalled();
    cleanup();
    renderRoom();
    expect(screen.getByText("Restored unsaved draft")).toBeTruthy();
    expect(editStoryPromises().value).toBe("Do not lose this\n");
  });

  it("adopts the fresh approval revision after opening a cached brief and saves subsequent edits against it", () => {
    projectStages.brief = { status: "complete" };
    const view = renderRoom();
    storyState = { ...storyState, data: { ...storyDecision, brief: {
      ...storyDecision.brief, revision: 4, status: "approved",
    } } };
    view.rerender();

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Brief approved")).toBeTruthy();
    fireEvent.change(editStoryPromises(), { target: { value: "A promise after approval" } });
    fireEvent.click(screen.getByRole("button", { name: "SAVE BRIEF" }));
    expect(updateBrief).toHaveBeenCalledWith({
      project: "demo", expectedRevision: 4,
      changes: { story_promises: ["A promise after approval"] },
    }, expect.any(Object));
  });

  it("adopts changed server content after a reverted edit without saving the obsolete no-op field", () => {
    const view = renderRoom();
    const promises = editStoryPromises();
    fireEvent.change(promises, { target: { value: "A temporary promise" } });
    fireEvent.change(promises, { target: { value: storyDecision.brief.story_promises[0] } });
    storyState = { ...storyState, data: { ...storyDecision, brief: {
      ...storyDecision.brief, content_sha256: "b".repeat(64), story_promises: ["The server's new promise"],
    } } };
    view.rerender();

    expect(screen.queryByRole("alert")).toBeNull();
    expect((screen.getByLabelText("STORY PROMISES") as HTMLTextAreaElement).value).toBe("The server's new promise");
    expect((screen.getByRole("button", { name: "SAVE BRIEF" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Page target: to"), { target: { value: "32" } });
    fireEvent.click(screen.getByRole("button", { name: "SAVE BRIEF" }));
    expect(updateBrief).toHaveBeenCalledWith({
      project: "demo", expectedRevision: 3, changes: { target_page_max: 32 },
    }, expect.any(Object));
  });

  it("preserves a dirty draft across refetch while blocking save and approval", () => {
    const view = renderRoom();
    const rawDraft = "Keep my ending\n\nAnd this detail\n";
    fireEvent.change(editStoryPromises(), { target: { value: rawDraft } });
    storyState = { ...storyState, data: { ...storyDecision, brief: {
      ...storyDecision.brief, revision: 4, content_sha256: "b".repeat(64), story_promises: ["A different server ending"],
    } } };
    view.rerender();

    expect(screen.getByRole("alert").textContent).toContain("This brief changed elsewhere");
    expect((screen.getByLabelText("STORY PROMISES") as HTMLTextAreaElement).value).toBe(rawDraft);
    const save = screen.getByRole("button", { name: "SAVE BRIEF" }) as HTMLButtonElement;
    const approve = screen.getByRole("button", { name: "SAVE & APPROVE BRIEF — CONTINUE" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(approve.disabled).toBe(true);
    fireEvent.click(save);
    fireEvent.click(approve);
    expect(updateBrief).not.toHaveBeenCalled();
    expect(approveBrief).not.toHaveBeenCalled();

    cleanup();
    renderRoom();
    expect(editStoryPromises().value).toBe("A different server ending");
    fireEvent.click(screen.getByText("Unsaved draft from revision 3"));
    expect((screen.getByLabelText("Unsaved draft from revision 3") as HTMLTextAreaElement).value).toContain(rawDraft);
  });

  it("does not roll a successful save back to an older cached brief", () => {
    const view = renderRoom();
    fireEvent.change(editStoryPromises(), { target: { value: "The saved promise" } });
    fireEvent.click(screen.getByRole("button", { name: "SAVE BRIEF" }));
    const saved = {
      ...storyDecision.brief, revision: 4, content_sha256: "b".repeat(64), story_promises: ["The saved promise"],
    };
    act(() => updateBrief.mock.calls[0][1].onSuccess(saved));
    storyState = { ...storyState, data: { ...storyDecision, brief: saved } };
    view.rerender();
    storyState = { ...storyState, data: storyDecision };
    view.rerender();

    expect(screen.queryByRole("alert")).toBeNull();
    expect((screen.getByLabelText("STORY PROMISES") as HTMLTextAreaElement).value).toBe("The saved promise");
    fireEvent.change(screen.getByLabelText("Page target: to"), { target: { value: "32" } });
    fireEvent.click(screen.getByRole("button", { name: "SAVE BRIEF" }));
    expect(updateBrief).toHaveBeenLastCalledWith({
      project: "demo", expectedRevision: 4, changes: { target_page_max: 32 },
    }, expect.any(Object));
  });

  it("keeps a prior revision's raw draft accessible after reload without applying it to the newer brief", () => {
    renderRoom();
    fireEvent.change(editStoryPromises(), { target: { value: "Old revision draft\n\nKeep this ending\n" } });
    cleanup();
    storyState = { ...storyState, data: { ...storyDecision, brief: { ...storyDecision.brief, revision: 4 } } };
    renderRoom();
    expect(editStoryPromises().value).toBe(storyDecision.brief.story_promises[0]);
    expect(screen.queryByText("Restored unsaved draft")).toBeNull();
    fireEvent.click(screen.getByText("Unsaved draft from revision 3"));
    const preserved = screen.getByLabelText("Unsaved draft from revision 3") as HTMLTextAreaElement;
    expect(preserved.value).toContain("Old revision draft\n\nKeep this ending\n");
    expect(preserved.readOnly).toBe(true);
    expect(screen.getByRole("button", { name: "Copy draft" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Discard draft" })).toBeTruthy();
    expect(updateBrief).not.toHaveBeenCalled();
    cleanup();
    renderRoom();
    fireEvent.click(screen.getByText("Unsaved draft from revision 3"));
    expect((screen.getByLabelText("Unsaved draft from revision 3") as HTMLTextAreaElement).value).toContain("Old revision draft\n\nKeep this ending\n");
  });
});

describe("StoryRoom stage fallback precedence", () => {
  beforeEach(() => {
    runPipeline.mockReset();
    storyState = { data: null, isLoading: false, error: null };
    projectStages = { extract: { status: "complete" } };
  });

  function renderStoryAt(initialEntry: string) {
    render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <I18nProvider>
          <Routes>
            <Route path="/project/:id/story" element={<StoryRoom />} />
            <Route path="/story" element={<StoryRoom />} />
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    );
  }

  it("shows an actionable load error when the route has no project id", () => {
    renderStoryAt("/story");

    expect(screen.getByText("COULD NOT LOAD")).toBeTruthy();
    expect(screen.getByText("Project id is missing from the route.")).toBeTruthy();
    expect(screen.queryByText("PROOF UNAVAILABLE")).toBeNull();
  });

  it("shows the failed stage error and technical details instead of a missing-brief failure", () => {
    projectStages = {
      extract: { status: "complete" },
      brief: { status: "failed", error: "Brief run failed", error_detail: "traceback: boom" },
    };
    renderStoryAt("/project/demo/story");

    expect(screen.getByRole("heading", { name: "Preparing your story brief" })).toBeTruthy();
    expect(screen.getByText("Brief run failed")).toBeTruthy();
    expect(screen.getByText("Technical details").closest("details")?.open).toBe(false);
    expect(screen.getByText("traceback: boom")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry stage" })).toBeTruthy();
    expect(screen.queryByText("PROOF UNAVAILABLE")).toBeNull();
    expect(screen.queryByText("ERROR DETAILS")).toBeNull();
  });

  it("keeps a running stage visible while its artifact is still missing", () => {
    projectStages = {
      extract: { status: "complete" },
      brief: { status: "running" },
    };
    renderStoryAt("/project/demo/story");

    expect(screen.getByText("RUNNING")).toBeTruthy();
    expect(screen.queryByText("COULD NOT LOAD")).toBeNull();
    expect(screen.queryByText("PROOF UNAVAILABLE")).toBeNull();
  });

  it("shows an actionable load error when a ready stage has no artifact", () => {
    projectStages = {
      extract: { status: "complete" },
      brief: { status: "complete" },
    };
    renderStoryAt("/project/demo/story");

    expect(screen.getByText("COULD NOT LOAD")).toBeTruthy();
    expect(
      screen.getByText("The development server reported this stage ready, but its data was missing from the response."),
    ).toBeTruthy();
    expect(screen.queryByText("PROOF UNAVAILABLE")).toBeNull();
    expect(screen.queryByText("AWAITING REVIEW")).toBeNull();
  });

});
