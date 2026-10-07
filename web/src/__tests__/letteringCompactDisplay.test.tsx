import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
  it("reads a second look that matches the script as a probable misread, without claiming a fix", () => {
    const issue = singleTypoIssue();
    issue.evidence.push("crop_check_status=disagrees", `crop_recognized_text=${JSON.stringify([expectedPassage])}`,
      `crop_readings=${JSON.stringify([{ first: recognizedPassage, close_up: expectedPassage, verdict: "disagrees" }])}`);
    const { container } = render(<I18nProvider><LetteringIssueCard issue={issue} /></I18nProvider>);
    expect(container.textContent).toContain("Probably a misread");
    expect(container.textContent).toContain("A closer look matches the script");
    expect(container.textContent).toContain("matching the script.");
    expect(container.querySelectorAll("dd")[2]?.textContent).toContain(expectedPassage);
    expect(container.textContent).not.toContain("CONFIRMED");
    expect(container.textContent).not.toContain("First read");
    expect(container.textContent).not.toContain("Close-up");
  });
  it("treats the same reading twice as a likely difference", () => {
    const issue = singleTypoIssue();
    issue.evidence.push("crop_check_status=agrees", `crop_recognized_text=${JSON.stringify([recognizedPassage])}`,
      `crop_readings=${JSON.stringify([{ first: recognizedPassage, close_up: recognizedPassage, verdict: "agrees" }])}`);
    const { container } = render(<I18nProvider><LetteringIssueCard issue={issue} /></I18nProvider>);
    expect(container.textContent).toContain("Possible wording difference");
    expect(container.textContent).toContain("read the same way twice");
    expect(container.textContent).toContain("Read the same way twice.");
  });
  it("treats an unavailable or weak second look as hard to read", () => {
    const issue = singleTypoIssue();
    issue.evidence.push("crop_check_status=inconclusive", "crop_recognized_text=[]");
    const { container } = render(<I18nProvider><LetteringIssueCard issue={issue} /></I18nProvider>);
    expect(container.textContent).toContain("Hard to read");
    expect(container.textContent).toContain("This lettering was hard to read.");
  });
  it("gives each difference its own note when lines disagree with each other", () => {
    const issue = singleTypoIssue();
    issue.evidence = [
      `expected_text=${JSON.stringify(["Robbins", "dream"])}`,
      `recognized_text=${JSON.stringify(["Robins", "dreem"])}`,
      "crop_check_status=disagrees", "crop_recognized_text=[\"Robins\",\"dream\"]",
      `crop_readings=${JSON.stringify([
        { first: "Robins", close_up: "Robins", verdict: "agrees" },
        { first: "dreem", close_up: "dream", verdict: "disagrees" },
      ])}`,
    ];
    const { container } = render(<I18nProvider><LetteringIssueCard issue={issue} /></I18nProvider>);
    const rows = [...container.querySelectorAll("li")].map((row) => row.textContent ?? "");
    expect(rows.some((row) => row.includes("Robins") && row.includes("Read the same way twice."))).toBe(true);
    expect(rows.some((row) => row.includes("dreem") && row.includes("“dream”, matching the script"))).toBe(true);
    // One line still reads wrong twice, so the page-level message stays cautious.
    expect(container.textContent).toContain("probably differs from the script");
  });
  it("explains an unfinished second look without claiming no text was present", () => {
    const issue = singleTypoIssue();
    issue.evidence.push("crop_check_status=inconclusive", "crop_check_complete=false", "crop_outcome_unknown=true",
      `crop_readings=${JSON.stringify([{ first: recognizedPassage, close_up: "", verdict: "inconclusive" }])}`);
    const { container } = render(<I18nProvider><LetteringIssueCard issue={issue} /></I18nProvider>);
    expect(container.textContent).toContain("hasn’t been double-checked yet");
    expect(container.textContent).toContain("Not double-checked.");
    expect(container.textContent).not.toContain("No readable lettering found");
  });
  it("offers a free double-check only for an unfinished second look", () => {
    const issue = singleTypoIssue();
    issue.evidence.push("crop_check_status=inconclusive", "crop_check_complete=false",
      `crop_readings=${JSON.stringify([{ first: recognizedPassage, close_up: "", verdict: "inconclusive" }])}`);
    const onRetry = vi.fn();
    const { getByRole } = render(<I18nProvider>
      <LetteringIssueCard issue={issue} secondLook={{ onRetry, busy: false }} />
    </I18nProvider>);
    fireEvent.click(getByRole("button", { name: "DOUBLE-CHECK" }));
    expect(onRetry).toHaveBeenCalledOnce();
    const finished = singleTypoIssue();
    finished.evidence.push("crop_check_status=inconclusive", "crop_recognized_text=[]");
    const { container } = render(<I18nProvider>
      <LetteringIssueCard issue={finished} secondLook={{ onRetry, busy: false }} />
    </I18nProvider>);
    expect(container.querySelector("button")).toBeNull();
  });
  it("matches a hyphen-wrapped closer look to the script", () => {
    const issue = singleTypoIssue();
    issue.evidence = [
      `expected_text=${JSON.stringify(["It was wonderful."])}`,
      `recognized_text=${JSON.stringify(["It was wondrful."])}`,
      "crop_check_status=disagrees",
      `crop_readings=${JSON.stringify([{ first: "It was wondrful.", close_up: "It was won- derful.", verdict: "disagrees" }])}`,
    ];
    const { container } = render(<I18nProvider><LetteringIssueCard issue={issue} /></I18nProvider>);
    expect(container.textContent).toContain("Probably a misread");
  });
});
