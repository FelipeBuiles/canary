import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StoryScenes } from "../components/story/StoryScenes";
import { I18nProvider } from "../i18n";
import type { StoryBible } from "../types/api";

afterEach(cleanup);

const scene = (id: string, title: string, beat: string, location_id = "loc_1") => ({
  id, chapter: 1, title, location_id, character_ids: ["char_1"], summary: `${title} summary.`,
  scene_type: "action", narrative_beat: beat, source_start_quote: "",
});

const story: StoryBible = {
  title: "The Last Incantation",
  author: "H. P. Lovecraft",
  total_scenes: 3,
  characters: [
    {
      id: "char_1", name: "Elena", visual_anchor: "1woman, silver-streaked dark hair", age_range: "late 30s", gender: "female",
      distinguishing_features: [], baseline_affect: "guarded and precise", default_outfit: "",
      relationships: [{ character_id: "char_2", relationship: "estranged sister" }],
      first_appearance_scene: "scene_1", appearance_states: [],
    },
    {
      id: "char_2", name: "Mara", visual_anchor: "1woman, red coat", age_range: "unknown", gender: "female",
      distinguishing_features: [], baseline_affect: null, default_outfit: "", relationships: [],
      first_appearance_scene: "scene_3", appearance_states: [],
    },
  ],
  locations: [{ id: "loc_1", name: "The Archive", visual_anchor: "interior, salt-stained stone stacks", time_of_day: "night", mood: "hushed", appearance_states: [] }],
  scenes: [
    scene("scene_1", "The Locked Shelf", "inciting_incident"),
    scene("scene_2", "The Ledger", "inciting_incident"),
    scene("scene_3", "Epilogue", "resolution", "loc_2"),
  ],
  sequences: [{ part_id: "part_0001", number: 1, title: "The Discovery", scenes: ["scene_1", "scene_2"], turn: "Elena reads the forbidden page." }],
  style_notes: null,
  props: [],
};

function renderScenes(value: StoryBible = story) {
  render(<I18nProvider><StoryScenes story={value} /></I18nProvider>);
}

describe("StoryScenes", () => {
  it("keeps every participant on scene rosters, not only the recurring cast", () => {
    renderScenes({ ...story, cast_character_ids: ["char_1"], scenes: [
      ...story.scenes.slice(0, 2), { ...story.scenes[2], character_ids: ["char_1", "char_2"] },
    ] });
    expect(screen.getByText("Elena, Mara")).toBeTruthy();
  });

  it("excludes back matter from story action and numbering even when a sequence claims it", () => {
    renderScenes({ ...story, sequences: [{ ...story.sequences[0], scenes: ["scene_1", "back"] }], scenes: [story.scenes[0], {
      ...story.scenes[0], id: "back",
      title: "Reading recommendations", location_id: null, character_ids: [],
      scene_type: "non_narrative", summary: "Links to reading communities.",
    }, { ...story.scenes[1] }] });
    expect(screen.queryByRole("heading", { name: "Reading recommendations" })).toBeNull();
    expect(screen.getByLabelText("SCENE 2")).toBeTruthy();
    expect(screen.getByText("Author notes and other non-story material are excluded from adaptation.")).toBeTruthy();
  });

  it("groups scenes into sequences, closes each with its turn, and keeps unclaimed scenes", () => {
    renderScenes();

    const sequence = screen.getByRole("region", { name: "The Discovery" });
    expect(within(sequence).getByText("Sequence 1")).toBeTruthy();
    expect(screen.queryByText(/^Act /)).toBeNull();
    expect(within(sequence).getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent)).toEqual(["The Locked Shelf", "The Ledger"]);
    expect(within(sequence).getByText("Elena reads the forbidden page.")).toBeTruthy();
    // The beat marks where it changes, not every scene that shares it.
    expect(within(sequence).getAllByText("Inciting incident")).toHaveLength(1);

    const more = screen.getByRole("region", { name: "More scenes" });
    expect(within(more).getByRole("heading", { name: "Epilogue" })).toBeTruthy();
    expect(within(more).getByLabelText("SCENE 3")).toBeTruthy();
    // One chapter throughout: the chapter label would be noise.
    expect(screen.queryByText(/Chapter/)).toBeNull();
  });

  it("lists scenes without sequence headings when Extract found none", () => {
    renderScenes({ ...story, sequences: [] });

    expect(screen.queryByRole("region", { name: "More scenes" })).toBeNull();
    expect(screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["The Locked Shelf", "The Ledger", "Epilogue"]);
  });
});
