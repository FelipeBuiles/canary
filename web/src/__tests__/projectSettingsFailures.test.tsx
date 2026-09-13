import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type * as ClientApi from "../api/client";
import { I18nProvider } from "../i18n";
import { ProjectSettingsPage } from "../pages/ProjectSettingsPage";

const requests = vi.hoisted(() => ({ save: vi.fn(), remove: vi.fn(), config: vi.fn(), models: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...await importOriginal<typeof ClientApi>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    if (options?.method === "DELETE") return requests.remove();
    if (options?.method === "PATCH") return requests.save(JSON.parse(String(options.body)));
    if (path.includes("model-settings")) return requests.models();
    if (path.includes("config")) return requests.config() ?? { target_language: "en" };
    return { project_name: "My project", stages: {} };
  },
}));
const clients: QueryClient[] = [];
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; vi.clearAllMocks(); });
function Destination() {
  const location = useLocation();
  return <p role="status">Deleted {location.state?.projectDeleted}</p>;
}
function openSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/project/demo/settings"]}><I18nProvider><Routes><Route path="/project/:id/settings" element={<ProjectSettingsPage />} /><Route path="/" element={<Destination />} /></Routes></I18nProvider></MemoryRouter></QueryClientProvider>);
}

it("shows a failed save inline and announces a successful explicit reattempt", async () => {
  requests.save.mockRejectedValueOnce(new Error("Could not save project settings")).mockResolvedValue({ target_language: "fr" });
  const user = userEvent.setup();
  openSettings();
  const language = screen.getByRole("combobox", { name: "OUTPUT LANGUAGE" });
  await waitFor(() => expect((language as HTMLSelectElement).disabled).toBe(false));
  await user.selectOptions(language, "fr");
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not save project settings");
  expect(requests.save).toHaveBeenCalledTimes(1);
  await user.selectOptions(language, "fr");
  expect(await screen.findByRole("status")).toHaveProperty("textContent", "Settings saved.");
});

it("retains delete confirmation input on failure and only navigates after success", async () => {
  requests.remove.mockRejectedValueOnce(new Error("Project is still draining")).mockResolvedValue({ status: "deleted" });
  const user = userEvent.setup();
  openSettings();
  await waitFor(() => expect((screen.getByRole("combobox", { name: "OUTPUT LANGUAGE" }) as HTMLSelectElement).disabled).toBe(false));
  await user.click(screen.getAllByRole("button", { name: "Delete Project" })[0]);
  await user.click(screen.getAllByRole("button", { name: "Delete Project" }).at(-1)!);
  const dialog = screen.getByRole("alertdialog");
  const input = within(dialog).getByRole("textbox");
  await user.type(input, "My project");
  await user.click(within(dialog).getByRole("button", { name: "Delete Project" }));
  expect(await within(dialog).findByRole("alert")).toHaveProperty("textContent", "Project is still draining");
  expect(input).toHaveProperty("value", "My project");
  expect(requests.remove).toHaveBeenCalledTimes(1);
  await user.click(within(dialog).getByRole("button", { name: "Delete Project" }));
  expect(await screen.findByRole("status")).toHaveProperty("textContent", "Deleted My project");
});


it("edits an existing project's model and restores account inheritance without starting generation", async () => {
  let saved = { target_language: "en", dev_model_selections: { adapt: "opus" } as Record<string, string> };
  requests.config.mockImplementation(() => saved);
  requests.models.mockResolvedValue({
    enabled: true, selections: { adapt: "terra" },
    stages: [{ id: "adapt", label: "Adaptation", model_ids: ["terra", "opus", "astra"] }],
    models: [
      { id: "terra", label: "Terra", kind: "text", provider: "OpenAI", vision: true, funding: "api" },
      { id: "opus", label: "Opus", kind: "text", provider: "Anthropic", vision: true, funding: "api" },
      { id: "astra", label: "Astra", kind: "text", provider: "Codex", vision: true, funding: "codex_subscription" },
    ],
  });
  requests.save.mockRejectedValueOnce(new Error("Could not save model choices"))
    .mockImplementation(async (data) => { saved = { ...saved, ...data }; return saved; });
  const user = userEvent.setup();
  openSettings();
  await user.click(screen.getByRole("button", { name: "Models (dev)" }));
  const select = await screen.findByRole("combobox", { name: "Adaptation" });
  expect(select).toHaveProperty("value", "opus");
  await user.selectOptions(select, "astra");
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not save model choices");
  expect(select).toHaveProperty("value", "opus");
  await user.selectOptions(select, "astra");
  await waitFor(() => expect(select).toHaveProperty("value", "astra"));
  expect(requests.save).toHaveBeenLastCalledWith({ dev_model_selections: { adapt: "astra" } });
  await user.selectOptions(select, "");
  await waitFor(() => expect(select).toHaveProperty("value", ""));
  expect(requests.save).toHaveBeenLastCalledWith({ dev_model_selections: {} });
  expect(requests.save).toHaveBeenCalledTimes(3);
});
