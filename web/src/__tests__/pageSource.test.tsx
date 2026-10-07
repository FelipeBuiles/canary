import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LetteringElement } from "@lettering-engine";
import { PageSourcePanel } from "../components/pages/PageSourcePanel";
import { I18nProvider } from "../i18n";
import { ApiError } from "../api/client";
import type { CompletePageSummary, PageSourceView } from "../types/api";

let result: { data?: PageSourceView; error?: Error | null; isLoading?: boolean } = {};

vi.mock("../api/queries", () => ({
  usePageSource: () => result,
}));

const passages: PageSourceView["passages"] = [{
  scene_title: "The harbour",
  units: [
    { id: "source-1", ordinal: 1, segments: [
      { text: "The harbour lay under a green fog.", kind: "depicted", lettering_item_ids: [] },
      { text: " ", kind: null, lettering_item_ids: [] },
    ] },
    { id: "source-2", ordinal: 2, segments: [
      { text: "Johansen said ", kind: null, lettering_item_ids: [] },
      { text: "the idol was older than the sea itself", kind: "lettering", lettering_item_ids: ["letter-1"] },
      { text: ".", kind: null, lettering_item_ids: [] },
    ] },
  ],
}];

function element(): LetteringElement {
  const placement = { x: 0.1, y: 0.6, width: 0.5, height: 0.2 };
  return {
    id: "el-1", source_lettering_item_id: "letter-1", role: "speech", text_by_locale: { source: "copy" },
    suggested_placement: placement, placement, hidden: false, style_override: null, tail_target: null,
    suggested_tail_target: null, rotation: -8, scale: 1.5, z_index: 0, tight_box: false, resolved: null,
  } as LetteringElement;
}

function integratedView(renderRevision: number | null = 2): PageSourceView {
  return {
    page_number: 1, page_revision: 1, passages,
    lettering: [{ id: "letter-1", text: "The idol was older than the sea itself!", element: null,
      region: renderRevision == null ? null : { x: 0.2, y: 0.1, width: 0.3, height: 0.05 } }],
    geometry: renderRevision == null ? null : { source: "text_check", render_revision: renderRevision },
  };
}

function editableView(letteringRevision = 4): PageSourceView {
  return {
    page_number: 1, page_revision: 1, passages,
    lettering: [{ id: "letter-1", text: "The idol was older than the sea itself!", element: element(), region: null }],
    geometry: { source: "lettering_placement", lettering_revision: letteringRevision },
  };
}

function item(mode: "baked" | "hybrid") {
  return {
    page: { page_number: 1, revision: 1, content_sha256: "a", content: [], reading_order: [] },
    active_render: { render: { revision: 2 } },
    issues: [], failure: null,
    analysis_recovery: { status: "checked", requires_paid_call: false },
    lettering_mode: mode,
    lettering_revision: mode === "hybrid" ? 4 : null,
  } as unknown as CompletePageSummary;
}

function renderPanel(mode: "baked" | "hybrid" = "baked") {
  return render(<I18nProvider><PageSourcePanel project="book" item={item(mode)} /></I18nProvider>);
}

const outline = () => screen.getByTestId("source-lettering-letter-1");

describe("Page source view", () => {
  beforeEach(() => {
    result = { data: integratedView(), error: null, isLoading: false };
  });

  it("shows the manuscript passage with lettering and drawn detail marked", () => {
    renderPanel();

    expect(screen.getByText("The harbour")).toBeTruthy();
    const lettering = screen.getByText("the idol was older than the sea itself");
    expect(lettering.tagName).toBe("MARK");
    expect(lettering.getAttribute("title")).toBe("Became lettering: The idol was older than the sea itself!");
    const depicted = screen.getByText("The harbour lay under a green fog.");
    expect(depicted.dataset.kind).toBe("depicted");
    expect(depicted.getAttribute("title")).toBe("Drawn on this page");
    // The model composes the page: drawn detail is never pinned to a place.
    expect(depicted.getAttribute("tabindex")).toBeNull();
    expect(screen.getByText(/Johansen said/).tagName).toBe("SPAN");
  });

  it("outlines the text-check region of integrated lettering while pointed at or focused", () => {
    renderPanel();
    expect(outline().className).toContain("opacity-0");
    expect(outline().style.left).toBe("19.2%");

    const lettering = screen.getByText("the idol was older than the sea itself");
    fireEvent.mouseEnter(lettering);
    expect(outline().className).toContain("opacity-100");
    fireEvent.mouseLeave(lettering);
    expect(outline().className).toContain("opacity-0");
    fireEvent.focus(lettering);
    expect(outline().className).toContain("opacity-100");
    fireEvent.blur(lettering);
    expect(outline().className).toContain("opacity-0");
  });

  it("outlines editable lettering from its saved element, scaled and rotated about its center", () => {
    result = { data: editableView(), error: null, isLoading: false };
    renderPanel("hybrid");

    // 0.5 × 0.2 body at 1.5× around its center (0.35, 0.7).
    const percent = (value: string) => Number.parseFloat(value);
    expect(percent(outline().style.left)).toBeCloseTo(-2.5);
    expect(percent(outline().style.top)).toBeCloseTo(55);
    expect(percent(outline().style.width)).toBeCloseTo(75);
    expect(percent(outline().style.height)).toBeCloseTo(30);
    expect(outline().style.transform).toBe("rotate(-8deg)");
  });

  it("never outlines positions measured on other artwork", () => {
    result = { data: editableView(3), error: null, isLoading: false };
    const { unmount } = renderPanel("hybrid");
    expect(screen.queryByTestId("source-lettering-letter-1")).toBeNull();
    expect(screen.getByText("Lettering positions are not available for this artwork.")).toBeTruthy();
    unmount();

    result = { data: integratedView(1), error: null, isLoading: false };
    renderPanel();
    expect(screen.queryByTestId("source-lettering-letter-1")).toBeNull();
    expect(screen.getByText("the idol was older than the sea itself").getAttribute("tabindex")).toBeNull();
  });

  it("says when integrated lettering needs a text check to be located", () => {
    result = { data: integratedView(null), error: null, isLoading: false };
    renderPanel();

    expect(screen.getByText("Lettering positions appear after this page's text check.")).toBeTruthy();
  });

  it("explains a rejected lineage with the server's rerun instruction", () => {
    result = { data: undefined, error: new ApiError(409, "Page 1 was planned from an older adaptation. Re-run Plan."), isLoading: false };
    renderPanel();

    expect(screen.getByRole("alert").textContent).toContain("The source for this page is not available.");
    expect(screen.getByText("Page 1 was planned from an older adaptation. Re-run Plan.").closest("details")).toBeNull();
  });
});
