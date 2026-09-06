import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const updateBrief = vi.fn();
const approveBrief = vi.fn();
const storyDecision = {
  story_bible: {
    title: "The Last Incantation",
    author: "H. P. Lovecraft",
    total_scenes: 1,
    characters: [{ id: "char_1", name: "Elena", visual_anchor: "Silver-streaked dark hair" }],
    locations: [{ id: "loc_1", name: "The Archive", visual_anchor: "Salt-stained stone stacks" }],
    scenes: [{ id: "scene_1", chapter: 1, title: "The Locked Shelf", summary: "Elena finds the forbidden ledger." }],
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

import { StoryRoom } from "../pages/rooms/StoryRoom";

function renderRoom() {
  render(
    <MemoryRouter initialEntries={["/project/demo/story"]}>
      <I18nProvider>
        <Routes>
          <Route path="/project/:id/story" element={<StoryRoom />} />
        </Routes>
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("StoryRoom", () => {
  beforeEach(() => {
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
    expect(screen.getByRole("heading", { name: "CHARACTERS & PLACES" })).toBeTruthy();
    expect(screen.getByText("Silver-streaked dark hair")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "STORY ORDER" })).toBeTruthy();
    expect(screen.getByText("Elena finds the forbidden ledger.")).toBeTruthy();
    expect(screen.queryByText("a".repeat(64))).toBeNull();
  });

  it("saves an edited target page range against the current Brief revision", () => {
    renderRoom();

    fireEvent.change(screen.getByLabelText("Minimum pages"), { target: { value: "24" } });
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "32" } });
    fireEvent.click(screen.getByRole("button", { name: "SAVE BRIEF" }));

    expect(updateBrief).toHaveBeenCalledWith({
      project: "demo",
      expectedRevision: 3,
      changes: expect.objectContaining({
        target_page_min: 24,
        target_page_max: 32,
      }),
    });
  });

  it("approves Brief rather than Extract", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "APPROVE BRIEF — CONTINUE" }));

    expect(approveBrief).toHaveBeenCalledWith(
      { project: "demo", stage: "brief" },
      expect.any(Object),
    );
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

    expect(screen.getByText("PRESS STOPPED")).toBeTruthy();
    expect(screen.getByText("Brief run failed")).toBeTruthy();
    expect(screen.getByText("TECHNICAL DETAILS")).toBeTruthy();
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

  it("keeps a real fetch error actionable while the stage is still running", () => {
    storyState = { data: null, isLoading: false, error: new Error("Backend 404: story not found") };
    projectStages = {
      extract: { status: "complete" },
      brief: { status: "running" },
    };
    renderStoryAt("/project/demo/story");

    expect(screen.getByText("COULD NOT LOAD")).toBeTruthy();
    expect(screen.getByText("ERROR DETAILS")).toBeTruthy();
    expect(screen.getByText("Backend 404: story not found")).toBeTruthy();
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
