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

vi.mock("../api/queries", () => ({
  useStory: () => ({
    data: storyDecision,
    isLoading: false,
    error: null,
  }),
  useProjectStatus: () => ({
    data: {
      stages: {
        extract: { status: "complete" },
        brief: { status: "awaiting_review" },
      },
    },
  }),
  useUpdateBrief: () => ({ mutate: updateBrief, isPending: false }),
  useApproveStage: () => ({ mutate: approveBrief, isPending: false }),
  useCreditBalance: () => ({ data: undefined }),
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
