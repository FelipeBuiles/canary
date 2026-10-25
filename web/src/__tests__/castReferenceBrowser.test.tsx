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

it("finds references across types and keeps cards and unsaved corrections mounted when filtering", async () => {
  const user = userEvent.setup();
  renderCast();
  const search = await screen.findByRole("searchbox", { name: "Find a reference" });
  const card = screen.getByRole("heading", { name: "Companion" }).closest("article")!;
  await user.click(screen.getByRole("button", { name: "Review & adjust · Companion" }));
  await user.type(within(screen.getByRole("dialog")).getByRole("textbox"), "Keep the whiskers longer.");
  await user.keyboard("{Escape}");
  await user.type(search, "  HALL  ");
  expect(screen.getByRole("button", { name: "Review & adjust · Great Hall" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Review & adjust · Companion" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Review & adjust · Brass Key" })).toBeNull();
  expect(screen.getByText("1 references found")).toBeTruthy();
  await user.clear(search);
  await user.type(search, "brass");
  expect(screen.getByRole("button", { name: "Review & adjust · Brass Key" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Review & adjust · Great Hall" })).toBeNull();
  await user.clear(search);
  await user.type(search, "nonexistent");
  expect(screen.getByText("No matching references. Try another name or clear your search.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^Review & adjust ·/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Clear search" }));
  expect((search as HTMLInputElement).value).toBe("");
  expect(screen.getAllByRole("button", { name: /^Review & adjust ·/ })).toHaveLength(3);
  expect(screen.getByRole("heading", { name: "Companion" }).closest("article")).toBe(card);
  await user.click(screen.getByRole("button", { name: "Review & adjust · Companion" }));
  expect((within(screen.getByRole("dialog")).getByRole("textbox") as HTMLTextAreaElement).value).toBe("Keep the whiskers longer.");
  expect(server.submit).not.toHaveBeenCalled();
});

it("offers section destinations and explicit review controls without starting generation", async () => {
  const user = userEvent.setup();
  renderCast();
  const search = await screen.findByRole("searchbox", { name: "Find a reference" });
  for (const name of ["Characters 1", "Places 1", "Props 1"]) {
    const link = screen.getByRole("link", { name });
    expect(document.querySelector(link.getAttribute("href")!)).toBeTruthy();
    await user.type(search, "nonexistent");
    await user.click(link);
    expect((search as HTMLInputElement).value).toBe("");
    expect(screen.getAllByRole("button", { name: /^Review & adjust ·/ })).toHaveLength(3);
  }
  for (const name of ["Companion", "Great Hall", "Brass Key"]) {
    await user.click(screen.getByRole("button", { name: `Review & adjust · ${name}` }));
    expect(screen.getByRole("dialog", { name: name.toUpperCase() })).toBeTruthy();
    expect(within(screen.getByRole("dialog")).getByRole("textbox")).toBeTruthy();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await user.keyboard("{Escape}");
  }
  expect(server.submit).not.toHaveBeenCalled();
});

it("opens Review & adjust with a Character check suggestion prefilled and spends nothing", async () => {
  const user = userEvent.setup();
  server.review = { status: "current", issues: [{ character_ids: ["cat"], concern: "scale", evidence: "Too large", suggestion: "Make the cat smaller beside adults." }] };
  renderCast();
  await user.click(await screen.findByText("1 note to review"));
  await user.click(screen.getByRole("button", { name: "Use this suggestion · Companion" }));
  const dialog = screen.getByRole("dialog", { name: "COMPANION" });
  expect((within(dialog).getByRole("textbox") as HTMLTextAreaElement).value).toBe("Make the cat smaller beside adults.");
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Use this suggestion · Companion" }));
  expect((within(screen.getByRole("dialog")).getByRole("textbox") as HTMLTextAreaElement).value).toBe("Make the cat smaller beside adults.");
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(server.submit).not.toHaveBeenCalled();
});

it("aligns each card's sections and names where a prop first appears in reader terms", async () => {
  renderCast();
  const heading = await screen.findByRole("heading", { name: "Brass Key" });
  const card = heading.closest("article")!;
  expect(card.classList.contains("grid-rows-subgrid")).toBe(true);
  expect(within(card).getByText("First seen: The Brass Door")).toBeTruthy();
  expect(within(card).getByText("Three brass teeth.")).toBeTruthy();
});
