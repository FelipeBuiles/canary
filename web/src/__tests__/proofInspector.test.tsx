import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { ProofInspector } from "../components/style/ProofInspector";
import { ProofStage } from "../components/style/ProofStage";
import type { StyleSuggestion } from "../api/styles";
import { I18nProvider } from "../i18n";

const mutation = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));
const presentation = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));
vi.mock("../api/queries", () => ({
  useSetActiveStyle: () => mutation,
  useUpdateStylePresentation: () => presentation,
  useImageGenerationMeta: () => ({ data: undefined, isLoading: false }),
}));

const suggestion: StyleSuggestion = {
  id: "ink", index: 0, label: "Midnight ink", origin: "generated",
  role: "story_fit_primary", medium: "Ink wash", palette: "Blue and gold",
  line_rendering: "Expressive brushwork", lighting_value: "Hard rim light",
  sequential_art_strengths: "Readable silhouettes", story_fit: "Keeps the danger intimate.",
  risk: "Shadows can obscure faces.",
  template: "Preserve the complete direction, including small but essential details at the end.",
  has_sample: true, sample_stale: false, has_style_reference: false,
  has_validation: true, validation_url: "/action-ink.png", is_active: false,
};

function props(overrides: Partial<ComponentProps<typeof ProofInspector>> = {}): ComponentProps<typeof ProofInspector> {
  return {
    suggestion, projectName: "My story", imageSrc: "/proof.png", imageAvailable: true, isGenerating: false,
    generationDisabled: false, retryDisabled: false, selectionDisabled: false, isCompared: false, compareDisabled: false,
    onToggleCompare: vi.fn(), validationBusy: false, onValidate: vi.fn(), onRefresh: vi.fn(),
    fallbackPrompt: "Full proof prompt", fallbackParameters: {}, ...overrides,
  };
}

function inspector(input = props()) {
  return <I18nProvider><ProofInspector {...input} /></I18nProvider>;
}

beforeEach(() => { mutation.mutate.mockReset(); mutation.isPending = false; });

describe("ProofInspector", () => {
  it("selects only from the explicit action, never from reading or comparing", async () => {
    const user = userEvent.setup();
    const input = props();
    render(inspector(input));
    expect(screen.getByText("Best fit")).toBeTruthy();
    await user.click(screen.getByText("Full direction"));
    await user.click(screen.getByRole("button", { name: "Compare · Midnight ink" }));
    expect(input.onToggleCompare).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Generation details · Midnight ink" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(mutation.mutate).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "Use this style" }));
    expect(mutation.mutate).toHaveBeenCalledWith(
      { project: "My story", id: "ink" }, expect.objectContaining({ onError: expect.any(Function) }),
    );
  });

  it.each(["pending", "generating", "disabled", "missing"])("blocks selection while %s", async (state) => {
    mutation.isPending = state === "pending";
    render(inspector(props({
      isGenerating: state === "generating", selectionDisabled: state === "disabled",
      suggestion: { ...suggestion, has_sample: state !== "missing" },
    })));
    const button = screen.getByRole("button", { name: /Use this style|Selecting…/ });
    expect(button).toHaveProperty("disabled", true);
    await userEvent.click(button);
    expect(mutation.mutate).not.toHaveBeenCalled();
  });

  it("shows the chosen style as a state, not an action", () => {
    render(inspector(props({ suggestion: { ...suggestion, is_active: true } })));
    expect(screen.getByRole("status").textContent).toContain("Your style");
    expect(screen.queryByRole("button", { name: "Use this style" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Hide/ })).toBeNull();
  });

  it("shows selection failure without marking the rejected direction as selected", async () => {
    render(inspector());
    await userEvent.click(screen.getByRole("button", { name: "Use this style" }));
    act(() => mutation.mutate.mock.calls[0][1].onError(new Error("Selection could not be saved")));
    expect(screen.getByRole("alert").textContent).toContain("Your changes could not be saved.");
    expect(screen.getByRole("button", { name: "Use this style" })).toBeTruthy();
  });

  it("blocks adding to a full comparison but permits removing an included proof", async () => {
    const input = props({ compareDisabled: true });
    const view = render(inspector(input));
    const compare = screen.getByRole("button", { name: "Compare · Midnight ink" });
    expect(compare).toHaveProperty("disabled", true);
    view.rerender(inspector({ ...input, isCompared: true }));
    expect(compare.getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(compare);
    expect(input.onToggleCompare).toHaveBeenCalledOnce();
  });

  it("keeps the full direction in a disclosure; the audition and refresh only call back", async () => {
    const user = userEvent.setup();
    const input = props({ suggestion: { ...suggestion, sample_stale: true, character_design: "Compact heads and short limbs." } });
    render(inspector(input));
    expect(screen.getByText(suggestion.risk)).toBeTruthy();
    const design = screen.getByText("Compact heads and short limbs.");
    expect(design.closest("details")).toHaveProperty("open", false);
    await user.click(screen.getByText("Full direction"));
    expect(design.closest("details")).toHaveProperty("open", true);
    expect(screen.getByRole("img", { name: "Midnight ink · Action audition" }).getAttribute("src")).toBe("/action-ink.png");
    await user.click(screen.getByRole("button", { name: "Retest" }));
    expect(input.onValidate).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Refresh proof" }));
    expect(input.onRefresh).toHaveBeenCalledOnce();
    expect(mutation.mutate).not.toHaveBeenCalled();
  });
});

function stageProps(overrides: Partial<ComponentProps<typeof ProofStage>> = {}): ComponentProps<typeof ProofStage> {
  return {
    projectName: "My story", suggestion, position: 1, count: 3, isGenerating: false, awaitingBatch: false,
    queueState: null, retryDisabled: false, onRetry: vi.fn(), onStep: vi.fn(),
    inspectImages: [], inspectIndex: 0, onInspectIndexChange: vi.fn(), ...overrides,
  };
}

function stage(input = stageProps()) {
  return <I18nProvider><ProofStage {...input} /></I18nProvider>;
}

describe("ProofStage", () => {
  it.each(["/lettered-proof.png?style=current", null])("draws the proof from its preview or saved file (%s)", (preview) => {
    render(stage(stageProps({ suggestion: { ...suggestion, sample_preview_url: preview } })));
    const source = screen.getByRole("img", { name: suggestion.label }).getAttribute("src");
    expect(source).toContain(preview ? `${preview}&t=` : "/files/samples/style_0.png?t=");
  });

  it("recovers a failed preview when the styles response changes its source", async () => {
    const input = stageProps({ suggestion: { ...suggestion, sample_preview_url: "/lettered-proof.png?style=previous" } });
    const view = render(stage(input));
    await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 0)); });
    fireEvent.error(screen.getByRole("img", { name: suggestion.label }));
    expect(screen.getByText("Proof image unavailable")).toBeTruthy();
    // Polling the same failed source must not retry it on every response.
    view.rerender(stage({ ...input, suggestion: { ...input.suggestion, sample_stale: true } }));
    expect(screen.queryByRole("img", { name: suggestion.label })).toBeNull();
    view.rerender(stage({ ...input, suggestion: { ...input.suggestion, sample_preview_url: null, sample_stale: true } }));
    await waitFor(() => expect(screen.getByRole("img", { name: suggestion.label }).getAttribute("src")).toContain("/files/samples/style_0.png?t="));
    expect(input.onRetry).not.toHaveBeenCalled();
  });

  it("distinguishes an unrequested proof from a failed one and offers the retry in place", async () => {
    const input = stageProps({ suggestion: { ...suggestion, has_sample: false, generation_status: "not_requested" } });
    const view = render(stage(input));
    expect(screen.getByText("Not drawn yet")).toBeTruthy();
    view.rerender(stage({ ...input, suggestion: { ...input.suggestion, generation_status: "failed" } }));
    expect(screen.getByText("This proof didn't finish")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Try this proof again" }));
    expect(input.onRetry).toHaveBeenCalledOnce();
    view.rerender(stage({ ...input, retryDisabled: true, suggestion: { ...input.suggestion, generation_status: "failed" } }));
    expect(screen.getByRole("button", { name: "Try this proof again" })).toHaveProperty("disabled", true);
    view.rerender(stage({ ...input, isGenerating: true, queueState: "queued", suggestion: { ...input.suggestion, generation_status: "failed" } }));
    expect(screen.queryByRole("button", { name: "Try this proof again" })).toBeNull();
  });

  it("flips with the arrow keys and the side buttons", async () => {
    const onStep = vi.fn();
    render(stage(stageProps({ onStep })));
    fireEvent.keyDown(screen.getByRole("group", { name: "Midnight ink, 1 / 3" }), { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("group", { name: "Midnight ink, 1 / 3" }), { key: "ArrowLeft" });
    await userEvent.click(screen.getByRole("button", { name: "Next proof" }));
    expect(onStep.mock.calls).toEqual([[1], [-1], [1]]);
  });
});
