import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StaleStripe } from "../components/draw/LiveCockpit";
import { isAllInkedTransition } from "../components/draw/progressTransitions";

describe("isAllInkedTransition", () => {
  it("fires when the last panel lands with no failures", () => {
    expect(isAllInkedTransition(31, { generated: 32, failed: 0, total: 32 })).toBe(true);
  });

  it("does not fire on mount of an already-complete stage", () => {
    expect(isAllInkedTransition(null, { generated: 32, failed: 0, total: 32 })).toBe(false);
  });

  it("does not fire again once complete", () => {
    expect(isAllInkedTransition(32, { generated: 32, failed: 0, total: 32 })).toBe(false);
  });

  it("never fires while panels failed", () => {
    expect(isAllInkedTransition(30, { generated: 31, failed: 1, total: 32 })).toBe(false);
  });

  it("never fires on an empty stage", () => {
    expect(isAllInkedTransition(0, { generated: 0, failed: 0, total: 0 })).toBe(false);
  });

  it("does not fire mid-run", () => {
    expect(isAllInkedTransition(10, { generated: 11, failed: 0, total: 32 })).toBe(false);
  });
});

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

  it("describes resumable cast work without panel-specific language", () => {
    render(
      <StaleStripe
        lastProgressAt={null}
        onContinue={() => undefined}
        onReset={() => undefined}
        continuing={false}
        resetting={false}
        stageLabel="CAST"
        itemLabel="cast images"
      />,
    );

    expect(screen.getByText("Continue asks the server to resume pending cast images and keeps generated art.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "CONTINUE CAST" })).toBeTruthy();
  });
});
