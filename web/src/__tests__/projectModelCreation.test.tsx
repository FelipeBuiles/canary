import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { UploadStep } from "../components/wizard/UploadStep";
vi.mock("../api/queries", () => ({ useShortStories: () => ({ data: [], isLoading: false }), useSourcePreview: () => ({ isPending: true }) }));
const settings = { enabled: true, selections: { adapt: "gpt", plan: "gpt", image: "image-sunburst", draw: "image-sunburst" }, stages: [{ id: "adapt", label: "Adapt", model_ids: ["gpt", "glm", "codex"] }, { id: "plan", label: "Plan", model_ids: ["gpt", "glm"] }, { id: "image", label: "Style & Cast images", model_ids: ["image-sunburst", "image-nano-banana-2.1"] }, { id: "draw", label: "Draw", model_ids: ["image-sunburst", "image-nano-banana-2.1"] }], models: [{ id: "gpt", label: "GPT", provider: "OpenAI", funding: "api" }, { id: "glm", label: "GLM", provider: "OpenRouter", funding: "api" }, { id: "codex", label: "Codex", provider: "Codex", funding: "codex_subscription", available: false }, { id: "image-sunburst", label: "GPT Image 2.5 Sunburst", provider: "OpenAI, FAL backup", funding: "api" }, { id: "image-nano-banana-2.1", label: "Nano Banana 2.1", provider: "Google Vertex AI", funding: "api" }] };
vi.mock("../api/modelSettings", () => ({ getAccountModelSettings: vi.fn(async () => settings) }));
async function setup(source: "file" | "import") {
  const user = userEvent.setup();
  const submit = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><I18nProvider><UploadStep onSubmit={submit} onSubmitImport={submit} isPending={false} error={null} /></I18nProvider></QueryClientProvider>);
  if (source === "file") {
    await user.upload(view.container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(["story"], "story.txt", { type: "text/plain" }));
  } else {
    await user.click(screen.getByText("Have a story code or link?"));
    await user.type(screen.getByLabelText("Library of Short Stories code or URL"), "story");
  }
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByText("Models for this project (dev)"));
  await screen.findByRole("combobox", { name: "Adapt" });
  return { user, submit };
}
describe("project creation models", () => {
  it.each(["file", "import"] as const)("sends only explicit project choices for %s", async (source) => {
    const { user, submit } = await setup(source);
    expect((screen.getByRole("option", { name: "Codex" }) as HTMLOptionElement).disabled).toBe(true);
    await user.selectOptions(screen.getByRole("combobox", { name: "Adapt" }), "glm");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "Create project" }));
    expect(submit.mock.calls[0][2]).toEqual({ target_language: "en", lettering_mode: "editable", dev_model_selections: { adapt: "glm" } });
  });
  it("omits overrides after returning to account inheritance", async () => {
    const { user, submit } = await setup("import");
    await user.selectOptions(screen.getByRole("combobox", { name: "Adapt" }), "glm");
    await user.selectOptions(screen.getByRole("combobox", { name: "Adapt" }), "");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "Create project" }));
    expect(submit.mock.calls[0][2]).toEqual({ target_language: "en", lettering_mode: "editable" });
  });
  it("pins Nano Banana 2.1 for Style/Cast images and Draw without changing account defaults", async () => {
    const { user, submit } = await setup("import");
    await user.selectOptions(screen.getByRole("combobox", { name: "Style & Cast images" }), "image-nano-banana-2.1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Draw" }), "image-nano-banana-2.1");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "Create project" }));
    expect(submit.mock.calls[0][2]).toEqual({ target_language: "en", lettering_mode: "editable", dev_model_selections: { image: "image-nano-banana-2.1", draw: "image-nano-banana-2.1" } });
    expect(settings.selections.image).toBe("image-sunburst");
    expect(settings.selections.draw).toBe("image-sunburst");
  });
});
