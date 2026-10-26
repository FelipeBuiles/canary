import { act, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CastRoom } from "../pages/rooms/CastRoom";
import type { GenerationJob } from "../types/api";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({
  reads: [] as string[], writes: [] as string[], fail: false, running: false,
  jobs: [] as GenerationJob[], currentVersion: 2, archivedVersions: 1, submit: vi.fn(),
}));
function locationHistory(path: string) {
  const livePath = path.includes("state_id=night") ? "plates/office/states/night.png" : "plates/office.png";
  const archivePath = path.includes("state_id=night") ? "plates/office/states/versions/night" : "plates/versions/office";
  return {
    has_history: Math.max(server.currentVersion, server.archivedVersions) > 1,
    versions: Array.from({ length: Math.max(server.currentVersion, server.archivedVersions) }, (_, index) => {
      const version = index + 1;
      return { version, current: version === server.currentVersion,
        image_path: version <= server.archivedVersions ? `${archivePath}/v00${version}.png` : livePath };
    }),
  };
}
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      server.writes.push(path);
      if (path.includes("instructed")) return server.submit();
      if (server.fail) throw new Error("The image could not be restored. Try again.");
      server.archivedVersions = Math.max(server.archivedVersions, server.currentVersion);
      server.currentVersion = Number(new URL(path, "https://canary.test").searchParams.get("version"));
      return { versions: locationHistory(path).versions };
    }
    server.reads.push(path);
    if (path.includes("/jobs")) return { jobs: server.jobs };
    if (path.includes("story_bible") || path.includes("story-bible")) return {
      characters: [], props: [], locations: [{ id: "office", name: "Professor Angell’s office", visual_anchor: "Oak walls and a gas lamp", mood: "scholarly",
        appearance_states: [{ id: "night", label: "At night", visual_anchor: "Oak walls at night", visually_significant: true }] }],
    };
    if (path.endsWith("/status")) return { style_selected: true, stages: { cast: { status: server.running ? "running" : "complete" } } };
    if (path.includes("estimate")) {
      const cost = { estimate_credits: 4, reserved_credits: 6, confidence: "variable" };
      return { ...cost, instruction_estimate: cost, reference_assets_supported: true };
    }
    if (path.includes("location-plate-versions")) return locationHistory(path);
    if (path.endsWith(".meta.json")) return null;
    if (path.includes("balance")) return { balance_credits: 100 };
    return {};
  },
}));
const clients: QueryClient[] = [];
afterEach(() => {
  clients.forEach((c) => c.clear()); clients.length = 0;
  server.reads = []; server.writes = []; server.fail = false; server.running = false;
  server.jobs = []; server.currentVersion = 2; server.archivedVersions = 1; server.submit.mockReset();
});
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/project/demo/cast"]}><I18nProvider><Routes>
    <Route path="/project/:id/cast" element={<CastRoom />} />
  </Routes></I18nProvider></MemoryRouter></QueryClientProvider>);
  return client;
}
const name = "Professor Angell’s office";
const pane = () => screen.getByTestId("cast-stage");
const stageImage = () => pane().querySelector("img")!;
const lookTile = () => within(screen.getByRole("group", { name: "Looks" })).getByRole("button", { name: "At night" });
/** The office is the only reference, so it starts on the stage; the alternate is its night look. */
async function open(alternate: boolean) {
  const user = userEvent.setup();
  await screen.findByRole("complementary", { name });
  // Let the initial idle refresh settle; it reloads the stage image once.
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  if (alternate) await user.click(lookTile());
}

it.each([false, true])("keeps two versions and moves selection across repeated restores (alternate: %s)", async (alternate) => {
  const user = userEvent.setup();
  mount();
  await open(alternate);
  const history = await screen.findByRole("region", { name: "Versions" });
  const current = within(history).getByRole("button", { name: "Selected version v2", pressed: true });
  expect(current).toHaveProperty("disabled", true);
  expect(within(current).getByText(/In use/)).toBeTruthy();
  expect(within(history).queryByRole("button", { name: "Restore v2" })).toBeNull();
  await user.click(current);
  expect(server.writes).toEqual([]);
  const suffix = alternate ? "&state_id=night" : "";
  expect(server.reads).toContain(`/projects/demo/location-plate-versions?loc_id=office${suffix}`);
  for (const version of [1, 2, 1, 2]) {
    const beforeImage = stageImage().getAttribute("src");
    const beforeThumbnail = alternate ? lookTile().querySelector("img")!.getAttribute("src") : null;
    await user.click(within(screen.getByRole("region", { name: "Versions" })).getByRole("button", { name: `Restore v${version}` }));
    const selected = await screen.findByRole("button", { name: `Selected version v${version}`, pressed: true });
    expect(selected).toHaveProperty("disabled", true);
    const updatedHistory = screen.getByRole("region", { name: "Versions" });
    expect(within(updatedHistory).getByRole("heading").textContent).toBe("Versions · 2");
    expect(within(updatedHistory).getAllByRole("button")).toHaveLength(2);
    expect(within(updatedHistory).getAllByRole("button", { pressed: true })).toHaveLength(1);
    expect(within(updatedHistory).queryByText(/v3/)).toBeNull();
    expect(within(updatedHistory).getByRole("button", { name: `Restore v${version === 1 ? 2 : 1}` })).toHaveProperty("disabled", false);
    await waitFor(() => expect(stageImage().getAttribute("src")).not.toBe(beforeImage));
    if (alternate) expect(lookTile().querySelector("img")!.getAttribute("src")).not.toBe(beforeThumbnail);
  }
  expect(server.writes).toEqual([1, 2, 1, 2].map((version) => `/projects/demo/location-plate-versions/restore?loc_id=office&version=${version}${suffix}`));
  expect(screen.queryByRole("alertdialog")).toBeNull();
});

it.each([false, true])("shows image progress and the new version without restoring an old one (alternate: %s)", async (alternate) => {
  const user = userEvent.setup();
  server.currentVersion = 1;
  server.archivedVersions = 0;
  const client = mount();
  await open(alternate);
  const drawingLabel = `Drawing ${alternate ? "At night" : name}…`;
  const originalSrc = stageImage().getAttribute("src");
  let admit!: (value: unknown) => void;
  server.submit.mockReturnValue(new Promise((resolve) => { admit = resolve; }));
  await user.type(screen.getByRole("textbox", { name: "Make a change" }), "Replace the desk with a round table.");
  await user.click(await screen.findByRole("button", { name: /Redraw with change.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Redraw with change" }));
  expect(within(pane()).getByRole("status").textContent).toBe(drawingLabel);
  expect(pane().getAttribute("aria-busy")).toBe("true");
  // A redraw keeps the current image on the stage until the new one lands.
  expect(stageImage().getAttribute("src")).toBe(originalSrc);

  const job: GenerationJob = {
    id: "location-change", project_name: "demo", kind: "location_plate_regen", label: "Office",
    payload: { loc_id: alternate ? "office:night" : "office" }, status: "queued", queue_position: 1,
    queued_at: new Date().toISOString(), started_at: null, finished_at: null, error: null,
  };
  server.jobs = [job];
  await act(async () => { admit({ job }); });
  await waitFor(() => expect(within(pane()).getByRole("status").textContent).toBe("Queued"));
  // Leaving the view and coming back keeps the job's state.
  const strip = within(screen.getByRole("group", { name: "Looks" }));
  await user.click(strip.getByRole("button", { name: alternate ? "Main" : "At night" }));
  await user.click(alternate ? lookTile() : strip.getByRole("button", { name: "Main" }));
  expect(within(pane()).getByRole("status").textContent).toBe("Queued");

  server.jobs = [{ ...job, status: "running", queue_position: null }];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "demo", "generation-jobs"] }); });
  await waitFor(() => expect(within(pane()).getByRole("status").textContent).toBe(drawingLabel));
  server.currentVersion = 2;
  server.archivedVersions = 1;
  server.jobs = [{ ...job, status: "complete", queue_position: null, finished_at: new Date().toISOString() }];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "demo", "generation-jobs"] }); });
  const history = await screen.findByRole("region", { name: "Versions" });
  expect(within(history).getByRole("button", { name: "Restore v1" })).toHaveProperty("disabled", false);
  const current = within(history).getByRole("button", { name: "Selected version v2", pressed: true });
  expect(current).toHaveProperty("disabled", true);
  expect(current.querySelector("img")!.getAttribute("src")).toContain(alternate ? "/plates/office/states/night.png?" : "/plates/office.png?");
  expect(pane().getAttribute("aria-busy")).toBe("false");
  expect(within(pane()).queryByRole("status")).toBeNull();
  expect(stageImage().getAttribute("src")).not.toBe(originalSrc);
  expect(server.writes).toHaveLength(1);
  expect(server.writes[0]).toContain("instructed");
});
it("keeps history available after a restore failure and lets the user retry", async () => {
  const user = userEvent.setup();
  mount();
  await open(false);
  server.fail = true;
  await user.click(await screen.findByRole("button", { name: "Restore v1" }));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be restored");
  server.fail = false;
  await user.click(screen.getByRole("button", { name: "Restore v1" }));
  await waitFor(() => expect(server.writes).toHaveLength(2));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
});

it("recovers a missing location image using the successful live probe URL", async () => {
  const client = mount();
  await open(false);
  const image = screen.getByAltText(name);
  const failedSrc = image.getAttribute("src");
  fireEvent.error(image);
  expect(within(pane()).getByText("No image yet")).toBeTruthy();

  server.running = true;
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "demo", "status"] }); });
  await waitFor(() => expect(pane().querySelector("img")).not.toBeNull());
  const probe = pane().querySelector("img")!;
  vi.useFakeTimers();
  try {
    fireEvent.error(probe);
    act(() => vi.advanceTimersByTime(5_000));
    const successfulSrc = pane().querySelector("img")!.getAttribute("src");
    expect(successfulSrc).not.toBe(failedSrc);
    fireEvent.load(pane().querySelector("img")!);
    expect(within(pane()).queryByText("No image yet")).toBeNull();
    expect(within(pane()).getByAltText(name).getAttribute("src")).toBe(successfulSrc);
  } finally {
    vi.useRealTimers();
  }
});
