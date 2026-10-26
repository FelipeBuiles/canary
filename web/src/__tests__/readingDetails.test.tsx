import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AdaptationDetails, EditorialNotes, PagePlanDetails } from "../components/pages/ReadingDetails";
import { I18nProvider } from "../i18n";
import { entityNames } from "../lib/readingDocs";
import type { BookAdaptation, BookPlan, CompletePageSummary, EditorialIssue, StoryBible } from "../types/api";

const plan: BookPlan = {
  revision: 1,
  target_page_min: 2,
  target_page_max: 4,
  editorial_issues: [],
  rhythm_summary: "Hold the tension until the final reveal.",
  pages: [3, 1, 2].map((page_number) => ({ page_number, revision: 1, content_sha256: "a" })),
};
function page(page_number: number): CompletePageSummary {
  return {
    page: {
      page_number, revision: 1, content_sha256: "a", page_turn_role: "none",
      spread_role: "single", emphasis: "initial", density_intent: "sparse",
      rhythm_intent: "", layout_intent: `Layout for page ${page_number}`, content: [], reading_order: [],
    },
    active_render: null, issues: [], failure: null,
    analysis_recovery: { status: "undrawn", requires_paid_call: false },
  };
}
const bible = {
  characters: [{ id: "p0001s0001_mara", name: "Mara" }],
  locations: [{ id: "p0001s0001_market", name: "The Market" }],
  props: [],
} as unknown as StoryBible;

function Plan({ pages, detailsLoading = false, detailsError = null, onOpenBeat = vi.fn() }: {
  pages: CompletePageSummary[] | undefined; detailsLoading?: boolean; detailsError?: unknown; onOpenBeat?: (beat: string) => void;
}) {
  const [current, setCurrent] = useState<number | null>(null);
  return <I18nProvider><PagePlanDetails project="demo" plan={plan} pages={pages} names={entityNames(bible)}
    detailsLoading={detailsLoading} detailsError={detailsError} page={current} onPage={setCurrent} onOpenBeat={onOpenBeat} /></I18nProvider>;
}
const pageRows = () => within(screen.getByRole("navigation", { name: "Planned pages" })).getAllByRole("button").filter((row) => row.hasAttribute("data-plan-page"));

describe("Reading document details", () => {
  it("lists editorial notes as optional suggestions without actions", () => {
    const issues: EditorialIssue[] = [{ id: "note", owner_stage: "plan", code: "narrative_review_padding", message: "Optional improvement.",
      evidence: ["The closing pause could be shorter.", "Consider one fewer panel."] }];
    render(<I18nProvider><EditorialNotes issues={issues} /></I18nProvider>);
    expect(screen.getByText("Optional improvement.")).toBeTruthy();
    expect(screen.getByText("The closing pause could be shorter.")).toBeTruthy();
    expect(screen.getByText("These suggestions don't block anything.")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("uses the plan's canonical order and keeps planned pages visible when details are missing", () => {
    render(<Plan pages={[page(1), page(3), page(9)]} />);
    const rows = pageRows();
    expect(rows.map((row) => row.textContent?.match(/Page \d+/)?.[0])).toEqual(["Page 3", "Page 1", "Page 2"]);
    expect(rows[0].getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("Layout for page 3")).toBeTruthy();
    expect(screen.queryByText("Layout for page 9")).toBeNull();
    fireEvent.click(rows[2]);
    expect(screen.getByText("Details for this planned page are not available yet.")).toBeTruthy();
    expect(screen.getByText("Not drawn yet")).toBeTruthy();
  });

  it("turns pages with the arrow keys and the stage arrows", () => {
    render(<Plan pages={[page(1), page(2), page(3)]} />);
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText("Layout for page 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Layout for page 2")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Next page" })).toHaveProperty("disabled", true);
  });

  it("shows panels as structured staging with names instead of internal ids", () => {
    const detail = page(3);
    detail.page.page_turn_role = "reveal";
    detail.page.rhythm_intent = "A quiet pause before the reveal.";
    detail.page.layout_intent = "Three tiers that slow down.\n\nCanonical staging (non-lettering):\nPanel 1: Setting: (location: p0001s0001_market; environment visible: True)";
    detail.page.content = [{
      id: "panel-1", order: 1, beat_ids: ["beat_0004"], panel_role: "establishing",
      visual_intent: "Wide view of the market as p0001s0001_mara arrives.",
      lettering: [{ id: "l1", kind: "dialogue", text: "I will return.", speaker: "Mara" }],
      entity_ids: ["p0001s0001_market", "p0001s0001_mara"], appearance_states: {},
      camera: { shot: "wide", angle: "eye_level" },
      acting: [{ entity_id: "p0001s0001_mara", facing: "toward_viewer", gaze: "the crowd", expression: "resolved", gesture: "raising a hand" }],
    }];
    const onOpenBeat = vi.fn();
    render(<Plan pages={[detail]} onOpenBeat={onOpenBeat} />);
    expect(screen.getAllByText("Reveal")).toHaveLength(2);
    expect(screen.getAllByText("A quiet pause before the reveal.")).toHaveLength(2);
    expect(screen.getByText("Three tiers that slow down.")).toBeTruthy();
    expect(screen.queryByText(/Canonical staging/)).toBeNull();
    expect(screen.getByText("Establishing · Wide · Eye level")).toBeTruthy();
    expect(screen.getByText("Wide view of the market as Mara arrives.")).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "In this panel" })).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["The Market", "Mara"]);
    expect(screen.getByText("I will return.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("p0001s0001");
    fireEvent.click(screen.getByRole("button", { name: "Beat 4" }));
    expect(onOpenBeat).toHaveBeenCalledWith("beat_0004");
  });

  it("distinguishes loading details from an unavailable detail response", () => {
    const view = render(<Plan pages={undefined} detailsLoading />);
    expect(screen.getByRole("status").textContent).toBe("Loading page details…");
    view.rerender(<Plan pages={undefined} detailsError={new Error("Unavailable")} />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("Page details are not available right now.")).toBeTruthy();
    expect(pageRows()).toHaveLength(3);
  });

  it("groups beats under their page and shows treatment and lettering in full", () => {
    const adaptation: BookAdaptation = {
      revision: 1, editorial_issues: [],
      treatment: { causal_spine: ["A promise starts the journey."], character_arcs: ["Mara learns to trust."], aftermath: ["The village rebuilds."] },
      beats: [
        { id: "beat-1", order: 1, summary: "Mara makes a promise.", lettering: [{ id: "line-1", kind: "caption", text: "I will return." }], transitions: [{ description: "Dawn breaks." }] },
        { id: "beat-2", order: 2, summary: "The road waits." },
      ],
    };
    const first = page(1);
    first.page.content = [{ id: "panel", order: 1, beat_ids: ["beat-1"], panel_role: "standard", visual_intent: "", lettering: [], entity_ids: [], appearance_states: {}, camera: null, acting: [] }];
    const onOpenPage = vi.fn();
    render(<I18nProvider><AdaptationDetails project="demo" adaptation={adaptation} pages={[first]} onOpenPage={onOpenPage} /></I18nProvider>);
    expect(screen.getByText("A promise starts the journey.")).toBeTruthy();
    expect(screen.getByText("I will return.")).toBeTruthy();
    expect(screen.getByText("Dawn breaks.")).toBeTruthy();
    expect(screen.getByText("Mara learns to trust.").closest("details")?.querySelector("summary")?.textContent).toContain("Character arcs");
    expect(screen.getByText("The village rebuilds.")).toBeTruthy();
    expect(screen.queryByText("Reveals")).toBeNull();
    expect(screen.getByText("Not placed on a page")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open page 1 in the plan" }));
    expect(onOpenPage).toHaveBeenCalledWith(1);
  });

  it("states when treatment and beats are absent", () => {
    render(<I18nProvider><AdaptationDetails project="demo" adaptation={{ revision: 1, editorial_issues: [] }} pages={[]} onOpenPage={vi.fn()} /></I18nProvider>);
    expect(screen.getByText("No narrative treatment is available yet.")).toBeTruthy();
    expect(screen.getByText("No adapted beats are available yet.")).toBeTruthy();
  });
});
