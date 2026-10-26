import { render, screen, within, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CastRoom } from "../pages/rooms/CastRoom";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({ submit: vi.fn(), estimates: [] as string[], uploads: [] as string[], supportsReferences: true, kind: "location" as "character" | "location" }));
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    if (options?.method === "POST" && options.body instanceof FormData) {
      const image = options.body.get("image") as File;
      server.uploads.push(path);
      return { upload_id: "a".repeat(32), label: image.name, image_path: `reference_uploads/${"a".repeat(32)}.png` };
    }
    if (options?.method === "POST") {
      server.submit(path, options.body ? JSON.parse(options.body as string) : null);
      throw new Error("Provider unavailable. Try again.");
    }
    if (path.includes("/jobs")) return { jobs: [] };
    if ((path.includes("story_bible") || path.includes("story-bible"))) {
      const office = { id: "office", name: "Boston study", visual_anchor: "Old furnishings", appearance_states: [{ id: "night", label: "At night", visual_anchor: "Old furnishings, nighttime", visually_significant: true, baseline_affect: null }] };
      const other = { id: "other", name: "Providence office", visual_anchor: "Brick walls", appearance_states: [] };
      return server.kind === "character"
        ? { characters: [{ ...office, age_range: "adult", gender: "male", distinguishing_features: [], relationships: [], default_outfit: "" }], props: [], locations: [other], scenes: [] }
        : { characters: [], props: [], locations: [office, other], scenes: [] };
    }
    if (path.includes("estimate")) {
      server.estimates.push(path);
      const cost = { estimate_credits: 4, reserved_credits: 6, confidence: "variable" };
      return { ...cost, instruction_estimate: cost, reference_assets_supported: server.supportsReferences };
    }
    if (path.includes("versions")) return { versions: [] };
    return {};
  },
}));
const clients: QueryClient[] = [];
afterEach(() => { clients.forEach((c) => c.clear()); clients.length = 0; server.submit.mockClear(); server.estimates = []; server.uploads = []; server.supportsReferences = true; server.kind = "location"; });
/** Mounts the room with the Boston study on the stage, as a character or a place. */
async function mount(kind: "character" | "location") {
  server.kind = kind;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/project/demo/cast"]}><I18nProvider>
    <Routes><Route path="/project/:id/cast" element={<CastRoom />} /></Routes>
  </I18nProvider></MemoryRouter></QueryClientProvider>);
  await screen.findByRole("complementary", { name: "Boston study" });
}
const looks = () => within(screen.getByRole("group", { name: "Looks" }));
const changeBox = () => screen.getByRole("textbox", { name: "Make a change" });
it.each(["character", "location"] as const)("edits only the selected %s appearance and sends reference attachments after confirmation", async (kind) => {
  const user = userEvent.setup();
  await mount(kind);
  await user.click(looks().getByRole("button", { name: "At night" }));
  await user.type(changeBox(), "Use the attached office’s window design, keeping this room’s layout.");
  expect(screen.getByText("Add a reference").closest("details")?.open).toBe(false);
  await user.click(screen.getByText("Add a reference"));
  const select = await screen.findByRole("combobox", { name: "Or choose one from this project" });
  await screen.findByRole("option", { name: "Providence office" });
  await user.selectOptions(select, JSON.stringify(["location", "other", null]));
  // A second attachment can be added and removed without changing the request text.
  await user.selectOptions(select, JSON.stringify([kind, "office", null]));
  expect(screen.getAllByRole("button", { name: /^Remove reference/ })).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "Remove reference · Boston study" }));
  expect(screen.getAllByRole("button", { name: /^Remove reference/ })).toHaveLength(1);
  expect(screen.queryByText("Make distinct from")).toBeNull();
  await user.click(await screen.findByRole("button", { name: /Redraw with change.*credits/ }));
  expect(server.submit).not.toHaveBeenCalled();
  expect(within(screen.getByRole("alertdialog")).getByText("Providence office")).toBeTruthy();
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Redraw with change" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(1));
  expect(server.submit.mock.calls[0]).toEqual([
    `/projects/demo/${kind === "character" ? "characters" : "locations"}/office/states/night/regenerate-instructed`,
    { instruction: "Use the attached office’s window design, keeping this room’s layout.", reference_assets: [{ asset_type: "location", asset_id: "other" }] },
  ]);
  expect(server.estimates.some((path) => path.includes("reference_count=1"))).toBe(true);
  expect((await screen.findByRole("alert")).textContent).toContain("Provider unavailable");
  // Leaving the look and coming back keeps the submitted direction and its attachments.
  await user.click(looks().getByRole("button", { name: "Main" }));
  await user.click(looks().getByRole("button", { name: "At night" }));
  expect((changeBox() as HTMLTextAreaElement).value).toBe("Use the attached office’s window design, keeping this room’s layout.");
  expect(within(screen.getByRole("list", { name: "Attached references" })).getByText("Providence office")).toBeTruthy();
});
it("uploads any image as a reference and sends it with the correction", async () => {
  // The picker's accept filter is advisory; the handler must still reject other types.
  const user = userEvent.setup({ applyAccept: false });
  await mount("location");
  await user.click(looks().getByRole("button", { name: "At night" }));
  await user.type(changeBox(), "Use the lamp from my photo.");
  await user.click(screen.getByText("Add a reference"));
  const input = screen.getByRole("complementary", { name: "Boston study · At night" }).querySelector<HTMLInputElement>('input[type="file"]')!;
  await user.upload(input, new File(["gif"], "lamp.gif", { type: "image/gif" }));
  expect((await screen.findByRole("alert")).textContent).toContain("PNG, JPG, or WebP");
  expect(server.uploads).toHaveLength(0);
  await user.upload(input, new File(["png"], "lamp.png", { type: "image/png" }));
  const attached = await screen.findByRole("list", { name: "Attached references" });
  expect(within(attached).getByText("lamp.png")).toBeTruthy();
  expect(attached.querySelector("img")?.getAttribute("src")).toBe(`/api/projects/demo/cast/reference-uploads/${"a".repeat(32)}`);
  await user.click(await screen.findByRole("button", { name: /Redraw with change.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Redraw with change" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(1));
  expect(server.submit.mock.calls[0][1]).toEqual({ instruction: "Use the lamp from my photo.", reference_assets: [{ upload_id: "a".repeat(32) }] });
});
it("opens a missing location appearance and offers a deliberate individual generation", async () => {
  const user = userEvent.setup();
  await mount("location");
  fireEvent.error(looks().getByRole("button", { name: "At night" }).querySelector("img")!);
  await user.click(looks().getByRole("button", { name: "At night" }));
  // The look's full-size image is missing too.
  fireEvent.error(screen.getByAltText("Boston study · At night"));
  await user.click(await screen.findByRole("button", { name: /Draw this image.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Draw this image" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(1));
  expect(server.submit.mock.calls[0][0]).toBe("/projects/demo/locations/office/states/night/regenerate");
});

it("does not offer reference attachments when the running backend lacks support", async () => {
  const user = userEvent.setup();
  server.supportsReferences = false;
  await mount("location");
  await user.click(looks().getByRole("button", { name: "At night" }));
  await screen.findByRole("button", { name: /Try another version.*credits/ });
  expect(screen.queryByText("Add a reference")).toBeNull();
  expect(server.submit).not.toHaveBeenCalled();
});
