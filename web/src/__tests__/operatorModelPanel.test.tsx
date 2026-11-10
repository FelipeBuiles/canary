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
    "gemini-4-carbon": ["low", "medium", "high"],
    "gpt-6-sol": ["low", "medium", "high"], "claude-opus-5-5": ["low", "medium", "high"],
    "claude-sonnet-5-5": ["low", "medium", "high"], "mimo-v2.6-pro": ["none", "enabled"],
    "bedrock-claude-opus-5-5": ["low", "medium", "high"], "bedrock-claude-sonnet-5-5": ["low", "medium", "high"],
  },
  text_reasoning_effort: "medium",
  text_reasoning_effort_options: ["low", "medium", "high"],
  selections: { adapt: "gpt-6-sol", image: "image-sunburst", draw: "image-sunburst" },
  models: [
    { id: "gemini-4-carbon", label: "Gemini 4 Carbon", provider: "Google Vertex AI", kind: "text" as const },
    { id: "gpt-6-sol", label: "GPT-6 Sol", provider: "OpenAI", kind: "text" as const },
    { id: "mimo-v2.6-pro", label: "MiMo", provider: "OpenRouter", kind: "text" as const },
    { id: "claude-opus-5-5", label: "Claude Opus 5.5", provider: "Anthropic", kind: "text" as const },
    { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5", provider: "Anthropic", kind: "text" as const },
    { id: "bedrock-claude-opus-5-5", label: "Claude Opus 5.5 · Bedrock", provider: "AWS Bedrock", kind: "text" as const },
    { id: "bedrock-claude-sonnet-5-5", label: "Claude Sonnet 5.5 · Bedrock", provider: "AWS Bedrock", kind: "text" as const },
    { id: "image-sunburst", label: "GPT Image 2.5 Sunburst", provider: "OpenAI, FAL backup", kind: "image" as const },
    { id: "image-nano-banana-2.1", label: "Nano Banana 2.1", provider: "Google Vertex AI", kind: "image" as const },
  ],
  stages: [{
    id: "adapt", label: "5. Adapt — script & dialogue", description: "Writes dialogue.",
    model_ids: ["gemini-4-carbon", "gpt-6-sol", "claude-opus-5-5", "claude-sonnet-5-5", "mimo-v2.6-pro",
                "bedrock-claude-opus-5-5", "bedrock-claude-sonnet-5-5"],
  }, {
    id: "image", label: "3–4. Style & Cast — images", description: "Generates style samples and cast references.",
    model_ids: ["image-sunburst", "image-nano-banana-2.1"],
  }, {
    id: "draw", label: "7. Draw — page artwork", description: "Generates complete comic pages.",
    model_ids: ["image-sunburst", "image-nano-banana-2.1"],
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

it("saves Nano Banana 2.1 for Style/Cast images and Draw through the operator API", async () => {
  const user = userEvent.setup();
  render(<OperatorModelPanel connection={connection} />);
  const image = await screen.findByRole("combobox", { name: "3–4. Style & Cast — images" });
  const draw = screen.getByRole("combobox", { name: "7. Draw — page artwork" });
  await user.selectOptions(image, "image-nano-banana-2.1");
  await user.selectOptions(draw, "image-nano-banana-2.1");
  expect(screen.getAllByText("Google Vertex AI")).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "Save stage models" }));
  expect(updateOperatorModels).toHaveBeenCalledWith({ image: "image-nano-banana-2.1", draw: "image-nano-banana-2.1" }, connection, {});
  expect(await screen.findByText("Stage models saved for new jobs across all projects.")).toBeTruthy();
  expect((image as HTMLSelectElement).value).toBe("image-nano-banana-2.1");
  expect((draw as HTMLSelectElement).value).toBe("image-nano-banana-2.1");
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


it("selects Carbon with configurable reasoning", async () => {
  const user = userEvent.setup();
  render(<OperatorModelPanel connection={connection} />);
  await user.selectOptions(await screen.findByRole("combobox", { name: /^5. Adapt/ }), "gemini-4-carbon");
  expect((screen.getByRole("combobox", { name: /Reasoning —/ }) as HTMLSelectElement).value).toBe("medium");
  await user.selectOptions(screen.getByRole("combobox", { name: /Reasoning —/ }), "high");
  await user.click(screen.getByRole("button", { name: "Save stage models" }));
  expect(updateOperatorModels).toHaveBeenCalledWith({ adapt: "gemini-4-carbon" }, connection, { adapt: "high" });
});
