import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CastRoom } from "../pages/rooms/CastRoom";
import type { GenerationJob } from "../types/api";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({ jobs: [] as GenerationJob[], submit: vi.fn(), castStatus: "complete" }));
const anchor = "1cat, tortoiseshell persian cat, flat face, fluffy fur, black fur, beige fur, white fur";
const readable = "Tortoiseshell persian cat, flat face, fluffy fur, black fur, beige fur, white fur.";
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    if (path.includes("regen-ref-instructed")) return server.submit(JSON.parse(options!.body as string));
    if (path.includes("/jobs")) return { jobs: server.jobs };
    if (path.includes("story_bible") || path.includes("story-bible")) return {
      characters: [{ id: "cat", name: "Companion", visual_anchor: anchor, age_range: "adult", gender: "female", distinguishing_features: ["fluffy fur"], relationships: [], appearance_states: [], default_outfit: "" }], locations: [], props: [],
    };
    if (path.endsWith("/status")) return { style_selected: true, stages: { cast: { status: server.castStatus } } };
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
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; server.jobs = []; server.submit.mockReset(); server.castStatus = "complete"; });
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
  expect(await screen.findByText(readable)).toBeTruthy();
  // Internal model tags never appear in the author-facing identity view.
  const identity = within(screen.getByRole("region", { name: "VISUAL ANCHOR" }));
  expect(identity.getByText(readable)).toBeTruthy();
  expect(identity.queryByText(anchor)).toBeNull();
  expect(identity.queryByText("Prompt tags")).toBeNull();
  const draft = "Restore the canonical cat anatomy.";
  await user.type(screen.getByRole("textbox"), draft);
  await user.click(await screen.findByRole("button", { name: /Redraw with change.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Redraw with change" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(1));
  expect(within(screen.getByRole("region", { name: "References" })).getByRole("status").textContent).toContain("Drawing Companion…");
  expect(screen.getByRole("button", { name: "Companion" }).hasAttribute("disabled")).toBe(false);
  expect(screen.queryByText("Last change applied")).toBeNull();
  view.unmount();
  view = mount(client);
  expect(await screen.findByText(readable)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Companion" }).hasAttribute("disabled")).toBe(false);
  const job: GenerationJob = { id: "correction", project_name: "fixture", kind: "character_ref_regen", label: "Companion", payload: { char_id: "cat", instruction: draft }, status: "queued", queue_position: 1, queued_at: new Date().toISOString(), started_at: null, finished_at: null, error: null };
  server.jobs = [job];
  await act(async () => { admit({ status: "queued", char_id: "cat", job }); });
  const reason = "The requested change contradicts the canonical anchor.";
  server.jobs = [{ ...job, status: "failed", error: reason, user_message: reason }];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "fixture", "generation-jobs"] }); });
  expect((await screen.findByRole("alert")).textContent).toContain(reason);
  view.unmount();
  mount(client);
  expect((await screen.findByRole("alert")).textContent).toContain(reason);
  expect((screen.getByRole("textbox", { name: "Make a change" }) as HTMLTextAreaElement).value).toBe(draft);
  expect(within(screen.getByRole("region", { name: "References" })).queryByRole("status")).toBeNull();
  expect(screen.queryByText("Last change applied")).toBeNull();
  server.submit.mockResolvedValue({ status: "queued", char_id: "cat", job: { ...job, id: "recovery", queued_at: new Date(Date.now() + 1000).toISOString() } });
  await user.click(screen.getByRole("button", { name: /Redraw with change.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Redraw with change" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("Last change applied")).toBeNull();
});

it("queues a character change while Cast is generating other references", async () => {
  server.castStatus = "running";
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const job: GenerationJob = { id: "fix", project_name: "fixture", kind: "character_ref_regen", label: "Companion", payload: { char_id: "cat" }, status: "queued", queue_position: 2, queued_at: new Date().toISOString(), started_at: null, finished_at: null, error: null };
  server.submit.mockResolvedValue({ status: "queued", char_id: "cat", job });
  const user = userEvent.setup();
  mount(client);
  await screen.findByRole("button", { name: "Companion" });
  expect(document.querySelector("footer")).toBeNull();
  expect(screen.queryByRole("button", { name: /Rerun cast/ })).toBeNull();
  await user.type(screen.getByRole("textbox", { name: "Make a change" }), "Give her a darker tail.");
  await user.click(await screen.findByRole("button", { name: /Redraw with change.*credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Redraw with change" }));
  await waitFor(() => expect(server.submit).toHaveBeenCalledWith({ char_id: "cat", instruction: "Give her a darker tail.", reference_assets: [] }));
  expect(within(screen.getByRole("region", { name: "REGENERATE IMAGE · Companion" })).getAllByRole("button", { name: "Queued" })).toHaveLength(2);
});
