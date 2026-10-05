import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { StoryBibleEditor } from "../components/story/StoryBibleEditor";
import type { StoryBibleEditor as Editor } from "../api/storyBible";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; body: unknown }[],
  castIds: undefined as string[] | undefined,
  undo: null as Editor["undo"],
  duplicates: [] as Editor["possible_duplicates"],
  references: undefined as Editor["references"] | undefined,
  props: [] as Editor["story_bible"]["props"],
  running: false,
}));

function editor(): Editor {
  return {
    revision: 4,
    undo: server.undo,
    possible_duplicates: server.duplicates,
    parts: [{ id: "part_0001", title: "Book One", ordinal: 1 }, { id: "part_0002", title: "Book Two", ordinal: 2 }],
    editable_scene_ids: ["scene_002"],
    citations: { mara: ["Book One"] },
    state_citations: {},
    references: server.references ?? [{ kind: "characters", entity_id: "ines", state_id: null, status: "outdated" }],
    story_bible: {
      cast_character_ids: server.castIds,
      revision: 4, title: "Lighthouse", author: "Test", total_scenes: 2, style_notes: null, sequences: [],
      excluded_entities: [{ kind: "character", name: "Old Tom", aliases: [], removed: { entity: {}, scene_ids: [] } },
        { kind: "prop", name: "Lantern", aliases: [] }],
      characters: [
        { id: "mara", name: "Mara", visual_anchor: "1woman, short black hair, grey coat.", age_range: "adult", gender: "female",
          distinguishing_features: [], baseline_affect: null, default_outfit: "grey coat", relationships: [],
          first_appearance_scene: "scene_001", appearance_states: [{ id: "storm", label: "Storm gear",
            visual_anchor: "1woman, short black hair, yellow oilskin coat.", continuity_guard: "  The coat stays yellow.  ",
            visually_significant: true, baseline_affect: null }], aliases: [], origin: "extracted" },
        { id: "ines", name: "Ines", visual_anchor: "1woman, long red hair", age_range: "adult", gender: "female",
          distinguishing_features: [], baseline_affect: null, default_outfit: "", relationships: [],
          first_appearance_scene: "scene_001", appearance_states: [], aliases: ["Ines Vale"], origin: "author" },
      ],
      locations: [{ id: "lamp", name: "Lamp room", visual_anchor: "glass lamp room", time_of_day: null, mood: "calm", appearance_states: [] }],
      props: server.props,
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
    if (path.endsWith("/status")) return { is_running: server.running, stages: {} };
    if (path.startsWith("/projects/p1/story-bible/characters/draft-estimate")) {
      return { mentioned: true, estimate: { estimate_credits: 2, reserved_credits: 3, reservation_multiplier: 1.5, confidence: "variable" }, mentioned_scene_ids: ["scene_002"] };
    }
    if (path === "/projects/p1/story-bible/characters/draft") {
      return { details: { name: "Old Tom", visual_anchor: "1man, white beard, oilskin coat", age_range: "70s" }, suggested_scene_ids: ["scene_002"], mentioned_scene_ids: ["scene_002"] };
    }
    if (method === "POST" && path === "/projects/p1/story-bible/characters") return { ...saved, entity_id: "author_char_001" };
    if (method === "PATCH" && path === "/projects/p1/story-bible/characters/mara") return saved;
    if (method === "PATCH" && path === "/projects/p1/story-bible/characters/mara/states/storm") return saved;
    if (path.startsWith("/projects/p1/story-bible/characters/ines/impact")) {
      const merge = path.includes("action=merge");
      return { action: merge ? "merge" : "remove", blocked: null, scenes: [{ id: "scene_001", title: "The light", part_id: "part_0001" }],
        looks: [], relationships: 0, aliases: merge ? ["Ines", "Ines Vale"] : [], cast_images: 1, new_references: merge ? 0 : 0, reopens_cast: false };
    }
    if (method === "POST" && path === "/projects/p1/story-bible/characters/ines/merge") return saved;
    if (method === "POST" && path === "/projects/p1/story-bible/undo") return { ...saved, undone: server.undo?.change };
    if (method === "DELETE") return saved;
    throw new Error(`Unexpected fixture API: ${method} ${path}`);
  },
}));

afterEach(() => { server.calls = []; server.castIds = undefined; server.undo = null; server.duplicates = []; server.references = undefined; server.props = []; server.running = false; localStorage.clear(); });

const openEntry = async (user: ReturnType<typeof userEvent.setup>, name: string) =>
  user.click(await screen.findByRole("button", { name }));

function CastLocation() {
  const location = useLocation();
  return <p>Cast room {location.search}</p>;
}

function renderEditor(story?: Editor["story_bible"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><I18nProvider><MemoryRouter initialEntries={["/project/p1~part_0002/story"]}>
    <Routes>
      <Route path="/project/:id/story" element={<StoryBibleEditor project="p1~part_0002" story={story} />} />
      <Route path="/project/:id/cast" element={<CastLocation />} />
    </Routes>
  </MemoryRouter></I18nProvider></QueryClientProvider>);
}

it("hides internal subject labels in Story Bible rows and description editors", async () => {
  const user = userEvent.setup();
  const view = renderEditor();
  const mara = (await screen.findByText("Mara")).closest("li")!;
  expect(within(mara).getByText("Short black hair, grey coat.")).toBeTruthy();
  expect(screen.getByText("Long red hair.")).toBeTruthy();
  expect(view.container.textContent).not.toMatch(/\b1woman\b/);

  await openEntry(user, "Mara");
  const sheet = screen.getByRole("dialog", { name: "Edit Mara" });
  const description = within(sheet).getByLabelText("Physical description *") as HTMLTextAreaElement;
  expect(description.value).toBe("short black hair, grey coat.");
  expect(within(sheet).getByText("Short black hair, yellow oilskin coat.")).toBeTruthy();
  expect(sheet.textContent).not.toMatch(/\b1woman\b/);

  const look = within(sheet).getByText("Storm gear").closest("li")!;
  await user.click(within(look).getByRole("button", { name: "Edit" }));
  expect((within(sheet).getByLabelText("Complete description of this look *") as HTMLTextAreaElement).value)
    .toBe("short black hair, yellow oilskin coat.");
  await user.clear(within(sheet).getByLabelText("Label *"));
  await user.type(within(sheet).getByLabelText("Label *"), "Rain gear");
  await user.click(within(sheet).getByRole("button", { name: "Save look" }));
  await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/states/storm"))).toBe(true));
  expect(server.calls.find((call) => call.path.endsWith("/states/storm"))?.body).toEqual({
    expected_revision: 4,
    changes: { label: "Rain gear", visual_anchor: "1woman, short black hair, yellow oilskin coat.",
      continuity_guard: "  The coat stays yellow.  ", visually_significant: true },
  });
});

it("saves an intentional physical description edit without exposing model tags", async () => {
  const user = userEvent.setup();
  renderEditor();
  await openEntry(user, "Mara");
  const sheet = screen.getByRole("dialog", { name: "Edit Mara" });
  const description = within(sheet).getByLabelText("Physical description *");
  await user.clear(description);
  await user.type(description, "short black hair, red coat");
  await user.click(within(sheet).getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(server.calls.some((call) => call.method === "PATCH")).toBe(true));
  expect(server.calls.find((call) => call.method === "PATCH")?.body).toEqual({
    expected_revision: 4, changes: { visual_anchor: "short black hair, red coat" },
  });
});

it("lets an author include a briefly appearing character in Cast against the loaded revision", async () => {
  const user = userEvent.setup();
  renderEditor();
  await openEntry(user, "Mara");
  const sheet = screen.getByRole("dialog", { name: "Edit Mara" });
  await user.click(within(sheet).getByRole("checkbox", { name: /Include in Cast even for a brief appearance/ }));
  await user.click(within(sheet).getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(server.calls.some((call) => call.method === "PATCH")).toBe(true));
  expect(server.calls.find((call) => call.method === "PATCH")?.body).toEqual({ expected_revision: 4, changes: { cast_required: true } });
});

it("lets an author choose a form study sheet, keeping formation for groups", async () => {
  const user = userEvent.setup();
  renderEditor();
  await openEntry(user, "Mara");
  const sheet = screen.getByRole("dialog", { name: "Edit Mara" });
  const select = within(sheet).getByRole("combobox", { name: "Reference sheet" }) as HTMLSelectElement;
  expect(select.value).toBe("figure");
  expect((within(select).getByRole("option", { name: /Formation/ }) as HTMLOptionElement).disabled).toBe(true);
  await user.selectOptions(select, "form");
  await user.click(within(sheet).getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(server.calls.some((call) => call.method === "PATCH")).toBe(true));
  expect(server.calls.find((call) => call.method === "PATCH")?.body).toEqual({ expected_revision: 4, changes: { reference_form: "form" } });
});

it("keeps the editor focused on recurring cast and lets authors inspect every source participant", async () => {
  server.castIds = ["ines"];
  const user = userEvent.setup();
  renderEditor();
  await screen.findByRole("button", { name: "Ines" });
  expect(screen.queryByText("Mara")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Show all source participants" }));
  expect(screen.getByText("Mara")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Show recurring characters only" }));
  expect(screen.queryByText("Mara")).toBeNull();
});

it("keeps what adapted parts cite and previews a removal before it happens", async () => {
  const user = userEvent.setup();
  renderEditor();
  const mara = (await screen.findByText("Mara")).closest("li")!;
  expect(within(mara).getByText("Used in Book One")).toBeTruthy();
  expect(within(mara).queryByRole("button", { name: "Remove" })).toBeNull();  // never on the list
  await openEntry(user, "Mara");
  let sheet = screen.getByRole("dialog", { name: "Edit Mara" });
  expect(within(sheet).getByText(/Book One already uses this entry/)).toBeTruthy();
  expect((within(sheet).getByRole("button", { name: "Remove from the story…" }) as HTMLButtonElement).disabled).toBe(true);
  await user.click(within(sheet).getByRole("button", { name: "Close Esc" }));

  const ines = screen.getByRole("button", { name: "Ines" }).closest("li")!;
  expect(within(ines).getByText("Added by you")).toBeTruthy();
  expect(within(ines).getByText("Cast image out of date")).toBeTruthy();
  await openEntry(user, "Ines");
  sheet = screen.getByRole("dialog", { name: "Edit Ines" });
  await user.click(within(sheet).getByRole("button", { name: "Remove from the story…" }));
  sheet = screen.getByRole("dialog", { name: "Remove Ines?" });
  expect(await within(sheet).findByText("Ines leaves 1 scene: The light")).toBeTruthy();
  expect(within(sheet).getByText("1 Cast image stops being used. Bringing Ines back restores them.")).toBeTruthy();
  await user.click(within(sheet).getByRole("button", { name: "Remove Ines" }));
  await waitFor(() => expect(server.calls.some((call) => call.method === "DELETE")).toBe(true));
  expect(server.calls.find((call) => call.method === "DELETE")?.path)
    .toBe("/projects/p1/story-bible/characters/ines?expected_revision=4");

  await user.click(screen.getByRole("button", { name: /Removed/ }));
  const tom = screen.getByText("Old Tom").closest("li")!;
  expect(within(tom).getByRole("button", { name: "Bring back" })).toBeTruthy();
  expect(within(screen.getByText("Lantern").closest("li")!).getByRole("button", { name: "Allow again" })).toBeTruthy();
  await user.click(within(tom).getByRole("button", { name: "Bring back" }));
  await waitFor(() => expect(server.calls.some((call) => call.path.startsWith("/projects/p1/story-bible/excluded/characters/Old%20Tom"))).toBe(true));
});

it("merges only after the author picks what stays and sees what changes", async () => {
  const user = userEvent.setup();
  renderEditor();
  await openEntry(user, "Ines");
  await user.click(within(screen.getByRole("dialog", { name: "Edit Ines" })).getByRole("button", { name: "Merge into another entry…" }));
  const sheet = screen.getByRole("dialog", { name: "Merge Ines" });
  // Nothing is chosen for the author.
  expect((within(sheet).getByRole("button", { name: "Merge" }) as HTMLButtonElement).disabled).toBe(true);
  expect(within(sheet).getByText("Choose an entry below.")).toBeTruthy();
  await user.type(within(sheet).getByLabelText("Find an entry"), "zzz");
  expect(within(sheet).getByText("No entry matches.")).toBeTruthy();
  await user.clear(within(sheet).getByLabelText("Find an entry"));
  await user.click(within(sheet).getByRole("radio", { name: /Mara/ }));
  expect(await within(sheet).findByText("Ines, Ines Vale become other names for Mara.")).toBeTruthy();
  // Mara is cited, so she can't be the one folded in.
  expect(within(sheet).queryByRole("button", { name: "Keep Ines instead" })).toBeNull();
  await user.click(within(sheet).getByRole("button", { name: "Merge into Mara" }));
  await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/ines/merge"))).toBe(true));
  expect(server.calls.find((call) => call.path.endsWith("/ines/merge"))?.body).toEqual({ expected_revision: 4, into: "mara" });
});

it("offers to undo the latest change and to compare likely duplicates", async () => {
  server.undo = { change: { action: "merge", kind: "characters", name: "Ines Vale", into: "Ines" }, blocked: null };
  server.duplicates = [{ kind: "characters", ids: ["mara", "ines"], reason: "name_within" }];
  const user = userEvent.setup();
  renderEditor();
  expect(await screen.findByText("Merged Ines Vale into Ines")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(server.calls.find((call) => call.path === "/projects/p1/story-bible/undo")?.body)
    .toEqual({ expected_revision: 4 }));

  const pair = screen.getByText("Mara and Ines may be the same character.").closest("li")!;
  await user.click(within(pair).getByRole("button", { name: "Compare" }));
  // The cited entry stays.
  const sheet = screen.getByRole("dialog", { name: "Merge Ines" });
  expect(await within(sheet).findByText("Ines, Ines Vale become other names for Mara.")).toBeTruthy();
  await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
  await user.click(within(screen.getByText("Mara and Ines may be the same character.").closest("li")!).getByRole("button", { name: "Not the same" }));
  expect(screen.queryByText("Mara and Ines may be the same character.")).toBeNull();
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
    details: { name: "Old Tom", visual_anchor: "1man, white beard, oilskin coat", age_range: "70s" },
  });
});

it("shows this part's scenes read-only beside who and where the shared entries are", async () => {
  const bible = editor().story_bible;
  const part = { ...bible, scenes: bible.scenes.filter((scene) => scene.part_id === "part_0002"), excluded_entities: [] };
  const user = userEvent.setup();
  renderEditor({ ...part, characters: part.characters.map((character) => character.id === "mara"
    ? { ...character, baseline_affect: "guarded_and_precise", relationships: [{ character_id: "ines", relationship: "estranged sister" }] }
    : character) });
  expect(screen.getByRole("heading", { name: "Inside your story" })).toBeTruthy();
  expect(screen.getByRole("button", { name: /^Scenes\s*1$/ }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("heading", { name: "The storm" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Add a character" })).toBeNull();

  // Once loaded, entries come from the shared editor copy, not this part's snapshot.
  await user.click(await screen.findByRole("button", { name: /^Characters\s*2$/ }));
  const mara = screen.getByRole("heading", { name: "Mara" }).closest("li")!;
  expect(within(mara).getByText("adult · female")).toBeTruthy();
  expect(within(mara).queryByText("· estranged sister")).toBeNull();
  // The first appearance lies in an earlier part, so the card names it.
  expect(within(mara).getByText("Book One · The light")).toBeTruthy();
  expect(within(mara).getByText("Used in Book One")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add a character" })).toBeTruthy();

  await user.click(screen.getByRole("button", { name: /^Places\s*1$/ }));
  const lamp = screen.getByRole("heading", { name: "Lamp room" }).closest("li")!;
  expect(within(lamp).getByText("Calm")).toBeTruthy();
  expect(within(lamp).getByText("01")).toBeTruthy();

  await user.click(screen.getByRole("button", { name: /Removed/ }));
  expect(screen.getByText("Old Tom")).toBeTruthy();
});

it("lists Cast images that edits left missing or out of date and leads to Cast to make them", async () => {
  server.props = [{ id: "sphinx", name: "Wooden sphinx", visual_anchor: "small carved wooden sphinx", first_appearance_scene: "scene_002",
    appearance_states: [], aliases: [], origin: "author" }];
  server.references = [
    { kind: "characters", entity_id: "mara", state_id: null, status: "current" },
    { kind: "characters", entity_id: "ines", state_id: null, status: "outdated" },
    { kind: "props", entity_id: "sphinx", state_id: null, status: "missing" },
  ];
  const user = userEvent.setup();
  renderEditor();
  const notice = await screen.findByRole("region", { name: "Cast images to update" });
  expect(within(notice).getByRole("heading").textContent).toBe("2 Cast images to update");
  expect(within(notice).getByText("Wooden sphinx").parentElement!.textContent).toContain("New, no image yet");
  expect(within(notice).getByText("Ines").parentElement!.textContent).toContain("Changed since its image");

  await user.click(screen.getByRole("button", { name: /^Props\s*1$/ }));
  const sphinx = screen.getByRole("button", { name: "Wooden sphinx" }).closest("li")!;
  expect(within(sphinx).getByRole("link", { name: "No Cast image yet" }).getAttribute("href"))
    .toBe("/project/p1~part_0002/cast?references=update");

  await user.click(within(notice).getByRole("button", { name: /Update in Cast/ }));
  expect(await screen.findByText("Cast room ?references=update")).toBeTruthy();
});

it("says nothing about Cast images before Cast has made any", async () => {
  server.references = [
    { kind: "characters", entity_id: "mara", state_id: null, status: "missing" },
    { kind: "characters", entity_id: "ines", state_id: null, status: "missing" },
  ];
  renderEditor();
  await screen.findByRole("button", { name: "Ines" });
  expect(screen.queryByRole("region", { name: "Cast images to update" })).toBeNull();
  expect(screen.queryByText("No Cast image yet")).toBeNull();
});

it("holds the Cast update while project work is queued or running", async () => {
  server.running = true;
  renderEditor();
  const notice = await screen.findByRole("region", { name: "Cast images to update" });
  await waitFor(() => expect((within(notice).getByRole("button", { name: /Update in Cast/ }) as HTMLButtonElement).disabled).toBe(true));
  expect(within(notice).getByText("Work is running on this project. Update these once it finishes.")).toBeTruthy();
});
