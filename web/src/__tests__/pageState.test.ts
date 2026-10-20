import { describe, expect, it } from "vitest";
import type { CompletePageSummary, GenerationJob } from "../types/api";
import { pageDisplayImage, pageState } from "../lib/pageState";
const page = (overrides = {}) => ({ page: { page_number: 1 }, active_render: { render: { revision: 2 } }, issues: [], failure: null, analysis_recovery: { status: "checked" }, ...overrides }) as unknown as CompletePageSummary;
describe("page presentation policy", () => {
  it.each([
    [{}, {}, null],
    [{ lettering_placement_review_needed: true }, {}, "placement"],
    [{ lettering_placement_review_needed: true, issues: [{ status: "open" }] }, {}, "flagged"],
    [{ issues: [{ status: "open" }, { status: "revised" }] }, {}, "confirm-fix"],
    [{ redraw: { changed_references: ["a"] }, issues: [{ status: "revised" }] }, {}, "earlier-look"],
    [{ analysis_recovery: { status: "stale_render" }, redraw: { changed_references: ["a"] } }, {}, "stale"],
    [{ analysis_recovery: { status: "stale_render" } }, { starting: true }, "revising"],
  ])("applies badge precedence", (overrides, input, badge) => {
    expect(pageState(page(overrides), input).badge).toBe(badge);
  });
  it("suppresses stale failures after checked evidence and blocks retry after artwork exists", () => {
    const failure = { status: "failed", recoverable: true, classification: "error" } as GenerationJob;
    expect(pageState(page(), { failure }).failure).toBeNull();
    expect(pageState(page({ analysis_recovery: { status: "failed" } }), { failure }).canRetryGeneration).toBe(false);
    expect(pageState(page({ active_render: null, analysis_recovery: { status: "failed" } }), { failure }).canRetryGeneration).toBe(true);
  });
  it("does not keep a failed stage's unsubmitted batch drawing", () => {
    expect(pageState(page(), { batch: true, drawFailed: true }).drawing).toBe(false);
    expect(pageState(page(), { batch: true, drawFailed: true, submitted: true }).drawing).toBe(true);
  });
  it("chooses the edition image and keys editable previews by lettering revision", () => {
    const input = { pageNumber: 1, revision: 2 };
    expect(pageDisplayImage("p", input)).toContain("/renders/2/preview");
    expect(pageDisplayImage("p", { ...input, hybrid: true, letteringRevision: 3 })).toContain("lettering");
    expect(pageDisplayImage("p", { ...input, hybrid: true, letteringRevision: 3 })).not.toBe(pageDisplayImage("p", { ...input, hybrid: true, letteringRevision: 4 }));
  });
});
