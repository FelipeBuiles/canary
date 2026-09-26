import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { UploadStep } from "../components/wizard/UploadStep";
vi.mock("../api/queries", () => ({ useShortStories: () => ({ data: [], isLoading: false }) }));
const settings = { enabled: true, selections: { adapt: "gpt", plan: "gpt" }, stages: [{ id: "adapt", label: "Adapt", model_ids: ["gpt", "glm", "codex"] }, { id: "plan", label: "Plan", model_ids: ["gpt", "glm"] }], models: [{ id: "gpt", label: "GPT", provider: "OpenAI", funding: "api" }, { id: "glm", label: "GLM", provider: "OpenRouter", funding: "api" }, { id: "codex", label: "Codex", provider: "Codex", funding: "codex_subscription", available: false }] };
vi.mock("../api/modelSettings", () => ({ getAccountModelSettings: vi.fn(async () => settings) }));
async function setup(source: "file" | "import") {
  const user = userEvent.setup();
  const submit = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><I18nProvider><UploadStep onSubmit={submit} onSubmitImport={submit} isPending={false} error={null} /></I18nProvider></QueryClientProvider>);
  if (source === "file") {
    await user.click(screen.getByRole("button", { name: "UPLOAD MANUSCRIPT" }));
    await user.upload(view.container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(["story"], "story.txt", { type: "text/plain" }));
  } else {
    await user.click(screen.getByText("HAVE A STORY CODE OR LINK?"));
    await user.type(screen.getByLabelText("Library of Short Stories code or URL"), "story");
  }
  await user.click(screen.getByRole("button", { name: "CONTINUE" }));
  await user.click(screen.getByText("Models for this project (dev)"));
  await screen.findByRole("combobox", { name: "Adapt" });
  return { user, submit };
}
describe("project creation models", () => {
  it.each(["file", "import"] as const)("sends only explicit project choices for %s", async (source) => {
    const { user, submit } = await setup(source);
    expect((screen.getByRole("option", { name: "Codex" }) as HTMLOptionElement).disabled).toBe(true);
    await user.selectOptions(screen.getByRole("combobox", { name: "Adapt" }), "glm");
    await user.click(screen.getByRole("button", { name: "CONTINUE" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "CREATE PROJECT" }));
    expect(submit.mock.calls[0][2]).toEqual({ target_language: "en", lettering_mode: "editable", dev_model_selections: { adapt: "glm" } });
  });
  it("omits overrides after returning to account inheritance", async () => {
    const { user, submit } = await setup("import");
    await user.selectOptions(screen.getByRole("combobox", { name: "Adapt" }), "glm");
    await user.selectOptions(screen.getByRole("combobox", { name: "Adapt" }), "");
    await user.click(screen.getByRole("button", { name: "CONTINUE" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "CREATE PROJECT" }));
    expect(submit.mock.calls[0][2]).toEqual({ target_language: "en", lettering_mode: "editable" });
  });
});
