import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ComicPage, LetteringStyle, PageSummary } from "../types/api";

vi.mock("../components/compose/ScaledContainer", () => ({
  ScaledContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../components/compose/ComicPageCanvas", () => ({
  ComicPageCanvas: ({
    page,
    lettering,
    imageBaseUrl,
  }: {
    page: ComicPage;
    lettering?: LetteringStyle;
    imageBaseUrl: string;
  }) => (
    <div
      data-testid={`comic-page-${page.page_number}`}
      data-theme={lettering?.theme}
      data-image-base={imageBaseUrl}
    />
  ),
}));

import { PreviewMode } from "../components/compose/PreviewMode";

const page: ComicPage = {
  page_number: 1,
  source_page_id: null,
  layout: "1",
  layout_mode: "grid",
  panels: [],
};

const pageList: PageSummary[] = [{ page_number: 1, panel_count: 0, layout: "1" }];

const lettering = {
  theme: "gothic",
} as LetteringStyle;

describe("PreviewMode", () => {
  it("uses the live compose canvas for the export spread", () => {
    const { container } = render(
      <PreviewMode
        project="project one"
        pages={[page]}
        pageList={pageList}
        lettering={lettering}
        isLoading={false}
        pageIdx={0}
        isExporting={false}
        outputLanguage="en"
        isTranslatingBubbles={false}
        exportError={null}
        issues={[]}
        onPageSelect={vi.fn()}
        onExport={vi.fn()}
        onOutputLanguageChange={vi.fn()}
        onTranslateBubbles={vi.fn()}
      />,
    );

    const canvas = screen.getByTestId("comic-page-1");
    expect(canvas.getAttribute("data-theme")).toBe("gothic");
    expect(canvas.getAttribute("data-image-base")).toBe("/api/projects/project%20one/files");
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("passes an explicit issue override after the user confirms export anyway", async () => {
    const user = userEvent.setup();
    const onExport = vi.fn();
    render(
      <PreviewMode
        project="project one"
        pages={[page]}
        pageList={pageList}
        lettering={lettering}
        isLoading={false}
        pageIdx={0}
        isExporting={false}
        outputLanguage="en"
        isTranslatingBubbles={false}
        exportError={null}
        issues={[{
          id: "lettering_stack_too_tall:1:scene_001-001:",
          type: "lettering_stack_too_tall",
          severity: "error",
          message: "Panel 1 automatic lettering uses 44% of the panel height.",
          pageNumber: 1,
          panelId: "scene_001-001",
        }]}
        onPageSelect={vi.fn()}
        onExport={onExport}
        onOutputLanguageChange={vi.fn()}
        onTranslateBubbles={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "↓ DOWNLOAD PDF" }));
    await user.click(screen.getByRole("button", { name: "EXPORT PDF ANYWAY" }));

    expect(onExport).toHaveBeenCalledWith("pdf", true);
  });
});
