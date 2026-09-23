import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { OperatorModelPanel } from "../components/OperatorModelPanel";
import { fetchOperatorModels, updateOperatorModels } from "../api/operator";

vi.mock("../api/operator", () => ({
  fetchOperatorModels: vi.fn(),
  updateOperatorModels: vi.fn(),
}));

const settings = {
  selections: { adapt: "gpt-6-sol" },
  models: [
    { id: "gpt-6-sol", label: "GPT-6 Sol", provider: "OpenAI", kind: "text" as const },
    { id: "claude-opus-5", label: "Claude Opus 5", provider: "Anthropic", kind: "text" as const },
  ],
  stages: [{
    id: "adapt", label: "5. Adapt — script & dialogue", description: "Writes dialogue.",
    model_ids: ["gpt-6-sol", "claude-opus-5"],
  }],
  note: "Applies to new jobs in every project.",
};
const connection = { baseUrl: "https://canary.example", token: "ops-token" };

beforeEach(() => {
  vi.mocked(fetchOperatorModels).mockReset().mockResolvedValue(settings);
  vi.mocked(updateOperatorModels).mockReset().mockImplementation(async (changes) => ({
    ...settings, selections: { ...settings.selections, ...changes },
  }));
});

it("saves a changed stage for all projects through the operator API", async () => {
  const user = userEvent.setup();
  render(<OperatorModelPanel connection={connection} />);
  const selector = await screen.findByRole("combobox", { name: /Adapt/ });
  expect((selector as HTMLSelectElement).value).toBe("gpt-6-sol");
  await user.selectOptions(selector, "claude-opus-5");
  await user.click(screen.getByRole("button", { name: "Save stage models" }));
  expect(updateOperatorModels).toHaveBeenCalledWith({ adapt: "claude-opus-5" }, connection);
  expect(await screen.findByText("Stage models saved for new jobs across all projects.")).toBeTruthy();
});
