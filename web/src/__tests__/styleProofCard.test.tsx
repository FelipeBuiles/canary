import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { StyleProofCard } from "../components/style/StyleProofCard";
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

function props(overrides: Partial<ComponentProps<typeof StyleProofCard>> = {}): ComponentProps<typeof StyleProofCard> {
  return {
    suggestion, projectName: "My story", isGenerating: false, generationDisabled: false,
    retryDisabled: false, selectionDisabled: false, queueState: null, fallbackPrompt: "Full proof prompt",
    fallbackParameters: {}, isCompared: false, onToggleCompare: vi.fn(),
    validationBusy: false, onValidate: vi.fn(), onRefresh: vi.fn(), onRetry: vi.fn(), ...overrides,
  };
}

function card(input = props()) {
  return <I18nProvider><StyleProofCard {...input} /></I18nProvider>;
}

beforeEach(() => { mutation.mutate.mockReset(); mutation.isPending = false; });

describe("StyleProofCard", () => {
  it("selects only from the explicit action, never from browsing or comparing", async () => {
    const user = userEvent.setup();
    const input = props();
    render(card(input));
    await user.click(screen.getByRole("heading", { name: suggestion.label }));
    await user.click(screen.getByText("VISUAL DIRECTION"));
    await user.click(screen.getByRole("button", { name: "COMPARE" }));
    expect(input.onToggleCompare).toHaveBeenCalledOnce();
    expect(mutation.mutate).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "SELECT THIS STYLE" }));
    expect(mutation.mutate).toHaveBeenCalledWith(
      { project: "My story", id: "ink" }, expect.objectContaining({ onError: expect.any(Function), onSuccess: expect.any(Function) }),
    );
  });

  it("opens the full proof without selecting a direction", async () => {
    render(card());
    await userEvent.click(screen.getByRole("button", { name: /View proof and direction/ }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(mutation.mutate).not.toHaveBeenCalled();
  });

  it.each(["/lettered-proof.png?style=current", null])("keeps the full proof on the card's image source (%s)", async (preview) => {
    render(card(props({ suggestion: { ...suggestion, sample_preview_url: preview } })));
    const cardSource = screen.getByRole("img", { name: suggestion.label }).getAttribute("src");
    if (preview) expect(cardSource).toContain(`${preview}&t=`);
    else expect(cardSource).toContain("/files/samples/style_0.png?t=");
    await userEvent.click(screen.getByRole("button", { name: /View proof and direction/ }));
    expect(within(screen.getByRole("dialog")).getByRole("img", { name: suggestion.label }).getAttribute("src")).toBe(cardSource);
  });

  it.each([null, "/lettered-proof.png?style=updated"])("recovers a failed preview when the refreshed styles response changes its source to %s", async (preview) => {
    const input = props({ suggestion: { ...suggestion, sample_preview_url: "/lettered-proof.png?style=previous" } });
    const view = render(card(input));
    await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 0)); });
    fireEvent.error(screen.getByRole("img", { name: suggestion.label }));
    expect(screen.getByText("PROOF IMAGE UNAVAILABLE")).toBeTruthy();

    // Polling the same failed source must not retry it on every response.
    view.rerender(card({ ...input, suggestion: { ...input.suggestion, sample_stale: true } }));
    expect(screen.getByText("PROOF IMAGE UNAVAILABLE")).toBeTruthy();
    expect(screen.queryByRole("img", { name: suggestion.label })).toBeNull();

    // A model change can withdraw the preview URL while retaining the saved art.
    view.rerender(card({ ...input, suggestion: { ...input.suggestion, sample_preview_url: preview, sample_stale: true } }));
    await waitFor(() => {
      const image = screen.getByRole("img", { name: suggestion.label });
      expect(image.getAttribute("src")).toContain(preview ? `${preview}&t=` : "/files/samples/style_0.png?t=");
    });
    // Returning to the original model must try its preview again, even if the
    // replacement image has not finished loading yet.
    view.rerender(card(input));
    expect(screen.getByRole("img", { name: suggestion.label }).getAttribute("src")).toContain("/lettered-proof.png?style=previous&t=");
    fireEvent.load(screen.getByRole("img", { name: suggestion.label }));
    expect(screen.getByRole("img", { name: suggestion.label }).className).toContain("opacity-100");
    expect(screen.queryByText("PROOF IMAGE UNAVAILABLE")).toBeNull();
    expect(input.onRefresh).not.toHaveBeenCalled();
    expect(input.onRetry).not.toHaveBeenCalled();
  });

  it.each(["pending", "generating", "disabled", "active"])("blocks selection while %s", async (state) => {
    mutation.isPending = state === "pending";
    render(card(props({
      isGenerating: state === "generating", selectionDisabled: state === "disabled",
      suggestion: { ...suggestion, is_active: state === "active" },
    })));
    const button = screen.getByRole("button", { name: /SELECT THIS STYLE|SELECTING…|YOUR STYLE/ });
    expect(button).toHaveProperty("disabled", true);
    expect(button.getAttribute("aria-pressed")).toBe(String(state === "active"));
    await userEvent.click(button);
    expect(mutation.mutate).not.toHaveBeenCalled();
  });

  it("reloads a saved proof when it becomes available again after an image failure", () => {
    const input = props();
    const view = render(card(input));
    fireEvent.error(screen.getByRole("img", { name: suggestion.label }));
    expect(screen.getByText("PROOF IMAGE UNAVAILABLE")).toBeTruthy();
    view.rerender(card({ ...input, suggestion: { ...suggestion, has_sample: false } }));
    expect(screen.getAllByText("PROOF NOT GENERATED").length).toBeGreaterThan(0);
    view.rerender(card(input));
    expect(screen.getByRole("img", { name: suggestion.label })).toBeTruthy();
    expect(screen.queryByText("PROOF IMAGE UNAVAILABLE")).toBeNull();
  });

  it("shows selection failure without marking the rejected direction as selected", async () => {
    render(card());
    await userEvent.click(screen.getByRole("button", { name: "SELECT THIS STYLE" }));
    act(() => mutation.mutate.mock.calls[0][1].onError(new Error("Selection could not be saved")));
    expect(screen.getByRole("alert").textContent).toContain("Your changes could not be saved.");
    expect(screen.getByText("Selection could not be saved").closest("details")?.open).toBe(false);
    expect(screen.getByRole("button", { name: "SELECT THIS STYLE" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByText("YOUR STYLE")).toBeNull();
  });

  it("blocks adding to a full comparison but permits removing an included proof", async () => {
    const input = props({ compareDisabled: true });
    const view = render(card(input));
    expect(screen.getByRole("button", { name: "COMPARE" })).toHaveProperty("disabled", true);
    await userEvent.click(screen.getByRole("button", { name: "COMPARE" }));
    expect(input.onToggleCompare).not.toHaveBeenCalled();
    view.rerender(card({ ...input, isCompared: true, compareDisabled: false }));
    await userEvent.click(screen.getByRole("button", { name: "COMPARING" }));
    expect(input.onToggleCompare).toHaveBeenCalledOnce();
    expect(mutation.mutate).not.toHaveBeenCalled();
  });

  it("retains full direction and action proof in disclosures; audition only calls its callback", async () => {
    const user = userEvent.setup();
    const input = props();
    render(card(input));
    const direction = screen.getByText(suggestion.template);
    expect(direction.closest("details")).toHaveProperty("open", false);
    await user.click(screen.getByText("VISUAL DIRECTION"));
    expect(direction.closest("details")).toHaveProperty("open", true);
    expect(screen.getByText(suggestion.risk)).toBeTruthy();
    await user.click(screen.getByText("ACTION AUDITION"));
    expect(screen.getByRole("img", { name: /Midnight ink · ACTION AUDITION/ }).getAttribute("src")).toBe("/action-ink.png");
    await user.click(screen.getByRole("button", { name: "RETEST IN ACTION" }));
    expect(input.onValidate).toHaveBeenCalledOnce();
    expect(input.onRefresh).not.toHaveBeenCalled();
    expect(mutation.mutate).not.toHaveBeenCalled();
  });
});

it("shows the concrete character design without adding more collapsed-card controls", async () => {
  const characterDesign = "Compact large heads, short limbs, rounded adult silhouettes and simple faces.";
  render(card(props({ suggestion: { ...suggestion, role: "story_fit_tertiary", character_design: characterDesign } })));
  expect(screen.getByText("STRONG FIT")).toBeTruthy();
  const design = screen.getByText(characterDesign);
  expect(design.closest("details")).toHaveProperty("open", false);
  await userEvent.click(screen.getByText("VISUAL DIRECTION"));
  expect(design.closest("details")).toHaveProperty("open", true);
  expect(screen.getByText("CHARACTER DESIGN")).toBeTruthy();
});

it("distinguishes an unrequested proof from a failed proof", () => {
  const view = render(card(props({ suggestion: { ...suggestion, has_sample: false, generation_status: "not_requested" } })));
  expect(screen.getAllByText("PROOF NOT GENERATED").length).toBeGreaterThan(0);
  expect(screen.queryByText("SAMPLE PROOF FAILED")).toBeNull();
  expect(screen.getByRole("button", { name: "SELECT THIS STYLE" })).toHaveProperty("disabled", true);
  view.rerender(card(props({ suggestion: { ...suggestion, has_sample: false, generation_status: "failed" } })));
  expect(screen.getAllByText("SAMPLE PROOF FAILED").length).toBeGreaterThan(0);
});

it("offers the retry inside the empty proof and keeps it open while other proofs draw", async () => {
  const input = props({ generationDisabled: true, suggestion: { ...suggestion, has_sample: false, generation_status: "failed" } });
  const view = render(card(input));
  expect(screen.queryByRole("button", { name: /View proof and direction/ })).toBeNull();
  expect(screen.getByRole("button", { name: "COMPARE" })).toHaveProperty("disabled", true);
  await userEvent.click(screen.getByRole("button", { name: "TRY SAMPLE AGAIN" }));
  expect(input.onRetry).toHaveBeenCalledOnce();
  expect(input.onRefresh).not.toHaveBeenCalled();
  view.rerender(card({ ...input, retryDisabled: true }));
  expect(screen.getByRole("button", { name: "TRY SAMPLE AGAIN" })).toHaveProperty("disabled", true);
  view.rerender(card({ ...input, isGenerating: true, queueState: "queued" }));
  expect(screen.queryByRole("button", { name: "TRY SAMPLE AGAIN" })).toBeNull();
});

it("keeps a failed proof retryable while a batch draws the others", () => {
  render(card(props({ awaitingBatch: true, suggestion: { ...suggestion, has_sample: false, generation_status: "failed" } })));
  expect(screen.getByRole("button", { name: "TRY SAMPLE AGAIN" })).toBeTruthy();
});
