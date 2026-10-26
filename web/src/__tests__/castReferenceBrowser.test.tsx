import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CastRoom } from "../pages/rooms/CastRoom";
import type { GenerationJob } from "../types/api";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({ jobs: [] as GenerationJob[], submit: vi.fn(), review: null as unknown }));
const anchor = "1cat, tortoiseshell persian cat, flat face, fluffy fur, black fur, beige fur, white fur";
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") { server.submit(path); throw new Error(`Unexpected mutation: ${path}`); }
    if (path.includes("/jobs")) return { jobs: server.jobs };
    if (path.endsWith("/cast/review") && server.review) return server.review;
    if (path.includes("story_bible") || path.includes("story-bible")) return {
      characters: [{ id: "cat", name: "Companion", visual_anchor: anchor, age_range: "adult", gender: "female", distinguishing_features: ["fluffy fur"], relationships: [], appearance_states: [], default_outfit: "" }], locations: [{ id: "hall", name: "Great Hall", visual_anchor: "Stone pillars.", time_of_day: "night", mood: "ominous", appearance_states: [] }], props: [{ id: "key", name: "Brass Key", visual_anchor: "Three brass teeth.", first_appearance_scene: "part0002_scene_014" }],
      scenes: [{ id: "part0002_scene_014", part_id: "part0002", chapter: 3, title: "The Brass Door", location_id: "hall" }],
    };
    if (path.endsWith("/status")) return { style_selected: true, stages: { cast: { status: "complete" } } };
    if (path.includes("estimate")) {
      const cost = { estimate_credits: 4, reserved_credits: 6, reservation_multiplier: 1.5, confidence: "variable" };
      return { ...cost, instruction_estimate: cost };
    }
    if (path.includes("character-ref-versions")) return { versions: [], has_history: false };
    if (path.endsWith(".meta.json")) return null;
    if (path.includes("balance")) return { balance_credits: 100 };
    throw new Error(`Unexpected fixture API: ${path}`);
  },
}));
const clients: QueryClient[] = [];
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; server.jobs = []; server.review = null; server.submit.mockReset(); });
function mount(client: QueryClient) {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/project/fixture/cast"]}><I18nProvider><Routes><Route path="/project/:id/cast" element={<CastRoom />} /></Routes></I18nProvider></MemoryRouter></QueryClientProvider>);
}
function renderCast() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return mount(client);
}

const panel = (name: string) => screen.getByRole("complementary", { name });
const changeBox = (name: string) => within(panel(name)).getByRole("textbox", { name: "Make a change" }) as HTMLTextAreaElement;

it("finds references across types and keeps the selection and unsaved corrections when filtering", async () => {
  const user = userEvent.setup();
  renderCast();
  const search = await screen.findByRole("searchbox", { name: "Find a reference" });
  const roster = screen.getByRole("complementary", { name: "Cast list" });
  // The first character starts on the stage.
  expect(within(roster).getByRole("button", { name: "Companion" }).getAttribute("aria-current")).toBe("true");
  await user.type(changeBox("Companion"), "Keep the whiskers longer.");
  await user.type(search, "  HALL  ");
  expect(within(roster).getByRole("button", { name: "Great Hall" })).toBeTruthy();
  expect(within(roster).queryByRole("button", { name: "Companion" })).toBeNull();
  expect(within(roster).queryByRole("button", { name: "Brass Key" })).toBeNull();
  expect(screen.getByText("1 references found")).toBeTruthy();
  await user.clear(search);
  await user.type(search, "brass");
  expect(within(roster).getByRole("button", { name: "Brass Key" })).toBeTruthy();
  expect(within(roster).queryByRole("button", { name: "Great Hall" })).toBeNull();
  await user.clear(search);
  await user.type(search, "nonexistent");
  expect(screen.getByText("No matching references. Try another name or clear your search.")).toBeTruthy();
  // Filtering never drops what is on the stage.
  expect(changeBox("Companion").value).toBe("Keep the whiskers longer.");
  await user.click(screen.getByRole("button", { name: "Clear search" }));
  expect((search as HTMLInputElement).value).toBe("");
  expect(within(roster).getAllByRole("button")).toHaveLength(3);
  expect(server.submit).not.toHaveBeenCalled();
});

it("puts each reference on the stage from the roster or the sheet without starting generation", async () => {
  const user = userEvent.setup();
  renderCast();
  const roster = await screen.findByRole("complementary", { name: "Cast list" });
  for (const name of ["Companion", "Great Hall", "Brass Key"]) {
    await user.click(within(roster).getByRole("button", { name }));
    expect(within(roster).getByRole("button", { name }).getAttribute("aria-current")).toBe("true");
    expect(within(panel(name)).getByRole("heading", { name })).toBeTruthy();
    expect(changeBox(name)).toBeTruthy();
  }
  await user.click(screen.getByRole("button", { name: "Sheet" }));
  expect(screen.queryByRole("complementary", { name: "Cast list" })).toBeNull();
  await user.click(within(screen.getByRole("region", { name: "Places" })).getByRole("button"));
  expect(screen.getByRole("button", { name: "Focus" }).getAttribute("aria-pressed")).toBe("true");
  expect(panel("Great Hall")).toBeTruthy();
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(server.submit).not.toHaveBeenCalled();
});

it("puts a Character check suggestion in the reference's change box and spends nothing", async () => {
  const user = userEvent.setup();
  server.review = { status: "current", issues: [{ character_ids: ["cat"], concern: "scale", evidence: "Too large", suggestion: "Make the cat smaller beside adults." }] };
  renderCast();
  await user.click(await screen.findByRole("button", { name: "Great Hall" }));
  await user.click(await screen.findByRole("button", { name: "Character check · 1 note" }));
  await user.click(screen.getByText("1 note to review"));
  await user.click(screen.getByRole("button", { name: "Use this suggestion · Companion" }));
  expect(changeBox("Companion").value).toBe("Make the cat smaller beside adults.");
  await user.clear(changeBox("Companion"));
  await user.click(screen.getByRole("button", { name: "Character check · 1 note" }));
  await user.click(screen.getByRole("button", { name: "Use this suggestion · Companion" }));
  expect(changeBox("Companion").value).toBe("Make the cat smaller beside adults.");
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(server.submit).not.toHaveBeenCalled();
});

it("names where a prop first appears in reader terms", async () => {
  const user = userEvent.setup();
  renderCast();
  const row = await screen.findByRole("button", { name: "Brass Key" });
  expect(row.textContent).toContain("First seen: The Brass Door");
  await user.click(row);
  expect(within(panel("Brass Key")).getByText("The Brass Door")).toBeTruthy();
  expect(within(panel("Brass Key")).getByText("Three brass teeth.")).toBeTruthy();
});
