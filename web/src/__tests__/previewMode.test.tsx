import { render, screen } from "@testing-library/react";
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
        onReviewLettering={vi.fn()}
        onOutputLanguageChange={vi.fn()}
        onTranslateBubbles={vi.fn()}
      />,
    );

    const canvas = screen.getByTestId("comic-page-1");
    expect(canvas.getAttribute("data-theme")).toBe("gothic");
    expect(canvas.getAttribute("data-image-base")).toBe("/api/projects/project%20one/files");
    expect(container.querySelector("iframe")).toBeNull();
  });
});
