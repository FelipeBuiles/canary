import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { PageChecks } from "../components/pages/PageChecks";
import type { VisualReviewReference } from "../api/pages";
import type { CompletePageSummary } from "../types/api";

const state = vi.hoisted(() => ({ references: [] as VisualReviewReference[], uncertain: [] as string[] }));
const idle = { mutate: vi.fn(), isPending: false, error: null };
vi.mock("../api/queries", () => ({
  useAcceptPageIssue: () => idle,
  useDismissPageIssue: () => idle,
  useSecondLook: () => idle,
}));
vi.mock("../api/pageRevisions", () => ({
  useCachedVisualReview: () => ({ data: { references: state.references, report: { uncertain: state.uncertain } } }),
  useReviewPageVisuals: () => idle,
  useVisualReviewEstimate: () => ({ data: undefined, error: null }),
}));

function reference(id: string, overrides: Partial<VisualReviewReference>): VisualReviewReference {
  return {
    order: 1, id, entity_id: id, appearance_state_id: null, label: id, display_label: id,
    visual_anchor: null, media_type: "image/png", image_path: `refs/${id}.png`, ...overrides,
  };
}

function renderChecks() {
  const item = {
    page: { page_number: 1 }, issues: [], visual_reviewed: true,
    analysis_recovery: { status: "checked", requires_paid_call: false },
  } as unknown as CompletePageSummary;
  render(<I18nProvider><PageChecks project="demo" item={item} pageIsDrawing={false} onRetryText={vi.fn()} retryingText={false}
    draft={{ locked: false, included: () => null, include: vi.fn() }} /></I18nProvider>);
}

describe("what the artwork was compared with", () => {
  it("groups pictured references by kind, with the style proof as an image and a short name", () => {
    state.references = [
      reference("herbert-ref", { kind: "character", display_label: "Herbert", visual_anchor: "young man, dark curly hair" }),
      reference("selected-style-proof", { entity_id: "", kind: "style", display_label: "Selected style", image_path: "samples/style_2.png" }),
      reference("parlour-ref", { kind: "location", display_label: "Parlour" }),
      reference("board-ref", { kind: "prop", display_label: "Chessboard", image_path: null }),
    ];
    state.uncertain = ["Whether the blinds are drawn."];
    renderChecks();
    fireEvent.click(screen.getByText("Compared with"));

    const style = screen.getByRole("region", { name: "Style" });
    expect(within(style).getByText("Selected style")).toBeTruthy();
    expect(style.querySelector("img")?.getAttribute("src")).toContain("samples/style_2.png");
    expect(screen.queryByText(/Rendering authority/)).toBeNull();
    // Groups follow the Cast's order, not the request's.
    expect(screen.getAllByRole("region").map((region) => region.getAttribute("aria-label")))
      .toEqual(["Checks", "Style", "Characters", "Places", "Objects", "COULDN'T TELL"]);
    // Descriptions stay out of the grid; the name carries them on hover.
    expect(screen.queryByText("young man, dark curly hair")).toBeNull();
    expect(within(screen.getByRole("region", { name: "Characters" })).getByText("Herbert").getAttribute("title"))
      .toMatch(/dark curly hair/i);
    // A reference without approved bytes shows its kind's icon, never a dead thumbnail or a letter.
    expect(screen.getByRole("region", { name: "Objects" }).querySelector("img")).toBeNull();
    expect(screen.getAllByRole("button", { name: /Zoom and inspect/ })).toHaveLength(3);
    expect(screen.getByText("Whether the blinds are drawn.")).toBeTruthy();
  });
});
