import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { StoryBibleEditor } from "../components/story/StoryBibleEditor";
import type { StoryBibleEditor as Editor } from "../api/storyBible";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; body: unknown }[],
  castIds: undefined as string[] | undefined,
}));

function editor(): Editor {
  return {
    revision: 4,
    parts: [{ id: "part_0001", title: "Book One", ordinal: 1 }, { id: "part_0002", title: "Book Two", ordinal: 2 }],
    editable_scene_ids: ["scene_002"],
    citations: { mara: ["Book One"] },
    state_citations: {},
    references: [{ kind: "characters", entity_id: "ines", state_id: null, status: "outdated" }],
    story_bible: {
      cast_character_ids: server.castIds,
      revision: 4, title: "Lighthouse", author: "Test", total_scenes: 2, style_notes: null, sequences: [],
      excluded_entities: [{ kind: "character", name: "Old Tom", aliases: [] }],
      characters: [
        { id: "mara", name: "Mara", visual_anchor: "short black hair, grey coat", age_range: "adult", gender: "female",
          distinguishing_features: [], baseline_affect: null, default_outfit: "grey coat", relationships: [],
          first_appearance_scene: "scene_001", appearance_states: [], aliases: [], origin: "extracted" },
        { id: "ines", name: "Ines", visual_anchor: "long red hair", age_range: "adult", gender: "female",
          distinguishing_features: [], baseline_affect: null, default_outfit: "", relationships: [],
          first_appearance_scene: "scene_001", appearance_states: [], aliases: ["Ines Vale"], origin: "author" },
      ],
      locations: [{ id: "lamp", name: "Lamp room", visual_anchor: "glass lamp room", time_of_day: null, mood: "calm", appearance_states: [] }],
      props: [],
      scenes: [
        { id: "scene_001", part_id: "part_0001", chapter: 1, title: "The light", location_id: "lamp", character_ids: ["mara", "ines"],
          summary: "", scene_type: "dialogue", narrative_beat: "setup", source_start_quote: "The light" },
        { id: "scene_002", part_id: "part_0002", chapter: 2, title: "The storm", location_id: "lamp", character_ids: ["mara"],
          summary: "", scene_type: "action", narrative_beat: "rising", source_start_quote: "The storm" },
      ],
    },
  };
}

vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    const body = options?.body ? JSON.parse(String(options.body)) : undefined;
    server.calls.push({ path, method, body });
    const saved = { story_bible: editor().story_bible, revision: 5 };
    if (path === "/projects/p1/story-bible/editor") return editor();
    if (path.startsWith("/projects/p1/story-bible/characters/draft-estimate")) {
      return { mentioned: true, estimate: { estimate_credits: 2, reserved_credits: 3, reservation_multiplier: 1.5, confidence: "variable" }, mentioned_scene_ids: ["scene_002"] };
    }
    if (path === "/projects/p1/story-bible/characters/draft") {
      return { details: { name: "Old Tom", visual_anchor: "white beard, oilskin coat", age_range: "70s" }, suggested_scene_ids: ["scene_002"], mentioned_scene_ids: ["scene_002"] };
    }
    if (method === "POST" && path === "/projects/p1/story-bible/characters") return { ...saved, entity_id: "author_char_001" };
    if (method === "PATCH" && path === "/projects/p1/story-bible/characters/mara") return saved;
    if (method === "DELETE") return saved;
    throw new Error(`Unexpected fixture API: ${method} ${path}`);
  },
}));

afterEach(() => { server.calls = []; server.castIds = undefined; });

function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><I18nProvider><MemoryRouter initialEntries={["/project/p1~part_0002/story"]}>
    <StoryBibleEditor project="p1~part_0002" />
  </MemoryRouter></I18nProvider></QueryClientProvider>);
}

it("lets an author include a briefly appearing character in Cast against the loaded revision", async () => {
  const user = userEvent.setup();
  renderEditor();
  const mara = (await screen.findByText("Mara")).closest("li")!;
  await user.click(within(mara).getByRole("button", { name: "Edit" }));
  const sheet = screen.getByRole("dialog", { name: "Edit Mara" });
  await user.click(within(sheet).getByRole("checkbox", { name: /Include in Cast even for a brief appearance/ }));
  await user.click(within(sheet).getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(server.calls.some((call) => call.method === "PATCH")).toBe(true));
  expect(server.calls.find((call) => call.method === "PATCH")?.body).toEqual({ expected_revision: 4, changes: { cast_required: true } });
});

it("keeps the editor focused on recurring cast and lets authors inspect every source participant", async () => {
  server.castIds = ["ines"];
  const user = userEvent.setup();
  renderEditor();
  await screen.findByText("Ines");
  expect(screen.queryByText("Mara")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Show all source participants" }));
  expect(screen.getByText("Mara")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Show recurring characters only" }));
  expect(screen.queryByText("Mara")).toBeNull();
});

it("keeps what adapted parts cite and removes the rest against the loaded revision", async () => {
  const user = userEvent.setup();
  renderEditor();
  const mara = (await screen.findByText("Mara")).closest("li")!;
  expect(within(mara).getByText("Used in Book One")).toBeTruthy();
  expect((within(mara).getByRole("button", { name: "Remove" }) as HTMLButtonElement).disabled).toBe(true);
  const ines = screen.getByText("Ines").closest("li")!;
  expect(within(ines).getByText("Added by you")).toBeTruthy();
  expect(within(ines).getByText("Cast image out of date")).toBeTruthy();

  await user.click(within(ines).getByRole("button", { name: "Remove" }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(server.calls.some((call) => call.method === "DELETE")).toBe(true));
  expect(server.calls.find((call) => call.method === "DELETE")?.path)
    .toBe("/projects/p1/story-bible/characters/ines?expected_revision=4");

  await user.click(screen.getByRole("button", { name: /Removed names/ }));
  expect(screen.getByText("Old Tom")).toBeTruthy();
});

it("adds a character drafted from the source into the scenes that can still change", async () => {
  const user = userEvent.setup();
  renderEditor();
  await user.click(await screen.findByRole("button", { name: "Add a character" }));
  const sheet = screen.getByRole("dialog", { name: "Add a character" });
  await user.type(within(sheet).getByLabelText("Name *"), "Old Tom");
  const draft = await within(sheet).findByRole("button", { name: /Draft from source/ });
  await waitFor(() => expect(draft.textContent).toContain("~2 credits"));
  await user.click(draft);
  await waitFor(() => expect((within(sheet).getByLabelText("Physical description *") as HTMLTextAreaElement).value)
    .toBe("white beard, oilskin coat"));
  const adapted = within(sheet).getByRole("checkbox", { name: /The light/ }) as HTMLInputElement;
  expect(adapted.disabled).toBe(true);
  expect((within(sheet).getByRole("checkbox", { name: /The storm/ }) as HTMLInputElement).checked).toBe(true);

  await user.click(within(sheet).getByRole("button", { name: "Add to the Story Bible" }));
  await waitFor(() => expect(server.calls.some((call) => call.method === "POST" && call.path === "/projects/p1/story-bible/characters")).toBe(true));
  expect(server.calls.find((call) => call.path === "/projects/p1/story-bible/characters")?.body).toEqual({
    expected_revision: 4,
    scene_ids: ["scene_002"],
    details: { name: "Old Tom", visual_anchor: "white beard, oilskin coat", age_range: "70s" },
  });
});
