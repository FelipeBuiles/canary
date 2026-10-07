import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "../i18n";
import { LetteringIssueCard } from "../components/pages/LetteringEvidence";
import type { PageIssue } from "../types/api";
const head = "The crowded market woke before dawn and lit every";
const tail = "while Mara hurried past the river gate in the rain";
const expectedPassage = `${head} lantern ${tail}`;
const recognizedPassage = `${head} lantarn ${tail}`;
function singleTypoIssue(): PageIssue {
  return {
    id: "ocr-1",
    issue_type: "misspelled_lettering",
    classification: "invariant_failure",
    correction_kind: "copy_change",
    correction_owner: "draw",
    page_number: 1,
    render_revision: 2,
    evidence: [
      `expected_text=${JSON.stringify([expectedPassage])}`,
      `recognized_text=${JSON.stringify([recognizedPassage])}`,
    ],
    requested_correction: "Fix the misspelled sign.",
    status: "open",
    resolution_revision: null,
  };
}
function renderCard() {
  return render(<I18nProvider>
    <LetteringIssueCard issue={singleTypoIssue()} />
  </I18nProvider>);
}
describe("LetteringIssueCard evidence display", () => {
  it("keeps the default summary compact on a one-character mismatch", () => {
    const { container } = renderCard();
    // Long unchanged context on both sides is cropped, never dumped verbatim.
    expect(container.textContent).toContain("…");
    const items = [...container.querySelectorAll("li")];
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.textContent?.includes(expectedPassage)).toBe(false);
      expect(item.textContent?.includes(recognizedPassage)).toBe(false);
    }
    // The differing letter itself stays visible in the compact row.
    expect(container.textContent).toContain("lantarn");
  });
  it("preserves the full passages in the evidence disclosure", () => {
    const { container } = renderCard();
    const definitions = [...container.querySelectorAll("dd")].map((entry) => entry.textContent ?? "");
    expect(definitions.some((text) => text.includes(expectedPassage))).toBe(true);
    expect(definitions.some((text) => text.includes(recognizedPassage))).toBe(true);
  });
  it("shows independent close-up evidence and uncertainty without claiming a fix", () => {
    const issue = singleTypoIssue();
    issue.evidence.push("crop_check_status=disagrees", `crop_recognized_text=${JSON.stringify([expectedPassage])}`);
    const { container } = render(<I18nProvider><LetteringIssueCard issue={issue} /></I18nProvider>);
    expect(container.textContent).toContain("Text check is uncertain");
    expect(container.textContent).toContain("The text checks disagree.");
    expect(container.textContent).toContain("First read:");
    expect(container.textContent).toContain("CLOSE-UP READ");
    expect(container.querySelectorAll("dd")[2]?.textContent).toContain(expectedPassage);
    expect(container.textContent).not.toContain("CONFIRMED");
  });
  it("treats an unavailable or weak close-up read as inconclusive", () => {
    const issue = singleTypoIssue();
    issue.evidence.push("crop_check_status=inconclusive", "crop_recognized_text=[]");
    const { container } = render(<I18nProvider><LetteringIssueCard issue={issue} /></I18nProvider>);
    expect(container.textContent).toContain("Text check is uncertain");
    expect(container.textContent).toContain("The close-up text check was inconclusive.");
    expect(container.textContent).toContain("No readable lettering found");
  });
});
