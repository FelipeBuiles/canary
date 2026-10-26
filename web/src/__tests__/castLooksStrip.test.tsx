import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CastRoom } from "../pages/rooms/CastRoom";
import type { GenerationJob } from "../types/api";

const fixtures = vi.hoisted(() => ({ references: [] as unknown[], jobs: [] as unknown[], running: false }));
const afterFire = { id: "after_fire", label: "After the fire", visual_anchor: "Smoke-blackened stonework", baseline_affect: null, visually_significant: true };

vi.mock("../api/client", () => ({
  isNotFoundError: () => false,
  isInsufficientCreditsError: () => false,
  apiFetch: async (path: string) => {
    if (path.endsWith("/cast/freshness")) return { references: fixtures.references };
    if (path.includes("/jobs")) return { jobs: fixtures.jobs };
    if (path.includes("story_bible") || path.includes("story-bible")) return {
      characters: [{ id: "char_1", name: "Marla", visual_anchor: "Soot on her cheeks", age_range: "adult", gender: "female",
        distinguishing_features: [], relationships: [], default_outfit: "", appearance_states: [afterFire] }],
      locations: ["loc_1", "loc_2"].map((id) => ({ id, name: `Keep ${id.slice(-1)}`, visual_anchor: "Stone walls", time_of_day: "day", mood: "grim", appearance_states: [afterFire] })),
      props: [], scenes: [],
    };
    if (path.endsWith("/status")) return { style_selected: true, stages: { cast: { status: fixtures.running ? "running" : "complete" } } };
    return { versions: [] };
  },
}));
afterEach(() => { fixtures.references = []; fixtures.jobs = []; fixtures.running = false; });

function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={client}><MemoryRouter initialEntries={["/project/demo/cast"]}><I18nProvider>{children}</I18nProvider></MemoryRouter></QueryClientProvider>;
}
async function mount() {
  render(<Providers><Routes><Route path="/project/:id/cast" element={<CastRoom />} /></Routes></Providers>);
  await screen.findByRole("complementary", { name: "Marla" });
}
const tile = () => within(screen.getByRole("group", { name: "Looks" })).getByRole("button", { name: "After the fire" });
const tileState = () => document.getElementById(tile().getAttribute("aria-describedby") ?? "")?.textContent;

it("keeps two places with the same look id independent on the strip and the stage", async () => {
  const user = userEvent.setup();
  await mount();
  for (const id of ["loc_1", "loc_2"]) {
    await user.click(screen.getByRole("button", { name: `Keep ${id.slice(-1)}` }));
    expect(tile().querySelector("img")!.getAttribute("src")).toContain(`/api/projects/demo/thumbnails/thumbnail/plates/${id}/states/after_fire.png?t=`);
    await user.click(tile());
    expect(screen.getByAltText(`Keep ${id.slice(-1)} · After the fire`).getAttribute("src"))
      .toContain(`/api/projects/demo/files/plates/${id}/states/after_fire.png?t=`);
  }
});

it("shows a look that has no image yet as drawing while Cast runs", async () => {
  fixtures.running = true;
  await mount();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  fireEvent.error(tile().querySelector("img")!);
  expect(tileState()).toBe("Drawing…");
});

it("marks a look drawn from an older main image as out of date", async () => {
  fixtures.references = [
    { kind: "characters", entity_id: "char_1", state_id: "after_fire", status: "outdated", reason: "parent_redrawn" },
  ];
  await mount();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  expect(tileState()).toBe("Out of date");
  // The stamp on the art, and the description read with the tile.
  expect(within(tile()).getAllByText("Out of date")).toHaveLength(2);
  await userEvent.click(tile());
  expect(screen.getByText("Drawn from an older Marla")).toBeTruthy();
});

it("shows looks as drawing while their main image's job redraws them", async () => {
  const job: Partial<GenerationJob> = { id: "redraw", project_name: "demo", kind: "character_ref_regen", label: "Marla",
    payload: { char_id: "char_1", with_looks: ["after_fire"] }, status: "running", queue_position: null,
    queued_at: new Date().toISOString(), started_at: new Date().toISOString(), finished_at: null, error: null };
  fixtures.jobs = [job];
  await mount();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  expect(tileState()).toBe("Drawing…");
});
