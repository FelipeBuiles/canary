import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { OutdatedReferences } from "../components/story/OutdatedReferences";
import type { ReferenceFreshness } from "../api/storyBible";
import type { GenerationJob, StageStatus, StoryBible } from "../types/api";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string }[],
  references: [] as ReferenceFreshness[],
  jobs: [] as GenerationJob[],
}));

vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    server.calls.push({ path, method });
    if (path.endsWith("/cast/freshness")) return { references: server.references };
    if (path.endsWith("/jobs")) return { jobs: server.jobs, current_reference_style_hash: "" };
    if (method === "POST" && path.endsWith("/cast/reopen")) return { reopened: true, references: server.references };
    if (method === "POST" && path.endsWith("/cast/references/keep")) return { references: server.references };
    if (path.includes("/asset-regen-estimate")) {
      return { estimate_credits: 4, reserved_credits: null, reservation_multiplier: 1, confidence: "low_variance" };
    }
    if (method === "POST" && path.includes("/regen-state-ref")) {
      const look = new URLSearchParams(path.split("?")[1]).get("state_id");
      return { status: "queued", char_id: "ines", job: queued(`job-${look}`, { char_id: `ines:${look}` }) };
    }
    throw new Error(`Unexpected fixture API: ${method} ${path}`);
  },
}));

afterEach(() => { server.calls = []; server.references = []; server.jobs = []; });

function queued(id: string, payload: Record<string, unknown>): GenerationJob {
  return { id, kind: "character_ref_regen", status: "queued", payload, queued_at: new Date().toISOString() } as GenerationJob;
}

const bible = {
  characters: [{ id: "ines", name: "Ines", appearance_states: [
    { id: "storm", label: "Storm gear" }, { id: "wed", label: "Wedding dress" },
  ] }],
  locations: [],
  props: [{ id: "sphinx", name: "Wooden sphinx", appearance_states: [] }],
} as unknown as StoryBible;

function Search() {
  return <p data-testid="search">{useLocation().search}</p>;
}

/** The references sit behind one notice chip; opening it shows the list. */
async function openList() {
  fireEvent.click(await screen.findByRole("button", { expanded: false, name: /needs a new image|references to update/ }));
  await screen.findByRole("heading", { name: "References to update" });
}

function renderReferences(entry: string, castStatus: StageStatus, onResume = vi.fn(), resumeDisabled = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><I18nProvider><MemoryRouter initialEntries={[entry]}>
    <OutdatedReferences project="p1" bible={bible} castStatus={castStatus} onResume={onResume} resumeDisabled={resumeDisabled} />
    <Search />
  </MemoryRouter></I18nProvider></QueryClientProvider>);
  return onResume;
}

const edited: ReferenceFreshness[] = [
  { kind: "characters", entity_id: "ines", state_id: null, status: "outdated" },
  { kind: "props", entity_id: "sphinx", state_id: null, status: "missing" },
];

it("lists new and changed references, offering to keep only the changed ones", async () => {
  server.references = edited;
  renderReferences("/project/p1/cast", "complete");
  await openList();
  expect(screen.getByRole("listitem", { name: "Wooden sphinx" }).textContent).toContain("New, no image yet");
  expect(screen.getByRole("listitem", { name: "Ines" }).textContent).toContain("Changed since its image");
  expect(screen.getAllByRole("button", { name: "Keep current image" })).toHaveLength(1);
  expect(server.calls.some((call) => call.method === "POST")).toBe(false);
});

it("reopens an approved Cast and opens its confirmation when arriving from the Story Bible", async () => {
  server.references = edited;
  const onResume = renderReferences("/project/p1/cast?references=update", "complete");
  await waitFor(() => expect(onResume).toHaveBeenCalledTimes(1));
  expect(server.calls.filter((call) => call.path.endsWith("/cast/reopen"))).toHaveLength(1);
  expect(screen.getByTestId("search").textContent).toBe("");
});

it("leaves the update to the author when Cast can't run yet", async () => {
  server.references = edited;
  const onResume = renderReferences("/project/p1/cast?references=update", "complete", vi.fn(), true);
  await openList();
  await waitFor(() => expect(screen.getByTestId("search").textContent).toBe(""));
  expect(onResume).not.toHaveBeenCalled();
  expect(server.calls.some((call) => call.method === "POST")).toBe(false);
});

it("resumes a pending Cast directly from the update button", async () => {
  server.references = edited;
  const user = userEvent.setup();
  const onResume = renderReferences("/project/p1/cast", "pending");
  await openList();
  await user.click(await screen.findByRole("button", { name: "Update images" }));
  expect(onResume).toHaveBeenCalledTimes(1);
  expect(server.calls.some((call) => call.path.endsWith("/cast/reopen"))).toBe(false);
});

const redrawnLooks: ReferenceFreshness[] = [
  { kind: "characters", entity_id: "ines", state_id: null, status: "current" },
  { kind: "characters", entity_id: "ines", state_id: "storm", status: "outdated", reason: "parent_redrawn" },
  { kind: "characters", entity_id: "ines", state_id: "wed", status: "outdated", reason: "parent_redrawn" },
];

it("groups looks drawn from a redrawn main image and never sends them to the Story Bible", async () => {
  server.references = redrawnLooks;
  renderReferences("/project/p1/cast", "awaiting_review");
  await openList();
  const group = await screen.findByRole("listitem", { name: "Ines" });
  expect(group.textContent).toContain("Its main image was redrawn, so these 2 looks were drawn from the previous one:");
  expect(group.textContent).toContain("Storm gear · Wedding dress");
  expect(screen.queryByRole("link", { name: "Edit details" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Keep current image" })).toBeNull();
  expect(await screen.findByRole("button", { name: /Redraw looks/ })).toBeTruthy();
});

it("redraws a group's looks one job each, only after a priced confirmation", async () => {
  server.references = redrawnLooks;
  const user = userEvent.setup();
  renderReferences("/project/p1/cast", "awaiting_review");
  await openList();
  const redraw = await screen.findByRole("button", { name: /Redraw looks.*8 credits/ });
  await user.click(redraw);
  expect(server.calls.some((call) => call.method === "POST")).toBe(false);
  const drawer = screen.getByRole("alertdialog");
  expect(within(drawer).getByText("~8 credits")).toBeTruthy();
  await user.click(within(drawer).getByRole("button", { name: "Redraw looks" }));
  await waitFor(() => expect(server.calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual([
    expect.stringContaining("char_id=ines&state_id=storm"),
    expect.stringContaining("char_id=ines&state_id=wed"),
  ]));
});

it("keeps every redrawn look of a group at once", async () => {
  server.references = redrawnLooks;
  const user = userEvent.setup();
  renderReferences("/project/p1/cast", "awaiting_review");
  await openList();
  await user.click(await screen.findByRole("button", { name: "Keep looks as they are" }));
  await waitFor(() => expect(server.calls.filter((call) => call.path.endsWith("/cast/references/keep"))).toHaveLength(2));
});

it("stops offering looks once their redraw is queued, and shows them redrawing", async () => {
  server.references = redrawnLooks;
  const user = userEvent.setup();
  renderReferences("/project/p1/cast", "awaiting_review");
  await openList();
  await user.click(await screen.findByRole("button", { name: /Redraw looks.*8 credits/ }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Redraw looks" }));

  const status = await screen.findByRole("status");
  expect(status.textContent).toContain("Redrawing: Storm gear · Wedding dress");
  expect(screen.queryByRole("button", { name: /Redraw looks/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "Keep looks as they are" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Update images" })).toBeNull();
});

it("treats looks a main-image job brings along as already redrawing", async () => {
  server.references = redrawnLooks;
  server.jobs = [queued("main", { char_id: "ines", with_looks: ["storm"] })];
  renderReferences("/project/p1/cast", "awaiting_review");
  await openList();
  const status = await screen.findByRole("status");
  expect(status.textContent).toContain("Redrawing: Storm gear");
  const group = screen.getByRole("listitem", { name: "Ines" });
  expect(group.textContent).toContain("this look was drawn from the previous one: Wedding dress");
});
