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
  it("renders fine with zero events", () => {
    renderStage(<StageRunning stage="cast" itemsDone={1} itemsTotal={4} />);
    expect(screen.getByText("RUNNING")).toBeTruthy();
    expect(screen.getByText("1 / 4")).toBeTruthy();
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
});
