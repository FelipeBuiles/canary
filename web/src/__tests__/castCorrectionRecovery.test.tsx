import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CastRoom } from "../pages/rooms/CastRoom";
import type { GenerationJob } from "../types/api";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({ jobs: [] as GenerationJob[], submit: vi.fn() }));
const anchor = "1cat, tortoiseshell persian cat, flat face, fluffy fur, black fur, beige fur, white fur";
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    if (path.includes("regen-ref-instructed")) return server.submit(JSON.parse(options!.body as string));
    if (path.includes("/jobs")) return { jobs: server.jobs };
    if (path.includes("story_bible") || path.includes("story-bible")) return {
      characters: [{ id: "cat", name: "Companion", visual_anchor: anchor, age_range: "adult", gender: "female", distinguishing_features: ["fluffy fur"], relationships: [], appearance_states: [], default_outfit: "" }], locations: [], props: [],
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
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; server.jobs = []; server.submit.mockReset(); });
function mount(client: QueryClient) {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/project/fixture/cast"]}><I18nProvider><Routes><Route path="/project/:id/cast" element={<CastRoom />} /></Routes></I18nProvider></MemoryRouter></QueryClientProvider>);
}
it("keeps canonical identity and a failed correction visible after closing and remounting, then permits deliberate recovery", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const user = userEvent.setup();
  // The app's ES2023 library target does not expose Promise.withResolvers.
  let admit!: (value: unknown) => void;
  const pending = new Promise<unknown>((resolve) => { admit = resolve; });
  server.submit.mockReturnValue(pending);
  let view = mount(client);
  expect(await screen.findByText(anchor)).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Open image · Companion" }));
  expect(within(screen.getByRole("region", { name: "VISUAL ANCHOR" })).getByText(anchor)).toBeTruthy();
  const draft = "Restore the canonical cat anatomy.";
  await user.type(screen.getByRole("textbox"), draft);
  await user.click(await screen.findByRole("button", { name: /REGENERATE WITH CHANGE.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "REGENERATE WITH CHANGE" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(1));
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button", { name: "Open image · Companion" }).hasAttribute("disabled")).toBe(true);
  expect(screen.queryByText("LAST CHANGE APPLIED")).toBeNull();
  view.unmount();
  view = mount(client);
  expect(await screen.findByText(anchor)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Open image · Companion" }).hasAttribute("disabled")).toBe(true);
  const job: GenerationJob = { id: "correction", project_name: "fixture", kind: "character_ref_regen", label: "Companion", payload: { char_id: "cat", instruction: draft }, status: "queued", queue_position: 1, queued_at: new Date().toISOString(), started_at: null, finished_at: null, error: null };
  server.jobs = [job];
  await act(async () => { admit({ status: "queued", char_id: "cat", job }); });
  const reason = "The requested change contradicts the canonical anchor.";
  server.jobs = [{ ...job, status: "failed", error: reason, user_message: reason }];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "fixture", "generation-jobs"] }); });
  expect((await screen.findByRole("alert")).textContent).toContain(reason);
  view.unmount();
  view = mount(client);
  expect((await screen.findByRole("alert")).textContent).toContain(reason);
  await user.click(screen.getByRole("button", { name: "Open image · Companion" }));
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(draft);
  expect(screen.queryByText("LAST CHANGE APPLIED")).toBeNull();
  server.submit.mockResolvedValue({ status: "queued", char_id: "cat", job: { ...job, id: "recovery", queued_at: new Date(Date.now() + 1000).toISOString() } });
  await user.click(screen.getByRole("button", { name: /REGENERATE WITH CHANGE.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "REGENERATE WITH CHANGE" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("LAST CHANGE APPLIED")).toBeNull();
});
