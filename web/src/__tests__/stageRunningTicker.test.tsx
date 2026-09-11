import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { StageRunning } from "../components/composites/StagePlaceholder";
import { usePipelineStore } from "../store/pipeline";
import { I18nProvider } from "../i18n";

function renderStage(stage: ReactElement) {
  return render(<I18nProvider>{stage}</I18nProvider>);
}

afterEach(() => {
  usePipelineStore.setState({ events: [] });
});

describe("StageRunning log ticker", () => {
  it("does not invent a progress percentage before counts arrive", () => {
    renderStage(<StageRunning stage="cast" />);
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBeNull();
    expect(screen.queryByText(/\d+%/)).toBeNull();
  });

  it("clamps stale over-complete totals to a valid percentage", () => {
    renderStage(<StageRunning stage="draw" itemsDone={16} itemsTotal={9} />);

    expect(screen.getByText("9 / 9")).toBeTruthy();
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.queryByText("178%")).toBeNull();
    expect(screen.getByRole("progressbar").getAttribute("value")).toBe("100");
  });

  it("shows the last three readable log lines for the running stage only", () => {
    usePipelineStore.setState({
      events: [
        { type: "log", stage: "cast", level: "info", message: "Generating character reference sheets..." },
        { type: "log", stage: "draw", level: "info", message: "Drawing panel batch 1-8 of 32" },
        { type: "log", stage: "cast", level: "error", message: "Failed ref sheet for Ada: timeout" },
        { type: "log", stage: "cast", level: "dim", message: "Using existing ref sheet for Marlow" },
        { type: "stage_progress", stage: "cast", done: 2, total: 4 },
        { type: "log", stage: "cast", level: "info", message: "Generating location plates..." },
      ],
    });

    renderStage(<StageRunning stage="cast" itemsDone={2} itemsTotal={4} />);

    expect(screen.getByText("Generating character reference sheets...")).toBeTruthy();
    expect(screen.getByText("Using existing ref sheet for Marlow")).toBeTruthy();
    expect(screen.getByText("Generating location plates...")).toBeTruthy();
    // Other stages and error lines stay out of the ticker.
    expect(screen.queryByText("Drawing panel batch 1-8 of 32")).toBeNull();
    expect(screen.queryByText("Failed ref sheet for Ada: timeout")).toBeNull();
  });

  it("caps the ticker at three lines, newest last", () => {
    usePipelineStore.setState({
      events: [1, 2, 3, 4, 5].map((n) => ({
        type: "log",
        stage: "extract",
        level: "info",
        message: `Step ${n}`,
      })),
    });

    renderStage(<StageRunning stage="extract" />);

    expect(screen.queryByText("Step 1")).toBeNull();
    expect(screen.queryByText("Step 2")).toBeNull();
    expect(screen.getByText("Step 3")).toBeTruthy();
    expect(screen.getByText("Step 4")).toBeTruthy();
    expect(screen.getByText("Step 5")).toBeTruthy();
  });

  it("keeps all Pages operations in Station 03 rather than exposing backend ordinals", () => {
    const { rerender } = renderStage(<StageRunning stage="adapt" />);
    expect(screen.getByText("03")).toBeTruthy();
    rerender(<I18nProvider><StageRunning stage="draw" /></I18nProvider>);
    expect(screen.getByText("03")).toBeTruthy();
    expect(screen.queryByText("07")).toBeNull();
  });
});


describe("Long-running Story and Pages work", () => {
  it.each(["extract", "brief", "adapt", "plan"] as const)("uses an active step instead of a resetting percentage for %s", (stage) => {
    const { rerender } = renderStage(<StageRunning stage={stage} itemsDone={1} itemsTotal={1} />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByText(/\d+%/)).toBeNull();
    expect(screen.getByText("Work in progress")).toBeTruthy();
    expect(screen.getByRole("list").querySelector('[aria-current="step"]')?.textContent).toContain("In progress");
    rerender(<I18nProvider><StageRunning stage={stage} itemsDone={0} itemsTotal={8} /></I18nProvider>);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByText("This step can take several minutes. Results appear when the step finishes.")).toBeTruthy();
  });

  it("advances the Pages checklist when adaptation finishes", () => {
    const { rerender } = renderStage(<StageRunning stage="adapt" />);
    expect(screen.getByText("Adapting your story", { selector: "li span" }).closest("li")?.getAttribute("aria-current")).toBe("step");
    rerender(<I18nProvider><StageRunning stage="plan" /></I18nProvider>);
    expect(screen.getByText("Adapting your story").closest("li")?.textContent).toContain("Done");
    expect(screen.getByText("Planning your pages", { selector: "li span" }).closest("li")?.getAttribute("aria-current")).toBe("step");
  });
});
