import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { OutdatedReferences } from "../components/story/OutdatedReferences";
import type { ReferenceFreshness } from "../api/storyBible";
import type { StageStatus, StoryBible } from "../types/api";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string }[],
  references: [] as ReferenceFreshness[],
}));

vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    server.calls.push({ path, method });
    if (path.endsWith("/cast/freshness")) return { references: server.references };
    if (method === "POST" && path.endsWith("/cast/reopen")) return { reopened: true, references: server.references };
    if (method === "POST" && path.endsWith("/cast/references/keep")) return { references: server.references };
    throw new Error(`Unexpected fixture API: ${method} ${path}`);
  },
}));

afterEach(() => { server.calls = []; server.references = []; });

const bible = {
  characters: [{ id: "ines", name: "Ines", appearance_states: [] }],
  locations: [],
  props: [{ id: "sphinx", name: "Wooden sphinx", appearance_states: [] }],
} as unknown as StoryBible;

function Search() {
  return <p data-testid="search">{useLocation().search}</p>;
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
  await screen.findByRole("heading", { name: "References to update" });
  expect(screen.getByText("Wooden sphinx").parentElement!.textContent).toContain("New, no image yet");
  expect(screen.getByText("Ines").parentElement!.textContent).toContain("Changed since its image");
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
  await screen.findByRole("heading", { name: "References to update" });
  await waitFor(() => expect(screen.getByTestId("search").textContent).toBe(""));
  expect(onResume).not.toHaveBeenCalled();
  expect(server.calls.some((call) => call.method === "POST")).toBe(false);
});

it("resumes a pending Cast directly from the update button", async () => {
  server.references = edited;
  const user = userEvent.setup();
  const onResume = renderReferences("/project/p1/cast", "pending");
  await user.click(await screen.findByRole("button", { name: "Update images" }));
  expect(onResume).toHaveBeenCalledTimes(1);
  expect(server.calls.some((call) => call.path.endsWith("/cast/reopen"))).toBe(false);
});
