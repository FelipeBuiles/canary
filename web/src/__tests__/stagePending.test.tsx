import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StageCostEstimate } from "../types/api";
import { I18nProvider } from "../i18n";

const run = vi.fn();
const reloadEstimate = vi.fn();
let estimate: StageCostEstimate | undefined;
let estimateError = false;
let estimateFetching = false;
const estimateCalls = vi.fn();

vi.mock("../api/queries", () => ({
  useStageEstimate: (...args: unknown[]) => {
    estimateCalls(...args);
    return { data: estimate, isError: estimateError, isFetching: estimateFetching, refetch: reloadEstimate };
  },
}));
vi.mock("../hooks/useRunAction", () => ({ useRunAction: () => ({ handleRun: run, isPending: false }) }));
vi.mock("../hooks/useNeedsCredits", () => ({ useNeedsCredits: () => ({ blocked: false }) }));

import { StagePending, StagePlaceholder } from "../components/composites/StagePlaceholder";

beforeEach(() => {
  run.mockReset();
  reloadEstimate.mockReset();
  estimateCalls.mockReset();
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
  it("quotes a fresh attempt separately and only restarts after confirmation", () => {
    render(<I18nProvider><StagePlaceholder project="demo" stage="adapt" status="failed" /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Start adaptation over" }));
    expect(estimateCalls).toHaveBeenLastCalledWith("demo", "adapt", true, true);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("archived");
    expect(dialog.textContent).toContain("Previous charges remain");
    expect(dialog.textContent).toContain("Page planning follows automatically");
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Start adaptation over" }));
    expect(run).toHaveBeenCalledWith("demo", "adapt", expect.objectContaining({ rerun: true }));
  });

  it("cancels a fresh start and returns to the resume estimate", () => {
    render(<I18nProvider><StagePlaceholder project="demo" stage="adapt" status="failed" /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Start adaptation over" }));
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(run).not.toHaveBeenCalled();
    expect(estimateCalls).toHaveBeenLastCalledWith("demo", "adapt", true, false);
    fireEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Resume adaptation" }));
    expect(run).toHaveBeenCalledWith("demo", "adapt", expect.objectContaining({ rerun: false }));
  });

  it("allows requesting a fresh estimate when resume estimation fails, but blocks unquoted work", () => {
    estimate = undefined;
    estimateError = true;
    render(<I18nProvider><StagePlaceholder project="demo" stage="adapt" status="failed" /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Start adaptation over" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("button", { name: "Start adaptation over" })).toHaveProperty("disabled", true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Retry estimate" }));
    expect(reloadEstimate).toHaveBeenCalledOnce();
    expect(run).not.toHaveBeenCalled();
  });

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


describe("Model refusal recovery", () => {
  it("allows an estimated and explicitly confirmed Adapt retry", () => {
    estimate = {
      stage: "adapt",
      estimate_credits: 8,
      reserved_credits: 12,
      reservation_multiplier: 1.5,
      confidence: "usually_within_estimate",
    };
    render(<MemoryRouter><I18nProvider><StagePlaceholder project="demo" stage="adapt" status="failed"
      errorCode="model_refusal" error="Provider declined" errorDetail="Traceback: AIRefusalError"
    /></I18nProvider></MemoryRouter>);

    expect(screen.getByText("Model declined this content")).toBeTruthy();
    expect(screen.getByText(
      "Retry the adaptation with the current settings after reviewing the estimate. The provider may decline the same input again.",
    )).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 8 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("12 credits")).toBeTruthy();
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Resume adaptation" }));

    expect(run).toHaveBeenCalledWith("demo", "adapt", expect.objectContaining({ rerun: false }));
  });

  it.each([
    { errorCode: "model_refusal", error: "Provider declined" },
    { error: "runtime_turn_error: stream disconnected before completion: Incomplete response returned, reason: content_filter" },
    { error: "AI request was refused by gateway/provider (finish_reason=content_filter)" },
  ])("shows refusal guidance without an unchanged paid retry", (failure) => {
    render(<MemoryRouter><I18nProvider><StagePlaceholder project="demo" stage="draw" status="failed"
      {...failure} errorDetail="Traceback: AIRefusalError"
    /></I18nProvider></MemoryRouter>);
    expect(screen.getByText("Model declined this content")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to projects" }).getAttribute("href")).toBe("/");
    expect(screen.queryByRole("button", { name: /try again|retry|restart|resume/i })).toBeNull();
    expect(screen.getByText("Technical details").closest("details")?.open).toBe(false);
    expect(run).not.toHaveBeenCalled();
  });
});
