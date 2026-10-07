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
it.each([false, true])("keeps two versions and moves selection across repeated restores (alternate: %s)", async (alternate) => {
  const user = userEvent.setup();
  mount();
  const open = await screen.findByRole("button", { name: "Review & adjust · Professor Angell’s office" });
  if (alternate) await user.click(screen.getByRole("button", { name: "Open image · At night" }));
  else await user.click(open);
  const dialog = screen.getByRole("dialog");
  const history = await screen.findByRole("region", { name: "Versions" });
  const current = within(history).getByRole("button", { name: "Selected version v2", pressed: true });
  expect(current).toHaveProperty("disabled", true);
  expect(within(current).getByText("Selected")).toBeTruthy();
  expect(within(dialog).queryByRole("button", { name: "Restore v2" })).toBeNull();
  await user.click(current);
  expect(server.writes).toEqual([]);
  const suffix = alternate ? "&state_id=night" : "";
  expect(server.reads).toContain(`/projects/demo/location-plate-versions?loc_id=office${suffix}`);
  for (const version of [1, 2, 1, 2]) {
    const pane = screen.getByTestId("image-modal-image-pane");
    const beforeImage = pane.querySelector("img")!.getAttribute("src");
    const beforeThumbnail = alternate ? screen.getByAltText("At night reference").getAttribute("src") : null;
    await user.click(within(screen.getByRole("region", { name: "Versions" })).getByRole("button", { name: `Restore v${version}` }));
    const selected = await screen.findByRole("button", { name: `Selected version v${version}`, pressed: true });
    expect(selected).toHaveProperty("disabled", true);
    const updatedHistory = screen.getByRole("region", { name: "Versions" });
    expect(within(updatedHistory).getByText("Versions (2)")).toBeTruthy();
    expect(within(updatedHistory).getAllByRole("button")).toHaveLength(2);
    expect(within(updatedHistory).getAllByRole("button", { pressed: true })).toHaveLength(1);
    expect(within(updatedHistory).queryByText("v3")).toBeNull();
    expect(within(updatedHistory).getByRole("button", { name: `Restore v${version === 1 ? 2 : 1}` })).toHaveProperty("disabled", false);
    await waitFor(() => expect(pane.querySelector("img")!.getAttribute("src")).not.toBe(beforeImage));
    if (alternate) expect(screen.getByAltText("At night reference").getAttribute("src")).not.toBe(beforeThumbnail);
  }
  expect(server.writes).toEqual([1, 2, 1, 2].map((version) => `/projects/demo/location-plate-versions/restore?loc_id=office&version=${version}${suffix}`));
  expect(screen.queryByRole("alertdialog")).toBeNull();
});

it.each([false, true])("shows image progress and the new version without restoring an old one (alternate: %s)", async (alternate) => {
  const user = userEvent.setup();
  server.currentVersion = 1;
  server.archivedVersions = 0;
  const client = mount();
  const open = await screen.findByRole("button", { name: "Review & adjust · Professor Angell’s office" });
  if (alternate) await user.click(screen.getByRole("button", { name: "Open image · At night" }));
  else await user.click(open);
  const pane = () => screen.getByTestId("image-modal-image-pane");
  const originalSrc = pane().querySelector("img")!.getAttribute("src");
  let admit!: (value: unknown) => void;
  server.submit.mockReturnValue(new Promise((resolve) => { admit = resolve; }));
  await user.type(screen.getByRole("textbox"), "Replace the desk with a round table.");
  await user.click(await screen.findByRole("button", { name: /REGENERATE WITH CHANGE.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "REGENERATE WITH CHANGE" }));
  expect(within(pane()).getByRole("status").textContent).toBe("DRAWING…");
  expect(pane().getAttribute("aria-busy")).toBe("true");
  expect(pane().querySelector("img")!.getAttribute("src")).toBe(originalSrc);

  const job: GenerationJob = {
    id: "location-change", project_name: "demo", kind: "location_plate_regen", label: "Office",
    payload: { loc_id: alternate ? "office:night" : "office" }, status: "queued", queue_position: 1,
    queued_at: new Date().toISOString(), started_at: null, finished_at: null, error: null,
  };
  server.jobs = [job];
  await act(async () => { admit({ job }); });
  await waitFor(() => expect(within(pane()).getByRole("status").textContent).toBe("QUEUED"));
  await user.keyboard("{Escape}");
  if (alternate) await user.click(screen.getByRole("button", { name: "Open image · At night" }));
  else await user.click(open);
  expect(within(pane()).getByRole("status").textContent).toBe("QUEUED");

  server.jobs = [{ ...job, status: "running", queue_position: null }];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "demo", "generation-jobs"] }); });
  await waitFor(() => expect(within(pane()).getByRole("status").textContent).toBe("DRAWING…"));
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
  expect(pane().querySelector("img")!.getAttribute("src")).not.toBe(originalSrc);
  expect(server.writes).toHaveLength(1);
  expect(server.writes[0]).toContain("instructed");
});
it("keeps history available after a restore failure and lets the user retry", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(await screen.findByRole("button", { name: "Review & adjust · Professor Angell’s office" }));
  server.fail = true;
  await user.click(await screen.findByRole("button", { name: "Restore v1" }));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be restored");
  server.fail = false;
  await user.click(screen.getByRole("button", { name: "Restore v1" }));
  await waitFor(() => expect(server.writes).toHaveLength(2));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
});

it("recovers a missing location card and modal using the successful live probe URL", async () => {
  const client = mount();
  const name = "Professor Angell’s office";
  const image = await screen.findByAltText(name);
  // Let the initial idle refresh settle before recording the failed request.
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  const failedSrc = image.getAttribute("src");
  fireEvent.error(image);
  expect(screen.getByText("NO PLATE IMAGE")).toBeTruthy();

  server.running = true;
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "demo", "status"] }); });
  const card = screen.getByRole("button", { name: `Open image · ${name}` });
  await waitFor(() => expect(card.querySelector("img")).not.toBeNull());
  const probe = card.querySelector("img")!;
  vi.useFakeTimers();
  try {
    fireEvent.error(probe);
    act(() => vi.advanceTimersByTime(5_000));
    const successfulSrc = card.querySelector("img")!.getAttribute("src");
    expect(successfulSrc).not.toBe(failedSrc);
    fireEvent.load(card.querySelector("img")!);
    expect(screen.getByAltText(name).getAttribute("src")).toBe(successfulSrc);
    fireEvent.load(screen.getByAltText(name));
    fireEvent.click(card);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByText("NO PLATE IMAGE")).toBeNull();
    expect(within(dialog).getByAltText(name).getAttribute("src")).toBe(successfulSrc);
  } finally {
    vi.useRealTimers();
  }
});
