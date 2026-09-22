import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AdaptationDetails, PagePlanDetails } from "../components/pages/ReadingDetails";
import { I18nProvider } from "../i18n";
import type { BookAdaptation, BookPlan, CompletePageSummary, EditorialIssue } from "../types/api";

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

function renderPlan(pages: CompletePageSummary[] | undefined, detailsLoading = false, detailsError: unknown = null) {
  return render(<I18nProvider><PagePlanDetails plan={plan} pages={pages} detailsLoading={detailsLoading} detailsError={detailsError} /></I18nProvider>);
}

describe("Reading document details", () => {
  it.each(["adaptation", "plan"])("shows %s editorial concerns as optional notes", (kind) => {
    const issues: EditorialIssue[] = [{ id: "note", owner_stage: kind === "adaptation" ? "adapt" : "plan", code: "narrative_review_padding", message: "Optional improvement.",
      evidence: ["The closing pause could be shorter.", "Consider one fewer panel."] }];
    render(<I18nProvider>{kind === "adaptation"
      ? <AdaptationDetails adaptation={{ revision: 1, editorial_issues: issues }} />
      : <PagePlanDetails plan={{ ...plan, editorial_issues: issues }} pages={[]} detailsLoading={false} detailsError={null} />}
    </I18nProvider>);
    const summary = screen.getByText(/Optional editorial notes/, { selector: "summary" });
    expect(summary.parentElement).toHaveProperty("open", false);
    fireEvent.click(summary);
    expect(screen.getByText("These suggestions do not block completion or start another generation.")).toBeTruthy();
    expect(screen.getByText("The closing pause could be shorter.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("uses the plan's canonical order and keeps planned pages visible when details are missing", () => {
    renderPlan([page(1), page(3), page(9)]);
    expect(screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["Page 03", "Page 01", "Page 02"]);
    expect(screen.getByText("Layout for page 3")).toBeTruthy();
    expect(screen.queryByText("Layout for page 9")).toBeNull();
    expect(screen.getByText("Details for this planned page are not available yet.")).toBeTruthy();
    for (const link of screen.getAllByRole("link")) {
      expect(document.getElementById(link.getAttribute("href")!.slice(1))).not.toBeNull();
    }
    expect(screen.queryByText("Page turn")).toBeNull();
  });

  it("distinguishes loading details from an unavailable detail response", () => {
    const view = renderPlan(undefined, true);
    expect(screen.getAllByRole("status").map((item) => item.textContent)).toEqual(Array(3).fill("Loading page details…"));
    view.rerender(<I18nProvider><PagePlanDetails plan={plan} pages={undefined} detailsLoading={false} detailsError={new Error("Unavailable")} /></I18nProvider>);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getAllByText("Page details are not available right now.")).toHaveLength(3);
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(3);
  });

  it("shows all supplied treatment and lettering text without inventing absent sections", () => {
    const adaptation: BookAdaptation = {
      revision: 1, editorial_issues: [],
      treatment: { causal_spine: ["A promise starts the journey."], character_arcs: ["Mara learns to trust."], aftermath: ["The village rebuilds."] },
      beats: [{ id: "beat-1", order: 1, summary: "Mara makes a promise.", lettering: [{ id: "line-1", text: "I will return." }], transitions: [{ description: "Dawn breaks." }] }],
    };
    render(<I18nProvider><AdaptationDetails adaptation={adaptation} /></I18nProvider>);
    expect(screen.getByText("Mara makes a promise.").closest("details")).toBeNull();
    expect(screen.getByText("Mara learns to trust.").closest("details")?.querySelector("summary")?.textContent).toContain("Character arcs");
    expect(screen.getByText("The village rebuilds.")).toBeTruthy();
    expect(screen.getByText("I will return.")).toBeTruthy();
    expect(screen.getByText("Dawn breaks.")).toBeTruthy();
    expect(screen.queryByText("Reveals")).toBeNull();
    expect(screen.queryByText("Consequences")).toBeNull();
    expect(screen.queryByText("Appearance changes")).toBeNull();
  });

  it("states when treatment and beats are absent", () => {
    render(<I18nProvider><AdaptationDetails adaptation={{ revision: 1, editorial_issues: [] }} /></I18nProvider>);
    expect(screen.getByText("No narrative treatment is available yet.")).toBeTruthy();
    expect(screen.getByText("No adapted beats are available yet.")).toBeTruthy();
    expect(screen.queryByText("Lettering & story details")).toBeNull();
  });
});
