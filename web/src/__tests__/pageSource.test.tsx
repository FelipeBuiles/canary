import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PageSourcePanel } from "../components/pages/PageSourcePanel";
import { I18nProvider } from "../i18n";
import type { CompletePageSummary, PageSourceView } from "../types/api";

let result: { data?: PageSourceView; error?: Error | null; isLoading?: boolean } = {};

vi.mock("../api/queries", () => ({
  usePageSource: () => result,
}));

const box = (x: number, y: number) => ({ x, y, width: 0.4, height: 0.3 });

function view(geometryRevision: number | null = 2): PageSourceView {
  return {
    page_number: 1,
    page_revision: 1,
    passages: [{
      scene_title: "The harbour",
      units: [
        { id: "source-1", ordinal: 1, segments: [
          { text: "The harbour lay under a green fog.", kind: "depicted", content_ids: ["panel-1", "panel-2"] },
          { text: " ", kind: null, content_ids: [] },
        ] },
        { id: "source-2", ordinal: 2, segments: [
          { text: "Johansen said ", kind: null, content_ids: [] },
          { text: "the idol was older than the sea itself", kind: "lettering", content_ids: ["panel-2"] },
          { text: ".", kind: null, content_ids: [] },
        ] },
      ],
    }],
    panels: [
      { id: "panel-1", order: 1, panel_role: "establishing", box: box(0, 0) },
      { id: "panel-2", order: 2, panel_role: "standard", box: box(0.5, 0) },
    ],
    geometry_render_revision: geometryRevision,
  };
}

const item = {
  page: { page_number: 1, revision: 1, content_sha256: "a", content: [], reading_order: [] },
  active_render: { render: { revision: 2 } },
  issues: [],
  failure: null,
  analysis_recovery: { status: "checked", requires_paid_call: false },
  lettering_mode: "baked",
} as unknown as CompletePageSummary;

function renderPanel() {
  return render(<I18nProvider><PageSourcePanel project="book" item={item} /></I18nProvider>);
}

function outline(id: string) {
  return screen.getByTestId(`source-panel-${id}`);
}

describe("Page source view", () => {
  beforeEach(() => {
    result = { data: view(), error: null, isLoading: false };
  });

  it("shows the exact manuscript passage with lettering and depiction marked", () => {
    renderPanel();

    expect(screen.getByText("The harbour")).toBeTruthy();
    const lettering = screen.getByText("the idol was older than the sea itself");
    expect(lettering.tagName).toBe("MARK");
    expect(lettering.dataset.kind).toBe("lettering");
    expect(lettering.getAttribute("title")).toBe("Lettered in panel 2");
    const depicted = screen.getByText("The harbour lay under a green fog.");
    expect(depicted.dataset.kind).toBe("depicted");
    expect(depicted.getAttribute("title")).toBe("Drawn in panel 1, 2");
    expect(screen.getByText(/Johansen said/).tagName).toBe("SPAN");
  });

  it("outlines only the cited panels while a highlight is pointed at or focused", () => {
    renderPanel();
    expect(outline("panel-1").className).toContain("opacity-0");
    expect(outline("panel-2").className).toContain("opacity-0");

    const lettering = screen.getByText("the idol was older than the sea itself");
    fireEvent.mouseEnter(lettering);
    expect(outline("panel-1").className).toContain("opacity-0");
    expect(outline("panel-2").className).toContain("opacity-100");
    fireEvent.mouseLeave(lettering);
    expect(outline("panel-2").className).toContain("opacity-0");

    // Keyboard users reach the same outline; depiction spans every panel of its beat.
    const depicted = screen.getByText("The harbour lay under a green fog.");
    expect(depicted.getAttribute("tabindex")).toBe("0");
    fireEvent.focus(depicted);
    expect(outline("panel-1").className).toContain("opacity-100");
    expect(outline("panel-2").className).toContain("opacity-100");
    fireEvent.blur(depicted);
    expect(outline("panel-1").className).toContain("opacity-0");
  });

  it("never draws outlines measured on different art", () => {
    result = { data: view(1), error: null, isLoading: false };
    renderPanel();

    expect(screen.queryByTestId("source-panel-panel-1")).toBeNull();
    expect(screen.getByText("Panel outlines are not available for this artwork.")).toBeTruthy();
    const lettering = screen.getByText("the idol was older than the sea itself");
    expect(lettering.getAttribute("tabindex")).toBeNull();
  });

  it("explains a rejected lineage with the server's rerun instruction", () => {
    result = { data: undefined, error: new Error("API 409: Page 1 was planned from an older adaptation. Re-run Plan."), isLoading: false };
    renderPanel();

    expect(screen.getByRole("alert").textContent).toBe("The source for this page is not available.");
    expect(screen.getByText("Page 1 was planned from an older adaptation. Re-run Plan.")).toBeTruthy();
  });
});
