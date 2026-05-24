import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StaleStripe } from "../components/draw/LiveCockpit";

describe("StaleStripe", () => {
  it("offers continue before reset", async () => {
    const user = userEvent.setup();
    const onContinue = vi.fn();
    const onReset = vi.fn();

    render(
      <StaleStripe
        lastProgressAt={null}
        onContinue={onContinue}
        onReset={onReset}
        continuing={false}
        resetting={false}
      />,
    );

    expect(screen.getByText("STAGE STUCK")).toBeTruthy();
    expect(screen.getByText("Continue asks the server to resume pending panels and keeps generated art.")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "CONTINUE DRAW" }));
    expect(onContinue).toHaveBeenCalledTimes(1);
    expect(onReset).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "RESET STAGE" }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("disables both actions while continuing", () => {
    render(
      <StaleStripe
        lastProgressAt={null}
        onContinue={() => undefined}
        onReset={() => undefined}
        continuing
        resetting={false}
      />,
    );

    expect(screen.getByRole("button", { name: "CONTINUING..." })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "RESET STAGE" })).toHaveProperty("disabled", true);
  });
});
