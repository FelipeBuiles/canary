import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { StageFailureSummary } from "../components/pages/StageFailureSummary";
import { I18nProvider } from "../i18n";
import type { InvariantFailure } from "../types/api";

function failure(code: string, overrides: Partial<InvariantFailure> = {}): InvariantFailure {
  return { id: code, code, owner_stage: "plan", message: `Internal check: ${code}`,
    evidence: ["Expected internal artifact IDs."], ...overrides };
}

function renderSummary(failures: InvariantFailure[], recoveryStage: "adapt" | "plan" = "plan") {
  return render(<I18nProvider><StageFailureSummary failures={failures} recoveryStage={recoveryStage} /></I18nProvider>);
}

beforeEach(() => localStorage.clear());

describe("Author-facing stage checks", () => {
  it("groups related problems, consolidates repeated explanations, and keeps all support evidence collapsed", () => {
    renderSummary([
      failure("missing_panel_camera"),
      failure("protected_language_missing", { owner_stage: "adapt" }),
      failure("missing_essential_event", { owner_stage: "adapt" }),
      failure("missing_character_turn", { owner_stage: "adapt" }),
      failure("cross_page_appearance_state"),
      failure("narrative_review_invalid"),
    ], "adapt");

    expect(screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual([
      "Story coverage", "Dialogue and captions", "Character and scene continuity", "Page flow and staging", "Saved draft checks",
    ]);
    const story = screen.getByRole("region", { name: "Story coverage" });
    expect(within(story).getByText("2 checks")).toBeTruthy();
    expect(within(story).getAllByText("An important event or character change from your brief is missing from the script.")).toHaveLength(1);
    expect(screen.getByText("Resume or restart adaptation to check the script again before page planning continues.")).toBeTruthy();
    expect(screen.queryByText("Retry page planning to check these pages again.")).toBeNull();
    for (const detail of screen.getAllByText(/Internal check:/)) {
      expect(detail.closest("details")?.open).toBe(false);
    }
    fireEvent.click(within(story).getByText("Technical details"));
    expect(screen.getByText("Internal check: missing_essential_event").closest("details")?.open).toBe(true);
    expect(screen.getByText("Internal check: missing_character_turn").closest("details")?.open).toBe(true);
  });

  it("shows readable, unique page locations in numerical order without treating unrelated IDs as pages", () => {
    const camera = failure("missing_panel_camera", {
      artifact_ids: ["page_010", "page_002_content_001", "page_002_content_003", "beat_003", "page_000", "other_page_099"],
    });
    renderSummary([
      camera,
      camera,
      failure("staging_authority", { artifact_ids: ["page_003_content_001"] }),
    ]);

    const pages = screen.getByRole("region", { name: "Page flow and staging" });
    expect(within(pages).getByText("2 checks")).toBeTruthy();
    expect(within(pages).getByText("Pages: 2, 3, 10")).toBeTruthy();
    expect(within(pages).getAllByText("Some scenes need clearer directions for what the artwork should show and how it should be framed.")).toHaveLength(1);
    expect(screen.queryByText(/page_002_content/)).toBeNull();
    expect(screen.getByText("Retry page planning to check these pages again.")).toBeTruthy();
  });

  it("keeps an unfamiliar failure visible without presenting its internal message as the explanation", () => {
    renderSummary([failure("new_check", { artifact_ids: ["page_004"] })]);
    const group = screen.getByRole("region", { name: "Saved draft checks" });
    expect(within(group).getByText("Part of the generated draft could not be checked. Try again before continuing to drawing.")).toBeTruthy();
    expect(within(group).getByText("Page: 4")).toBeTruthy();
    expect(within(group).getByText("1 check")).toBeTruthy();
    expect(within(group).getByText("Internal check: new_check").closest("details")?.open).toBe(false);
  });

  it.each([
    ["es", "Diálogos y textos narrativos", "1 revisión", "Página: 4"],
    ["fr", "Dialogues et récitatifs", "1 vérification", "Page : 4"],
  ])("localizes grouped checks and locations in %s", async (locale, title, count, location) => {
    localStorage.setItem("canary.uiLanguage", locale);
    await act(async () => { renderSummary([failure("protected_language_missing", { artifact_ids: ["page_004"] })]); });
    const group = await screen.findByRole("region", { name: title });
    expect(within(group).getByText(count)).toBeTruthy();
    expect(within(group).getByText(location)).toBeTruthy();
    expect(within(group).queryByText("Wording you asked to keep exactly is missing from the comic script. Resume adaptation to letter the book’s exact wording, or change the phrase under Protected language in the Story room.")).toBeNull();
  });

  it("does not show an empty report", () => {
    renderSummary([]);
    expect(screen.queryByRole("region", { name: "What needs another check" })).toBeNull();
  });
});
