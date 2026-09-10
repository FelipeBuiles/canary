import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StageCostEstimate } from "../types/api";
import { I18nProvider } from "../i18n";

const run = vi.fn();
const reloadEstimate = vi.fn();
let estimate: StageCostEstimate | undefined;
let estimateError = false;
let estimateFetching = false;

vi.mock("../api/queries", () => ({
  useStageEstimate: () => ({ data: estimate, isError: estimateError, isFetching: estimateFetching, refetch: reloadEstimate }),
}));
vi.mock("../hooks/useRunAction", () => ({ useRunAction: () => ({ handleRun: run, isPending: false }) }));
vi.mock("../hooks/useNeedsCredits", () => ({ useNeedsCredits: () => ({ blocked: false }) }));

import { StagePending, StagePlaceholder } from "../components/composites/StagePlaceholder";

beforeEach(() => {
  run.mockReset();
  reloadEstimate.mockReset();
  estimate = { stage: "extract", estimate_credits: 12, reserved_credits: 18, reservation_multiplier: 1.5, confidence: "usually_within_estimate" };
  estimateError = false;
  estimateFetching = false;
});

describe("First Story analysis consent", () => {
  it("does not start on arrival and requires confirmation after showing the estimate", () => {
    render(<I18nProvider><StagePending project="demo" stage="extract" allowStart /></I18nProvider>);
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Start Story analysis" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Start Story analysis" }));
    expect(run).toHaveBeenCalledWith("demo", "extract", expect.objectContaining({ rerun: false }));
  });

  it("does not interpret an unavailable estimate as a free action and offers recovery", () => {
    estimate = undefined;
    estimateError = true;
    render(<I18nProvider><StagePending project="demo" stage="extract" allowStart /></I18nProvider>);
    expect(screen.getByRole("button", { name: "Start Story analysis" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Retry estimate" }));
    expect(reloadEstimate).toHaveBeenCalledOnce();
    expect(run).not.toHaveBeenCalled();
  });

  it("keeps start failures visible and permits another deliberate attempt", () => {
    run.mockImplementation((_project, _stage, options) => options.onError(new Error("Manuscript is unavailable")));
    render(<I18nProvider><StagePending project="demo" stage="extract" allowStart /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Start Story analysis" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Start Story analysis" }));
    expect(screen.getByRole("alert").textContent).toContain("Manuscript is unavailable");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Start Story analysis" })).toHaveProperty("disabled", false);
  });
});

describe("Failed stage recovery consent", () => {
  function failedStage(rerun = false) {
    return (
      <I18nProvider>
        <StagePlaceholder project="demo" stage="plan" status="failed" retryAsRerun={rerun} />
      </I18nProvider>
    );
  }

  it("blocks an unknown estimate, then permits confirmation only after estimate recovery", () => {
    estimate = undefined;
    const { rerender } = render(failedStage());
    const retry = screen.getByRole("button", { name: "Retry stage" });
    expect(retry).toHaveProperty("disabled", true);
    fireEvent.click(retry);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(run).not.toHaveBeenCalled();

    estimateError = true;
    rerender(failedStage());
    fireEvent.click(screen.getByRole("button", { name: "Retry estimate" }));
    expect(reloadEstimate).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Retry stage" })).toHaveProperty("disabled", true);
    expect(run).not.toHaveBeenCalled();

    estimate = { stage: "plan", estimate_credits: 24, reserved_credits: 36, reservation_multiplier: 1.5, confidence: "usually_within_estimate" };
    estimateError = false;
    rerender(failedStage());
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 24 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("36 credits")).toBeTruthy();
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Retry stage" }));
    expect(run).toHaveBeenCalledOnce();
    expect(run).toHaveBeenCalledWith("demo", "plan", expect.objectContaining({ rerun: false }));
  });

  it("revokes open confirmation while an estimate refreshes or fails, even with cached cost data", () => {
    const { rerender } = render(failedStage());
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));

    estimateFetching = true;
    rerender(failedStage());
    const refreshingConfirmation = screen.getByRole("alertdialog");
    const refreshingAction = within(refreshingConfirmation).getByRole("button", { name: "Starting…" });
    expect(refreshingAction).toHaveProperty("disabled", true);
    fireEvent.click(refreshingAction);
    expect(run).not.toHaveBeenCalled();

    estimateFetching = false;
    estimateError = true;
    rerender(failedStage());
    const failedAction = within(screen.getByRole("alertdialog")).getByRole("button", { name: "Starting…" });
    expect(failedAction).toHaveProperty("disabled", true);
    fireEvent.click(failedAction);
    expect(run).not.toHaveBeenCalled();
  });

  it("allows cancelling a retry without authorizing work", () => {
    render(failedStage());
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(run).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Retry stage" })).toHaveProperty("disabled", false);
  });

  it("keeps mutation failures recoverable without silently retrying or reusing consent", () => {
    run.mockImplementationOnce((_project, _stage, options) => options.onError(new Error("Source revision changed")));
    run.mockImplementationOnce((_project, _stage, options) => options.onSuccess());
    render(failedStage());
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Retry stage" }));
    expect(screen.getByRole("alert").textContent).toContain("Source revision changed");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(run).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    expect(run).toHaveBeenCalledOnce();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Retry stage" }));
    expect(run).toHaveBeenCalledTimes(2);
    expect(run).toHaveBeenLastCalledWith("demo", "plan", expect.objectContaining({ rerun: false }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("shows downstream artifacts at risk and the hold before authorizing a destructive restart", () => {
    estimate = { stage: "plan", estimate_credits: 24, reserved_credits: 36, reservation_multiplier: 1.5, confidence: "usually_within_estimate" };
    render(failedStage(true));
    fireEvent.click(screen.getByRole("button", { name: "Restart this step" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByText("DRAW")).toBeTruthy();
    expect(within(confirmation).getByText("FINISH")).toBeTruthy();
    expect(within(confirmation).queryByText("CAST")).toBeNull();
    expect(within(confirmation).getByLabelText("about 24 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("36 credits")).toBeTruthy();
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Restart this step" }));
    expect(run).toHaveBeenCalledOnce();
    expect(run).toHaveBeenCalledWith("demo", "plan", expect.objectContaining({ rerun: true }));
  });
});


describe("Readable adaptation failures", () => {
  it("keeps internal errors collapsed and resumes with saved work after consent", () => {
    render(<I18nProvider><StagePlaceholder project="demo" stage="adapt" status="failed"
      error="Book adaptation has invariant failures: invalid_lettering_speaker"
      errorDetail={"Traceback: /a/very/long/path/".repeat(80)}
    /></I18nProvider>);
    expect(screen.getByText("The comic script needs a few corrections before page planning can continue.")).toBeTruthy();
    const details = screen.getByText("Technical details").closest("details");
    expect(details?.open).toBe(false);
    expect(details?.textContent).toContain("invalid_lettering_speaker");
    expect(details?.querySelector("pre")?.className).toContain("[overflow-wrap:anywhere]");
    expect(screen.queryByText("Page planning follows automatically. You will choose when to start drawing.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Resume adaptation" }));
    expect(run).toHaveBeenCalledWith("demo", "adapt", expect.objectContaining({ rerun: false }));
  });
});
