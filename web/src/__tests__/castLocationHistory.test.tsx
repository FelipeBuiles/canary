import { act, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CastRoom } from "../pages/rooms/CastRoom";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({ reads: [] as string[], writes: [] as string[], fail: false, running: false }));
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      server.writes.push(path);
      if (server.fail) throw new Error("The image could not be restored. Try again.");
      return { versions: [] };
    }
    server.reads.push(path);
    if (path.includes("/jobs")) return { jobs: [] };
    if (path.includes("story_bible") || path.includes("story-bible")) return {
      characters: [], props: [], locations: [{ id: "office", name: "Professor Angell’s office", visual_anchor: "Oak walls and a gas lamp", mood: "scholarly",
        appearance_states: [{ id: "night", label: "At night", visual_anchor: "Oak walls at night", visually_significant: true }] }],
    };
    if (path.endsWith("/status")) return { style_selected: true, stages: { cast: { status: server.running ? "running" : "complete" } } };
    if (path.includes("estimate")) return { estimate_credits: 4, reserved_credits: 6, confidence: "variable", reference_assets_supported: true };
    if (path.includes("location-plate-versions")) return { has_history: true, versions: [
      { version: 1, image_path: "plates/versions/office/v001.png" },
      { version: 2, current: true, image_path: "plates/office.png" },
    ] };
    if (path.endsWith(".meta.json")) return null;
    if (path.includes("balance")) return { balance_credits: 100 };
    return {};
  },
}));
const clients: QueryClient[] = [];
afterEach(() => { clients.forEach((c) => c.clear()); clients.length = 0; server.reads = []; server.writes = []; server.fail = false; server.running = false; });
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/project/demo/cast"]}><I18nProvider><Routes>
    <Route path="/project/:id/cast" element={<CastRoom />} />
  </Routes></I18nProvider></MemoryRouter></QueryClientProvider>);
  return client;
}
it.each([false, true])("shows and restores the selected location version (alternate: %s)", async (alternate) => {
  const user = userEvent.setup();
  mount();
  const open = await screen.findByRole("button", { name: "Review & adjust · Professor Angell’s office" });
  if (alternate) await user.click(screen.getByRole("button", { name: "Open image · At night" }));
  else await user.click(open);
  const dialog = screen.getByRole("dialog");
  await screen.findByText(/PREVIOUS VERSIONS/);
  const restore = within(dialog).getByRole("button", { name: "Restore v1" });
  expect(within(dialog).queryByRole("button", { name: "Restore v2" })).toBeNull();
  const suffix = alternate ? "&state_id=night" : "";
  expect(server.reads).toContain(`/projects/demo/location-plate-versions?loc_id=office${suffix}`);
  const beforeImages = Array.from(dialog.querySelectorAll("img")).map((img) => img.src);
  const beforeThumbnail = alternate ? screen.getByAltText("At night reference").getAttribute("src") : null;
  await user.click(restore);
  await waitFor(() => expect(server.writes).toEqual([`/projects/demo/location-plate-versions/restore?loc_id=office&version=1${suffix}`]));
  await waitFor(() => expect(Array.from(dialog.querySelectorAll("img")).map((img) => img.src)).not.toEqual(beforeImages));
  if (alternate) expect(screen.getByAltText("At night reference").getAttribute("src")).not.toBe(beforeThumbnail);
  expect(screen.queryByRole("alertdialog")).toBeNull();
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
