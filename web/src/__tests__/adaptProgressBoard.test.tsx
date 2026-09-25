import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StageRunning } from "../components/composites/StagePlaceholder";
import { I18nProvider } from "../i18n";
import type { AdaptProgressSnapshot } from "../types/api";

function snapshot(overrides: Partial<AdaptProgressSnapshot> = {}): AdaptProgressSnapshot {
  return {
    kind: "adapt",
    phase: "drafting",
    serial_transport: true,
    source_units: 240,
    treatment: { spine: 7, reveals: 3, turns: 2, arcs: 2 },
    sections: [
      { units: 120, title: "The chamber", state: "done", beats: [["causal_event"], ["reveal"], ["reaction", "character_turn"]], lettering: 5, flagged: [] },
      { units: 80, title: null, state: "lettering", beats: [["transition"], ["reveal"]], lettering: null, flagged: [] },
      { units: 40, title: null, state: "queued", beats: null, lettering: null, flagged: [] },
    ],
    sections_done: 1,
    beats: 5,
    lettering: 5,
    rounds: [],
    max_rounds: 3,
    ...overrides,
  };
}

describe("Adapt progress board", () => {
  it("shows the validated script taking shape instead of the generic step list", () => {
    render(<I18nProvider><StageRunning stage="adapt" snapshot={snapshot()} /></I18nProvider>);

    expect(screen.getByText("Write beats and lettering").closest("li")?.getAttribute("aria-current")).toBe("step");
    expect(screen.getByText("Story shape: 7 story links · 3 reveals · 2 character turns.")).toBeTruthy();
    expect(screen.getByText("1/3")).toBeTruthy();
    expect(screen.getByText("240 source passages")).toBeTruthy();
    const sheet = screen.getByRole("list", { name: "Beat sheet" });
    const tiles = within(sheet).getAllByRole("listitem");
    // Five validated beats plus one placeholder for the part not yet staged.
    expect(tiles).toHaveLength(6);
    expect(tiles[1].getAttribute("aria-label")).toBe("Beat 2 · Reveal");
    expect(tiles[2].getAttribute("aria-label")).toBe("Beat 3 · Character turn · Reaction");
    expect(tiles[4].getAttribute("aria-label")).toBe("Beat 5 · Reveal");
    expect(tiles[5].getAttribute("aria-label")).toBe("Part 3 · Waiting");
    expect(screen.getByText(/Writing part 2\. 1 part waiting\. This model writes one part at a time/)).toBeTruthy();
    expect(screen.queryByText(/Results appear when the step finishes/)).toBeNull();
    expect(screen.queryByText("Adapting your story")).toBeTruthy();
  });

  it("marks the beats a check flagged and reports each round", () => {
    const base = snapshot();
    render(<I18nProvider><StageRunning stage="adapt" snapshot={snapshot({
      phase: "repairing",
      sections: [
        { ...base.sections[0], state: "repairing", flagged: [1] },
        { ...base.sections[1], state: "done", lettering: 2 },
      ],
      sections_done: 1,
      rounds: [{ round: 1, blocking: 1, notes: 2 }],
    })} /></I18nProvider>);

    expect(screen.getByText("Rewriting the parts the checks flagged.")).toBeTruthy();
    const tiles = within(screen.getByRole("list", { name: "Beat sheet" })).getAllByRole("listitem");
    expect(tiles[1].getAttribute("aria-label")).toBe("Beat 2 · Reveal · Needs a fix");
    expect(screen.getByText("Check 1 of 3")).toBeTruthy();
    expect(screen.getByText("Check 1: 1 issue to fix. 2 notes for your review.")).toBeTruthy();
    expect(screen.getByText(/Fixing part 1\./)).toBeTruthy();
  });

  it("ignores another stage's snapshot", () => {
    render(<I18nProvider><StageRunning stage="plan" snapshot={snapshot()} /></I18nProvider>);
    expect(screen.queryByRole("list", { name: "Beat sheet" })).toBeNull();
  });
});
