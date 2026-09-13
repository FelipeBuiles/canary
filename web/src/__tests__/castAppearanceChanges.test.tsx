import { render, screen, within, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { StateRefRow } from "../pages/rooms/CastRoom";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({ submit: vi.fn(), estimates: [] as string[], supportsReferences: true }));
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      server.submit(path, options.body ? JSON.parse(options.body as string) : null);
      throw new Error("Provider unavailable. Try again.");
    }
    if (path.includes("/jobs")) return { jobs: [] };
    if ((path.includes("story_bible") || path.includes("story-bible"))) return { characters: [], props: [], locations: [
      { id: "office", name: "Boston study", appearance_states: [{ id: "night", label: "At night", visually_significant: true }] },
      { id: "other", name: "Providence office", appearance_states: [] },
    ] };
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
afterEach(() => { clients.forEach((c) => c.clear()); clients.length = 0; server.submit.mockClear(); server.estimates = []; server.supportsReferences = true; });
function mount(kind: "character" | "location") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><I18nProvider><StateRefRow projectName="demo" entityId="office" kind={kind}
    stageRegenerating={false} refreshToken="current" states={[{ id: "night", label: "At night", visual_anchor: "Old furnishings, nighttime", visually_significant: true, baseline_affect: null }]} />
  </I18nProvider></QueryClientProvider>);
}
it.each(["character", "location"] as const)("edits only the selected %s appearance and sends reference attachments after confirmation", async (kind) => {
  const user = userEvent.setup();
  mount(kind);
  await user.click(screen.getByRole("button", { name: "Open image · At night" }));
  await user.type(screen.getByRole("textbox"), "Use the attached office’s window design, keeping this room’s layout.");
  expect(screen.getByText("Add a reference").closest("details")?.open).toBe(false);
  await user.click(screen.getByText("Add a reference"));
  const select = await screen.findByRole("combobox", { name: "Choose a reference" });
  await screen.findByRole("option", { name: "Providence office" });
  await user.selectOptions(select, JSON.stringify(["location", "other", null]));
  // A second attachment can be added and removed without changing the request text.
  await user.selectOptions(select, JSON.stringify(["location", "office", null]));
  expect(screen.getAllByRole("button", { name: /^Remove reference/ })).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "Remove reference · Boston study" }));
  expect(screen.getAllByRole("button", { name: /^Remove reference/ })).toHaveLength(1);
  expect(screen.queryByText("Make distinct from")).toBeNull();
  await user.click(await screen.findByRole("button", { name: /REGENERATE WITH CHANGE.*credits/ }));
  expect(server.submit).not.toHaveBeenCalled();
  expect(within(screen.getByRole("alertdialog")).getByText("Providence office")).toBeTruthy();
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "REGENERATE WITH CHANGE" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(1));
  expect(server.submit.mock.calls[0]).toEqual([
    `/projects/demo/${kind === "character" ? "characters" : "locations"}/office/states/night/regenerate-instructed`,
    { instruction: "Use the attached office’s window design, keeping this room’s layout.", reference_assets: [{ asset_type: "location", asset_id: "other" }] },
  ]);
  expect(server.estimates.some((path) => path.includes("reference_count=1"))).toBe(true);
  expect((await screen.findByRole("alert")).textContent).toContain("Provider unavailable");
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Open image · At night" }));
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Use the attached office’s window design, keeping this room’s layout.");
  expect(within(screen.getByRole("list", { name: "Attached references" })).getByText("Providence office")).toBeTruthy();
});
it("opens a missing location appearance and offers a deliberate individual generation", async () => {
  const user = userEvent.setup();
  mount("location");
  fireEvent.error(screen.getByAltText("At night reference"));
  await user.click(screen.getByRole("button", { name: "Review & adjust · At night" }));
  // The state sheet probe confirms the missing full-size asset.
  const images = screen.getByRole("dialog").querySelectorAll("img");
  images.forEach((image) => fireEvent.error(image));
  await user.click(await screen.findByRole("button", { name: /GENERATE IMAGE.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "GENERATE IMAGE" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(1));
  expect(server.submit.mock.calls[0][0]).toBe("/projects/demo/locations/office/states/night/regenerate");
});

it("does not offer reference attachments when the running backend lacks support", async () => {
  const user = userEvent.setup();
  server.supportsReferences = false;
  mount("location");
  await user.click(screen.getByRole("button", { name: "Open image · At night" }));
  await screen.findByRole("button", { name: /TRY ANOTHER VERSION.*credits/ });
  expect(screen.queryByText("Add a reference")).toBeNull();
  expect(server.submit).not.toHaveBeenCalled();
});
