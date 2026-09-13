import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { ApiError } from "../api/client";
import type { AccountModelSettings } from "../api/modelSettings";

vi.mock("../api/modelSettings", () => ({ getAccountModelSettings: vi.fn(), updateAccountModelSettings: vi.fn() }));
import { getAccountModelSettings, updateAccountModelSettings } from "../api/modelSettings";
import { AccountModelPanel } from "../components/AccountModelPanel";

const settings: AccountModelSettings = {
  enabled: true,
  selections: { adapt: "gpt-5.6-terra", draw: "image-sunburst" },
  stages: [
    { id: "adapt", label: "Adapt", model_ids: ["gpt-5.6-terra", "deepseek-v4.1-flash"] },
    { id: "draw", label: "Draw", model_ids: ["image-sunburst", "image-flare"] },
  ],
  models: [
    { id: "gpt-5.6-terra", label: "GPT-5.6 Terra", kind: "text", provider: "OpenAI", vision: true },
    { id: "deepseek-v4.1-flash", label: "DeepSeek V4.1 Flash", kind: "text", provider: "OpenRouter", vision: true },
    { id: "image-sunburst", label: "GPT Image 2.5 Sunburst", kind: "image", provider: "OpenAI", vision: true },
    { id: "image-flare", label: "GPT Image 2.5 Flare", kind: "image", provider: "OpenAI", vision: true },
  ],
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><I18nProvider><AccountModelPanel /></I18nProvider></QueryClientProvider>);
}

describe("account model controls", () => {
  beforeEach(() => {
    vi.mocked(getAccountModelSettings).mockReset().mockResolvedValue(settings);
    vi.mocked(updateAccountModelSettings).mockReset();
  });

  it("offers only compatible models and saves changed selections without generating", async () => {
    const user = userEvent.setup();
    vi.mocked(updateAccountModelSettings).mockResolvedValue({ ...settings, selections: { ...settings.selections, adapt: "deepseek-v4.1-flash" } });
    mount();
    const adapt = await screen.findByRole("combobox", { name: "Adapt" });
    expect((screen.getByRole("button", { name: "Save models" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("combobox", { name: "Draw" }) as HTMLSelectElement).options).toHaveLength(2);
    await user.selectOptions(adapt, "deepseek-v4.1-flash");
    expect(updateAccountModelSettings).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Save models" }));
    await screen.findByText("Account models saved. New jobs will use these choices.");
    expect(updateAccountModelSettings).toHaveBeenCalledWith({ adapt: "deepseek-v4.1-flash" }, expect.anything());
    expect((screen.getByRole("button", { name: "Save models" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("retains edits on a failed save so the user can retry", async () => {
    const user = userEvent.setup();
    vi.mocked(updateAccountModelSettings).mockRejectedValueOnce(new Error("Settings could not be saved"));
    mount();
    await user.selectOptions(await screen.findByRole("combobox", { name: "Draw" }), "image-flare");
    await user.click(screen.getByRole("button", { name: "Save models" }));
    await screen.findByRole("alert");
    expect((screen.getByRole("combobox", { name: "Draw" }) as HTMLSelectElement).value).toBe("image-flare");
    expect((screen.getByRole("button", { name: "Save models" }) as HTMLButtonElement).disabled).toBe(false);
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect((screen.getByRole("combobox", { name: "Draw" }) as HTMLSelectElement).value).toBe("image-sunburst");
  });

  it("does not show selectors when the server disables development controls", async () => {
    vi.mocked(getAccountModelSettings).mockRejectedValue(new ApiError(403, "Development only"));
    mount();
    await screen.findByText("Model controls are available only on a development server.");
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save models" })).toBeNull();
  });

  it("loads saved account choices when mounted again", async () => {
    vi.mocked(getAccountModelSettings).mockResolvedValue({ ...settings, selections: { ...settings.selections, draw: "image-flare" } });
    const view = mount();
    await waitFor(() => expect((screen.getByRole("combobox", { name: "Draw" }) as HTMLSelectElement).value).toBe("image-flare"));
    view.unmount();
    mount();
    await waitFor(() => expect((screen.getByRole("combobox", { name: "Draw" }) as HTMLSelectElement).value).toBe("image-flare"));
  });

  it("groups Codex choices by billing source and saves the exact selected model", async () => {
    const user = userEvent.setup();
    const codexId = "codex-dev/text/gpt-5.6-luna";
    const catalog: AccountModelSettings = {
      ...settings, codex_enabled: true,
      stages: settings.stages.map((stage) => stage.id === "adapt" ? { ...stage, model_ids: [...stage.model_ids, codexId] } : stage),
      models: [...settings.models, { id: codexId, label: "GPT-5.6 Luna", provider: "Codex", kind: "text", vision: true, funding: "codex_subscription", available: true }],
    };
    vi.mocked(getAccountModelSettings).mockResolvedValue(catalog);
    vi.mocked(updateAccountModelSettings).mockResolvedValue({ ...catalog, selections: { ...catalog.selections, adapt: codexId } });
    mount();
    const select = await screen.findByRole("combobox", { name: "Adapt" });
    expect(select.querySelector('optgroup[label="Codex subscription"]')).not.toBeNull();
    await user.selectOptions(select, codexId);
    await user.click(screen.getByRole("button", { name: "Save models" }));
    await screen.findByText("Account models saved. New jobs will use these choices.");
    expect(updateAccountModelSettings).toHaveBeenCalledWith({ adapt: codexId }, expect.anything());
  });

  it("keeps a saved unavailable Codex model visible and offers API replacements", async () => {
    const codexId = "codex-dev/text/gpt-5.5";
    vi.mocked(getAccountModelSettings).mockResolvedValue({
      ...settings, codex_enabled: false, selections: { ...settings.selections, adapt: codexId },
      stages: settings.stages.map((stage) => stage.id === "adapt" ? { ...stage, model_ids: [...stage.model_ids, codexId] } : stage),
      models: [...settings.models, { id: codexId, label: "GPT-5.5", provider: "Codex", kind: "text", vision: true, funding: "codex_subscription", available: false }],
    });
    mount();
    const select = await screen.findByRole("combobox", { name: "Adapt" });
    expect((select as HTMLSelectElement).value).toBe(codexId);
    expect((screen.getByRole("option", { name: "GPT-5.5" }) as HTMLOptionElement).disabled).toBe(true);
    expect(screen.getByText(/Codex is disabled on this server/)).toBeTruthy();
    await userEvent.selectOptions(select, "gpt-5.6-terra");
    expect((select as HTMLSelectElement).value).toBe("gpt-5.6-terra");
  });

  it("allows mixed model choices without linked-step billing warnings", async () => {
    const codexId = "codex-dev/text/gpt-5.5";
    vi.mocked(getAccountModelSettings).mockResolvedValue({
      ...settings,
      selections: { ...settings.selections, plan: "gpt-5.6-terra" },
      stages: settings.stages.map((stage) => stage.id === "adapt" ? { ...stage, model_ids: [...stage.model_ids, codexId] } : stage),
      models: [...settings.models, { id: codexId, label: "GPT-5.5", provider: "Codex", kind: "text", vision: true, funding: "codex_subscription" }],
    });
    mount();
    const select = await screen.findByRole("combobox", { name: "Adapt" });
    await userEvent.selectOptions(select, codexId);
    expect(screen.queryByText(/These linked steps must use the same billing source/)).toBeNull();
    expect(screen.getByText(/Mix API and Codex models freely/)).toBeTruthy();
    await userEvent.selectOptions(select, "gpt-5.6-terra");
    expect(screen.queryByText(/These linked steps must use the same billing source/)).toBeNull();
  });
});
