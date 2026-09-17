import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { GenerationJob } from "../types/api";
import type { LetteringTranslationEstimate } from "../api/lettering";

const server = vi.hoisted(() => ({ estimate: vi.fn(), translate: vi.fn(), jobs: [] as GenerationJob[], balance: 100 }));
vi.mock("../api/lettering", () => ({
  getLetteringTranslationEstimate: server.estimate,
  translateProjectLettering: server.translate,
}));
vi.mock("../api/queries", () => ({
  useGenerationJobs: (project: string) => useQuery({ queryKey: ["project", project, "generation-jobs", []], queryFn: async () => ({ jobs: server.jobs }) }),
  useCreditBalance: () => useQuery({ queryKey: ["credits", "balance"], queryFn: async () => ({ balance_credits: server.balance }) }),
}));
vi.mock("../store/insufficientCredits", () => ({ maybeShowInsufficientCredits: vi.fn() }));

import { ProjectLetteringLanguage } from "../components/lettering/ProjectLetteringLanguage";

const estimate: LetteringTranslationEstimate = {
  estimate_credits: 12, reserved_credits: 18, reservation_multiplier: 1.5, confidence: "variable", funding: "api",
  target_locale: "es", snapshot_sha256: "saved-snapshot", page_count: 2, element_count: 5, translate_count: 3, preserved_target_count: 2,
};
const job: GenerationJob = {
  id: "translation", project_name: "demo", kind: "lettering_translation", label: "Translation", payload: { target_locale: "es" },
  status: "queued", queue_position: 1, queued_at: "2099-01-01T00:00:00Z", started_at: null, finished_at: null, error: null,
};
const clients: QueryClient[] = [];
beforeEach(() => {
  server.jobs = [];
  server.balance = 100;
  server.estimate.mockReset().mockResolvedValue(estimate);
  server.translate.mockReset().mockResolvedValue({ job });
});
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; });

function setup(onApplied = vi.fn(async () => {}), disabled = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const tree = (blocked = disabled) => <QueryClientProvider client={client}><I18nProvider>
    <ProjectLetteringLanguage project="demo" disabled={blocked} onApplied={onApplied} />
  </I18nProvider></QueryClientProvider>;
  return { client, onApplied, tree, ...render(tree()) };
}

async function chooseLanguage() {
  const disclosure = screen.getByText("Project language", { selector: "summary" }).parentElement!;
  disclosure.setAttribute("open", "");
  fireEvent(disclosure, new Event("toggle"));
  fireEvent.change(screen.getByLabelText("Translate to"), { target: { value: "es" } });
  await waitFor(() => expect(screen.getByRole("button", { name: /Translate project/ })).toHaveProperty("disabled", false));
}

async function confirm() {
  fireEvent.click(screen.getByRole("button", { name: /Translate project/ }));
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Translate project" }));
}

it("estimates selection without spending, and submits the saved snapshot only after explicit confirmation", async () => {
  const view = setup();
  await chooseLanguage();
  expect(server.translate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Translate project/ }));
  const dialog = within(screen.getByRole("alertdialog"));
  expect(dialog.getByLabelText("about 12 credits")).toBeTruthy();
  expect(dialog.getByText(/2 existing translations/)).toBeTruthy();
  expect(server.translate).not.toHaveBeenCalled();
  view.rerender(view.tree(true));
  expect(dialog.getByRole("button", { name: "Translate project" })).toHaveProperty("disabled", true);
  view.rerender(view.tree(false));
  fireEvent.click(dialog.getByRole("button", { name: "Translate project" }));
  await screen.findByText(/Project translation queued/);
  expect(server.translate).toHaveBeenCalledWith("demo", { target_locale: "es", expected_snapshot_sha256: "saved-snapshot" });
  expect(view.onApplied).not.toHaveBeenCalled();
});

it("requires enough credits for the hold, not just the estimated final cost", async () => {
  server.balance = 12;
  setup();
  const disclosure = screen.getByText("Project language", { selector: "summary" }).parentElement!;
  disclosure.setAttribute("open", "");
  fireEvent(disclosure, new Event("toggle"));
  fireEvent.change(screen.getByLabelText("Translate to"), { target: { value: "es" } });
  await screen.findByText(/Not enough credits for the temporary hold/);
  expect(screen.getByRole("button", { name: /Translate project/ })).toHaveProperty("disabled", true);
  expect(server.translate).not.toHaveBeenCalled();
});

it("invalidates every page and credits on completion but does not claim application if the editor refresh fails", async () => {
  server.jobs = [{ ...job, status: "running" }];
  const onApplied = vi.fn<() => Promise<void>>().mockRejectedValue(new Error("Local draft changed"));
  const view = setup(onApplied);
  await screen.findByText(/Translating project/);
  view.client.setQueryData(["page-lettering", "demo", 1], { revision: 1 });
  view.client.setQueryData(["page-lettering", "demo", 2], { revision: 1 });
  view.client.setQueryData(["credits", "history"], []);
  server.jobs = [{ ...job, status: "complete" }];
  await act(async () => { await view.client.invalidateQueries({ queryKey: ["project", "demo", "generation-jobs"] }); });
  await screen.findByText(/The job finished, but the editor could not refresh/);
  expect(screen.queryByText(/Project language applied/)).toBeNull();
  expect(view.client.getQueryState(["page-lettering", "demo", 1])?.isInvalidated).toBe(true);
  expect(view.client.getQueryState(["page-lettering", "demo", 2])?.isInvalidated).toBe(true);
  expect(view.client.getQueryState(["credits", "history"])?.isInvalidated).toBe(true);
  onApplied.mockResolvedValueOnce(undefined);
  fireEvent.click(screen.getByRole("button", { name: "Refresh lettering" }));
  await screen.findByText(/Project language applied/);
  expect(server.translate).not.toHaveBeenCalled();
});

it("keeps an unknown submission separate from another translation and explicitly replays its exact request", async () => {
  server.translate.mockRejectedValueOnce(new TypeError("Response lost"));
  setup();
  await chooseLanguage();
  await confirm();
  await screen.findByText(/The submission result is unknown/);
  expect(screen.getByLabelText("Translate to")).toHaveProperty("disabled", true);
  expect(server.translate).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Check submission" }));
  await screen.findByText(/Project translation queued/);
  expect(server.translate).toHaveBeenCalledTimes(2);
  expect(server.translate.mock.calls[1]).toEqual(server.translate.mock.calls[0]);
});
