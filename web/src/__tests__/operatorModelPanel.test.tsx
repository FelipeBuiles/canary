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
  reasoning_efforts: { adapt: "medium" },
  reasoning_options: {
    "gpt-6-sol": ["low", "medium", "high"], "claude-opus-5-5": ["low", "medium", "high"],
    "claude-sonnet-5-5": ["low", "medium", "high"], "mimo-v2.6-pro": ["none", "enabled"],
    "bedrock-claude-opus-5-5": ["low", "medium", "high"], "bedrock-claude-sonnet-5-5": ["low", "medium", "high"],
  },
  text_reasoning_effort: "medium",
  text_reasoning_effort_options: ["low", "medium", "high"],
  selections: { adapt: "gpt-6-sol" },
  models: [
    { id: "gpt-6-sol", label: "GPT-6 Sol", provider: "OpenAI", kind: "text" as const },
    { id: "mimo-v2.6-pro", label: "MiMo", provider: "OpenRouter", kind: "text" as const },
    { id: "claude-opus-5-5", label: "Claude Opus 5.5", provider: "Anthropic", kind: "text" as const },
    { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5", provider: "Anthropic", kind: "text" as const },
    { id: "bedrock-claude-opus-5-5", label: "Claude Opus 5.5 · Bedrock", provider: "AWS Bedrock", kind: "text" as const },
    { id: "bedrock-claude-sonnet-5-5", label: "Claude Sonnet 5.5 · Bedrock", provider: "AWS Bedrock", kind: "text" as const },
  ],
  stages: [{
    id: "adapt", label: "5. Adapt — script & dialogue", description: "Writes dialogue.",
    model_ids: ["gpt-6-sol", "claude-opus-5-5", "claude-sonnet-5-5", "mimo-v2.6-pro",
                "bedrock-claude-opus-5-5", "bedrock-claude-sonnet-5-5"],
  }],
  note: "Applies to new jobs in every project.",
};
const connection = { baseUrl: "https://canary.example", token: "ops-token" };

beforeEach(() => {
  vi.mocked(fetchOperatorModels).mockReset().mockResolvedValue(settings);
  vi.mocked(updateOperatorModels).mockReset().mockImplementation(async (changes, _connection, efforts) => ({
    ...settings, selections: { ...settings.selections, ...changes },
    reasoning_efforts: { ...settings.reasoning_efforts, ...efforts },
  }));
});

it("saves a changed stage for all projects through the operator API", async () => {
  const user = userEvent.setup();
  render(<OperatorModelPanel connection={connection} />);
  const selector = await screen.findByRole("combobox", { name: /^5. Adapt/ });
  expect((selector as HTMLSelectElement).value).toBe("gpt-6-sol");
  await user.selectOptions(selector, "claude-opus-5-5");
  await user.click(screen.getByRole("button", { name: "Save stage models" }));
  expect(updateOperatorModels).toHaveBeenCalledWith({ adapt: "claude-opus-5-5" }, connection, {});
  expect(await screen.findByText("Stage models saved for new jobs across all projects.")).toBeTruthy();
});

it("saves text effort without changing stage models", async () => {
  const user = userEvent.setup();
  render(<OperatorModelPanel connection={connection} />);
  const selector = await screen.findByRole("combobox", { name: /Reasoning —/ });
  expect((selector as HTMLSelectElement).value).toBe("medium");
  await user.selectOptions(selector, "high");
  await user.click(screen.getByRole("button", { name: "Save stage models" }));
  expect(updateOperatorModels).toHaveBeenCalledWith({}, connection, { adapt: "high" });
});

it.each(["claude-opus-5-5", "claude-sonnet-5-5"])("selects %s through either Anthropic or Bedrock", async (model) => {
  const user = userEvent.setup();
  render(<OperatorModelPanel connection={connection} />);
  const selector = await screen.findByRole("combobox", { name: /^5. Adapt/ });
  await user.selectOptions(selector, model);
  expect(screen.getByText("Anthropic")).toBeTruthy();
  await user.selectOptions(selector, `bedrock-${model}`);
  expect(screen.getByText("AWS Bedrock")).toBeTruthy();
  expect((screen.getByRole("combobox", { name: /Reasoning —/ }) as HTMLSelectElement).value).toBe("medium");
  await user.click(screen.getByRole("button", { name: "Save stage models" }));
  expect(updateOperatorModels).toHaveBeenCalledWith({ adapt: `bedrock-${model}` }, connection, {});
});

it("switches an open model to reasoning on", async () => {
  const user = userEvent.setup();
  render(<OperatorModelPanel connection={connection} />);
  await user.selectOptions(await screen.findByRole("combobox", { name: /^5. Adapt/ }), "mimo-v2.6-pro");
  const reasoning = screen.getByRole("combobox", { name: /Reasoning —/ });
  expect((reasoning as HTMLSelectElement).value).toBe("none");
  await user.selectOptions(reasoning, "enabled");
  await user.click(screen.getByRole("button", { name: "Save stage models" }));
  expect(updateOperatorModels).toHaveBeenCalledWith({ adapt: "mimo-v2.6-pro" }, connection, { adapt: "enabled" });
});
