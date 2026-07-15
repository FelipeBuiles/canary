import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { RegenAction } from "../components/composites/RegenAction";
import { I18nProvider } from "../i18n";

function renderAction(overrides: Partial<ComponentProps<typeof RegenAction>> = {}) {
  const onRegenerate = vi.fn();
  const onRegenerateWithInstruction = vi.fn();
  render(
    <I18nProvider>
      <RegenAction
        assetLabel="Panel 4"
        cost={{
          estimate_credits: 7,
          reserved_credits: null,
          reservation_multiplier: 1,
          confidence: "low_variance",
        }}
        instructionCost={{
          estimate_credits: 9,
          reserved_credits: null,
          reservation_multiplier: 1,
          confidence: "variable",
        }}
        onRegenerate={onRegenerate}
        onRegenerateWithInstruction={onRegenerateWithInstruction}
        {...overrides}
      />
    </I18nProvider>,
  );
  return { onRegenerate, onRegenerateWithInstruction };
}

afterEach(() => {
  document.body.style.overflow = "";
  window.localStorage.clear();
});

describe("RegenAction", () => {
  it("does not start a paid action before its estimate is available", () => {
    renderAction({ cost: undefined });

    expect(screen.getByRole("button", { name: /TRY ANOTHER VERSION COST CALCULATING/i })).toHaveProperty("disabled", true);
  });

  it("confirms a paid same-brief regeneration before starting", async () => {
    const user = userEvent.setup();
    const { onRegenerate } = renderAction();

    await user.click(screen.getByRole("button", { name: /TRY ANOTHER VERSION about 7 credits/i }));
    expect(onRegenerate).not.toHaveBeenCalled();

    const drawer = screen.getByRole("alertdialog");
    expect(within(drawer).getByText("~7 credits")).toBeTruthy();
    await user.click(within(drawer).getByRole("button", { name: "TRY ANOTHER VERSION" }));

    expect(onRegenerate).toHaveBeenCalledOnce();
  });

  it("passes only a confirmed visual change", async () => {
    const user = userEvent.setup();
    const { onRegenerateWithInstruction } = renderAction();

    const input = screen.getByLabelText("WHAT SHOULD CHANGE?");
    await user.type(input, "Make the rain heavier");
    await user.click(screen.getByRole("button", { name: /REGENERATE WITH CHANGE about 9 credits/i }));

    const drawer = screen.getByRole("alertdialog");
    expect(within(drawer).getByText(/Make the rain heavier/)).toBeTruthy();
    expect(within(drawer).getByText("~9 credits")).toBeTruthy();
    await user.click(within(drawer).getByRole("button", { name: "REGENERATE WITH CHANGE" }));

    expect(onRegenerateWithInstruction).toHaveBeenCalledWith("Make the rain heavier");
  });
});
