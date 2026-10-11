import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CastRoom } from "../pages/rooms/CastRoom";
import type * as Client from "../api/client";

type Freshness = "current" | "outdated" | "missing";
const server = vi.hoisted(() => ({ cat: "outdated" as Freshness, hall: "current" as Freshness, running: true }));
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string) => {
    if (path.includes("/jobs")) return { jobs: [] };
    if (path.endsWith("/cast/freshness")) return { references: [
      { kind: "characters", entity_id: "cat", state_id: null, status: server.cat },
      { kind: "locations", entity_id: "hall", state_id: null, status: server.hall },
    ] };
    if (path.includes("story_bible") || path.includes("story-bible")) return {
      characters: [{ id: "cat", name: "Companion", visual_anchor: "Tortoiseshell cat.", age_range: "adult", gender: "female", distinguishing_features: [], relationships: [], appearance_states: [], default_outfit: "" }],
      locations: [{ id: "hall", name: "Great Hall", visual_anchor: "Stone pillars.", time_of_day: "night", mood: "ominous", appearance_states: [] }],
      props: [], scenes: [],
    };
    if (path.endsWith("/status")) return {
      style_selected: true, is_running: server.running, active_jobs: [],
      stages: { cast: { status: server.running ? "running" : "complete", items_done: 2, items_total: 17, failures: [] } },
    };
    throw new Error(`Unexpected fixture API: ${path}`);
  },
}));
afterEach(() => { server.cat = "outdated"; server.hall = "current"; server.running = true; });

function renderCast() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/project/fixture/cast"]}><I18nProvider>
    <Routes><Route path="/project/:id/cast" element={<CastRoom />} /></Routes>
  </I18nProvider></MemoryRouter></QueryClientProvider>);
  return client;
}
/** The existing images load: only a pending update may keep a card drawing. */
function loadExistingImages() {
  for (const image of document.querySelectorAll("img")) fireEvent.load(image);
}
const card = (name: string) => screen.getByRole("heading", { name }).closest("article")!;
const drawing = (name: string) => card(name).querySelector('[aria-busy="true"]') !== null;

it("shows the run's progress in the Cast room and keeps changed references drawing until their new image lands", async () => {
  const client = renderCast();
  const progress = await screen.findByRole("status", { name: "Cast progress" });
  expect(within(progress).getByText("2 / 17")).toBeTruthy();
  await waitFor(() => expect(within(progress).getByText(/1 changed reference still to redraw/)).toBeTruthy());

  act(loadExistingImages);
  // The outdated character still has its old image on disk, but it is not done.
  expect(drawing("Companion")).toBe(true);
  expect(drawing("Great Hall")).toBe(false);

  server.cat = "current";
  await act(() => client.refetchQueries({ queryKey: ["project", "fixture", "cast-freshness"] }));
  await waitFor(() => expect(screen.queryByText(/changed reference still to redraw/)).toBeNull());
  // The card swaps to the new image's URL; load whichever image is mounted when it lands.
  await waitFor(() => {
    loadExistingImages();
    expect(drawing("Companion")).toBe(false);
  });
});
