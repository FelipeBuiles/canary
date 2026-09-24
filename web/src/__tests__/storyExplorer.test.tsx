import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StoryExplorer } from "../components/composites/StoryExplorer";
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
  narrative_arcs: [{ act: 1, title: "The Discovery", scenes: ["scene_1", "scene_2"], turning_point: "Elena reads the forbidden page." }],
  style_notes: null,
  props: [],
};

function renderExplorer(value: StoryBible = story) {
  render(<I18nProvider><StoryExplorer story={value} /></I18nProvider>);
}

describe("StoryExplorer", () => {
  it("groups scenes into acts, closes each act with its turning point, and keeps unclaimed scenes", () => {
    renderExplorer();

    const act = screen.getByRole("region", { name: "The Discovery" });
    expect(within(act).getByText("Act 1")).toBeTruthy();
    expect(within(act).getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent)).toEqual(["The Locked Shelf", "The Ledger"]);
    expect(within(act).getByText("Elena reads the forbidden page.")).toBeTruthy();
    // The beat marks where it changes, not every scene that shares it.
    expect(within(act).getAllByText("Inciting incident")).toHaveLength(1);

    const more = screen.getByRole("region", { name: "More scenes" });
    expect(within(more).getByRole("heading", { name: "Epilogue" })).toBeTruthy();
    expect(within(more).getByLabelText("SCENE 3")).toBeTruthy();
    // One chapter throughout: the chapter label would be noise.
    expect(screen.queryByText(/Chapter/)).toBeNull();
  });

  it("lists scenes without act headings when Extract found no arcs", () => {
    renderExplorer({ ...story, narrative_arcs: [] });

    expect(screen.queryByRole("region", { name: "More scenes" })).toBeNull();
    expect(screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["The Locked Shelf", "The Ledger", "Epilogue"]);
  });

  it("shows who each character is, not only how they are drawn", () => {
    renderExplorer();
    fireEvent.click(screen.getByRole("button", { name: /^Characters\s*2$/ }));

    const elena = screen.getByRole("heading", { name: "Elena" }).closest("article")!;
    expect(within(elena).getByText("late 30s · female")).toBeTruthy();
    expect(within(elena).getByText("Guarded and precise")).toBeTruthy();
    expect(within(elena).getByText("Silver-streaked dark hair.")).toBeTruthy();
    expect(within(elena).getByText("Mara")).toBeTruthy();
    expect(within(elena).getByText("· estranged sister")).toBeTruthy();
    expect(within(elena).getByText("01 · The Locked Shelf")).toBeTruthy();

    const mara = screen.getByRole("heading", { name: "Mara" }).closest("article")!;
    expect(within(mara).getByText("female")).toBeTruthy();
  });

  it("shows each place's time, mood and the scenes set there", () => {
    renderExplorer();
    fireEvent.click(screen.getByRole("button", { name: /^Places\s*1$/ }));

    const archive = screen.getByRole("heading", { name: "The Archive" }).closest("article")!;
    expect(within(archive).getByText("Night · Hushed")).toBeTruthy();
    expect(within(archive).getByText("Interior, salt-stained stone stacks.")).toBeTruthy();
    expect(within(archive).getByText("01, 02")).toBeTruthy();
  });
});
