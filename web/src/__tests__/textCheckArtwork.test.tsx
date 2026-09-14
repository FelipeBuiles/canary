import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { TextCheckArtwork } from "../components/pages/TextCheckArtwork";
import type { PageIssue } from "../types/api";

let analysisHash = "original";
vi.mock("../api/queries", () => ({
  useCompletePage: () => ({ data: {
    renders: [{ render: { revision: 1, image_sha256: "original", width: 1000, height: 1500 } },
      { render: { revision: 2, image_sha256: "redraw", width: 1000, height: 1500 } }],
    analyses: [{ render_revision: 1, render_image_sha256: analysisHash,
      ocr_observations: [{ id: "ocr_001", text: "Correct." }, { id: "ocr_002", text: "Wrong." }],
      observed_regions: [{ id: "region_001", polygon: [[0.1, 0.1], [0.8, 0.2]] },
        { id: "region_002", polygon: [[0.2, 0.4], [0.7, 0.5]] }],
    }],
  } }),
}));
const issue = {
  page_number: 1, render_revision: 1,
  evidence: ['expected_text=["Correct.","Right."]'],
} as PageIssue;

describe("Text check artwork evidence", () => {
  it("crops the disputed text from the checked revision, not a subsequent redraw", () => {
    analysisHash = "original";
    const { container } = render(<I18nProvider><TextCheckArtwork project="demo" issue={issue} /></I18nProvider>);
    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("190 585 520 180");
    expect(container.querySelector("image")?.getAttribute("href")).toContain("/renders/1");
  });
  it("offers the original image but never crops using evidence from different pixels", () => {
    analysisHash = "wrong-pixels";
    render(<I18nProvider><TextCheckArtwork project="demo" issue={issue} /></I18nProvider>);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("link").getAttribute("href")).toContain("/renders/1");
  });
});
