import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { SHOW_DEV_CONTENT_KEY } from "../lib/devContent";
import type { EditorialIssue, StageStatus } from "../types/api";

const previewCorrections = vi.fn();
const submitCorrections = vi.fn();
const reviewVisuals = vi.fn();
const dismissIssue = vi.fn();
const analyzePage = vi.fn();
const continueToBook = vi.fn();
const generatePage = vi.fn();
const runPipeline = vi.fn();
const trackGenerationJobs = vi.fn((project?: string, ids: string[] = []) => {
  void project;
  void ids;
  return { data: { jobs: [] } };
});
type TestStageInfo = {
  status: StageStatus;
  stale: boolean;
  items_done?: number;
  items_total?: number;
};
let stageStatuses: Record<"adapt" | "plan" | "draw", TestStageInfo> = {
  adapt: { status: "complete", stale: false },
  plan: { status: "complete", stale: false },
  draw: { status: "awaiting_review", stale: false },
};
let includeUndrawnPage = false;
let completePagesUnavailable = false;
let pageIssues: Array<Record<string, unknown>> | undefined;
let persistedPageFailure: Record<string, unknown> | null = null;
let persistedRenderedFailure: Record<string, unknown> | null = null;
let adaptationIssues: EditorialIssue[] = [];
let planIssues: EditorialIssue[] = [];
let planValidation: {
  invariant_failures: Array<{
    id: string;
    owner_stage: string;
    code: string;
    message: string;
    evidence: string[];
  }>;
  recommendations: string[];
} | undefined;
let generationJobResults: Array<{
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  classification?: string;
  user_message?: string;
  recoverable?: boolean;
  error?: string | null;
}> = [];
let previewResult: Record<string, unknown> | undefined;

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({
    data: {
      stages: stageStatuses,
    },
  }),
  useAdaptation: () => ({
    data: {
      treatment: { causal_spine: ["A quarrel seeds the voyage"] },
      beats: [{
        id: "beat-1",
        order: 1,
        summary: "Mara argues at the market",
        narrative_function: "confrontation",
      }],
      editorial_issues: adaptationIssues,
    },
  }),
  useBookPlan: () => ({
    data: {
      rhythm_summary: "A slow-burn rhythm",
      target_page_min: 1,
      target_page_max: 4,
      editorial_issues: planIssues,
    },
  }),
  useStageValidation: (_project: string | undefined, stage: string) => ({
    data: stage === "plan" ? planValidation : undefined,
  }),
  useCompletePages: () => completePagesUnavailable ? ({
    data: undefined,
    isLoading: false,
    error: new Error("Page plan is unavailable"),
    refetch: vi.fn(),
  }) : ({
    data: {
      pages: [{
        page: {
          page_number: 1,
          revision: 2,
          content_sha256: "a".repeat(64),
          page_turn_role: "reveal",
          spread_role: "right",
          emphasis: "peak",
          density_intent: "standard",
          rhythm_intent: "Hold, then reveal",
          layout_intent: "One dominant reveal",
          content: [],
          reading_order: [],
        },
        active_render: {
          render: { page_number: 1, revision: 2, parent_revision: 1 },
        },
        issues: pageIssues ?? [{
          id: "page-issue-1",
          issue_type: "identity",
          classification: "editorial_issue",
          correction_kind: "render_fidelity",
          correction_owner: "draw",
          page_number: 1,
          render_revision: 1,
          evidence: ["Face differs from approved reference"],
          requested_correction: "Restore the approved face",
          status: "open",
          resolution_revision: null,
        }],
        failure: persistedRenderedFailure,
      }, ...(includeUndrawnPage ? [{
        page: {
          page_number: 2,
          revision: 1,
          content_sha256: "b".repeat(64),
          page_turn_role: "release",
          spread_role: "single",
          emphasis: "release",
          density_intent: "sparse",
          rhythm_intent: "Breathe",
          layout_intent: "Quiet closing page",
          content: [],
          reading_order: [],
        },
        active_render: null,
        issues: [],
        failure: persistedPageFailure,
      }] : [])],
      issue_summary: {
        unresolved_issue_ids: ["page-issue-1"],
        blocking_issue_ids: [],
        accepted_editorial_issue_ids: [],
      },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  }),
  useGenerateCompletePage: () => ({ mutate: generatePage, isPending: false }),
  useAnalyzeCompletePage: () => ({ mutate: analyzePage, isPending: false }),
  useAcceptPageIssue: () => ({ mutate: vi.fn(), isPending: false }),
  useDismissPageIssue: () => ({ mutate: dismissIssue, isPending: false }),
  useApproveStage: () => ({ mutate: continueToBook, isPending: false }),
  useRunPipeline: () => ({ mutate: runPipeline, isPending: false }),
  useGenerationJobs: (project: string | undefined, ids: string[]) => {
    trackGenerationJobs(project, ids);
    return {
      data: {
        jobs: generationJobResults.filter((job) => ids.includes(job.id)),
      },
    };
  },
  useCreditBalance: () => ({ data: undefined }),
  useStageEstimate: () => ({ data: undefined }),
}));

vi.mock("../api/pageRevisions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/pageRevisions")>();
  return {
    ...actual,
    useCorrectionPreview: () => ({ mutate: previewCorrections, isPending: false, data: previewResult, error: null }),
    useSubmitCorrections: () => ({ mutate: submitCorrections, isPending: false, error: null, isSuccess: false }),
    useRenderCorrection: () => ({ data: null, isLoading: false, error: null }),
    useCachedVisualReview: () => ({
      data: {
        cached: true,
        page_number: 1,
        render_revision: 2,
        render_image_sha256: "0".repeat(64),
        report: null,
        finding_issues: [],
        references: [],
      },
      isLoading: false,
      error: null,
    }),
    useVisualReviewEstimate: () => ({ data: { estimate_credits: 2 } }),
    useReviewPageVisuals: () => ({ mutate: reviewVisuals, isPending: false, data: undefined, error: null }),
  };
});

import { PagesRoom } from "../pages/rooms/PagesRoom";

function renderRoom() {
  render(
    <MemoryRouter initialEntries={["/project/demo/pages"]}>
      <I18nProvider>
        <Routes>
          <Route path="/project/:id/pages" element={<PagesRoom />} />
        </Routes>
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("PagesRoom", () => {
  beforeEach(() => {
    window.localStorage.removeItem(SHOW_DEV_CONTENT_KEY);
    window.localStorage.clear();
    previewCorrections.mockReset();
    submitCorrections.mockReset();
    reviewVisuals.mockReset();
    dismissIssue.mockReset();
    previewResult = undefined;
    analyzePage.mockReset();
    continueToBook.mockReset();
    generatePage.mockReset();
    runPipeline.mockReset();
    trackGenerationJobs.mockClear();
    includeUndrawnPage = false;
    completePagesUnavailable = false;
    pageIssues = undefined;
    persistedPageFailure = null;
    persistedRenderedFailure = null;
    adaptationIssues = [{
      id: "adapt-issue-1",
      owner_stage: "adapt",
      code: "rushed_aftermath",
      message: "The aftermath is compressed.",
      evidence: ["Source units 80–92"],
    }];
    planIssues = [];
    planValidation = undefined;
    generationJobResults = [];
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "awaiting_review", stale: false },
    };
  });


  it("offers to retry Adapt when Adapt failed before Plan started", () => {
    stageStatuses = {
      adapt: { status: "failed", stale: false },
      plan: { status: "pending", stale: false },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(screen.getByRole("heading", { name: "Book Adaptation" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: false, retryFailed: undefined },
      expect.any(Object),
    );
  });

  it("offers to start Adapt when a recovered project is pending", () => {
    stageStatuses = {
      adapt: { status: "pending", stale: false },
      plan: { status: "pending", stale: false },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;

    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Start adaptation" }));
    expect(runPipeline).toHaveBeenCalledWith(
      {
        project: "demo",
        stage: "adapt",
        rerun: false,
        retryFailed: undefined,
      },
      expect.any(Object),
    );
  });

  it("offers to retry Adapt when a server restart left it stale", () => {
    stageStatuses = {
      adapt: { status: "running", stale: true },
      plan: { status: "pending", stale: false },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(screen.getByText("PRESS STOPPED")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: false, retryFailed: undefined },
      expect.any(Object),
    );
  });

  it("regenerates Adapt when Plan reports undersegmented upstream beats", () => {
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "failed", stale: false },
      draw: { status: "pending", stale: false },
    };
    planValidation = {
      invariant_failures: [{
        id: "plan_failure_upstream_adaptation_granularity",
        owner_stage: "adapt",
        code: "upstream_adaptation_granularity",
        message: "Adapt must split the story into enough visual beats.",
        evidence: ["Plan requires 32 beats; Adapt provides 19."],
      }],
      recommendations: [],
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(screen.getByRole("heading", { name: "Book Adaptation" })).toBeTruthy();
    expect(screen.getByText("Adapt must split the story into enough visual beats.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: true, retryFailed: undefined },
      expect.any(Object),
    );
  });

  it("restores persisted Adapt progress after a refresh", () => {
    stageStatuses = {
      adapt: {
        status: "running",
        stale: false,
        items_done: 1,
        items_total: 2,
      },
      plan: { status: "pending", stale: false },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(screen.getByText("1 / 2")).toBeTruthy();
  });

  it("shows the render canvas and revision history", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    expect(screen.getByAltText("Complete page 1, render revision 2")).toBeTruthy();
    expect(screen.getByText("COMPARE WITH PREVIOUS RENDER", { exact: false })).toBeTruthy();
    expect(screen.queryByText("page-issue-1")).toBeNull();
    expect(screen.queryByText("rushed_aftermath")).toBeNull();
  });

  it("opens page review as an accessible dialog and closes it with Escape", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(dialog).toBeTruthy();
    expect(dialog.className).toContain("z-[120]");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Page 1 review" })).toBeNull();
  });

  it("closes page review when the backdrop is clicked but not its content", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    fireEvent.click(screen.getByRole("tab", { name: "Page" }));
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBe(dialog);

    fireEvent.click(dialog);
    expect(screen.queryByRole("dialog", { name: "Page 1 review" })).toBeNull();
  });

  function stubPreviewResult(): Record<string, unknown> {
    return {
      selected_issue_ids: ["page-issue-1"],
      unselected_open_issue_ids: [],
      pending_manual_change_ids: [],
      changes: [],
      note: null,
      mode: "redraw",
      instruction: "compiled",
      context: {
        adaptation_revision: 1,
        adaptation_sha256: "0".repeat(64),
        treatment_spine: [],
        beat_ids: [],
        beat_count: 0,
        appearance_chronology: [],
        continuity: [],
        source_unit_ids: [],
        selected_source_unit_ids: [],
        omitted_source_unit_ids: [],
        context_digest: "d",
        truncated: false,
      },
      references: [],
      profile: { id: "p", provider: "v", model: "m" },
      lettering_count: 0,
      prompt_characters: 8,
      request_sha256: "r",
      warnings: [],
      estimate: {
        estimate_credits: 3,
        reserved_credits: 3,
        reservation_multiplier: 1,
        confidence: "high",
      },
    };
  }

  it("submits selected suggestions and manual requests as one correction after preview", () => {
    previewCorrections.mockImplementation((_variables, options) => {
      previewResult = stubPreviewResult();
      options?.onSuccess?.(previewResult);
    });
    submitCorrections.mockImplementation((_variables, options) => {
      options?.onSuccess?.({ status: "queued", job: { id: "job-correction-1" }, selected_issue_ids: ["page-issue-1"] });
    });
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    // Editing stays closed until requested: the artwork leads.
    expect(screen.queryByLabelText(/Manual request/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));

    // The open Draw suggestion arrives pre-selected in the draft.
    expect(screen.getByRole("checkbox", { name: /Restore the approved face/ })).toHaveProperty("checked", true);
    fireEvent.change(screen.getByLabelText(/Manual request/), {
      target: { value: "Keep the reveal, but restore the approved face." },
    });
    fireEvent.click(screen.getByRole("button", { name: "ADD MANUAL REQUEST" }));

    // Submission is blocked until an explicit preview runs.
    fireEvent.click(screen.getByRole("button", { name: "SUBMIT ONE CORRECTION" }));
    expect(submitCorrections).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "PREVIEW COST & CONTEXT" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "PREVIEW COST & CONTEXT" }));
    expect(previewCorrections).toHaveBeenCalledWith(
      expect.objectContaining({ project: "demo", pageNumber: 1 }),
      expect.any(Object),
    );
    const previewBody = previewCorrections.mock.calls[0][0].body;
    expect(previewBody.comic_page_revision).toBe(2);
    expect(previewBody.parent_render_revision).toBe(2);
    expect(previewBody.comic_page_sha256).toBe("a".repeat(64));
    expect(previewBody.changes.length).toBe(2);
    expect(previewBody.changes[0].issue_id).toBe("page-issue-1");
    expect(previewBody.changes[1].instruction).toContain("Keep the reveal");

    fireEvent.click(screen.getByRole("button", { name: "SUBMIT ONE CORRECTION" }));
    expect(submitCorrections).toHaveBeenCalledWith(
      expect.objectContaining({ project: "demo", pageNumber: 1 }),
      expect.any(Object),
    );
    expect(trackGenerationJobs).toHaveBeenLastCalledWith("demo", ["job-correction-1"]);
  });

  it("shows the reason when a correction cannot be queued", () => {
    previewCorrections.mockImplementation((_variables, options) => {
      previewResult = stubPreviewResult();
      options?.onSuccess?.(previewResult);
    });
    submitCorrections.mockImplementation((_variables, options) => {
      options?.onError?.(new Error("Saved edition conflict"));
    });
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));

    fireEvent.click(screen.getByRole("button", { name: "PREVIEW COST & CONTEXT" }));
    fireEvent.click(screen.getByRole("button", { name: "SUBMIT ONE CORRECTION" }));

    expect(screen.getByRole("alert").textContent).toContain("Saved edition conflict");
  });

  it("offers queue-all or one-by-one when Draw starts", () => {
    includeUndrawnPage = true;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "pending", stale: false },
    };
    renderRoom();

    expect(screen.getByText("How do you want to draw this edition?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "GO ONE BY ONE" }));
    expect(runPipeline).toHaveBeenLastCalledWith(
      { project: "demo", stage: "draw", queuePages: false },
      expect.any(Object),
    );

    fireEvent.click(screen.getByRole("button", { name: "QUEUE ALL PAGES" }));
    expect(runPipeline).toHaveBeenLastCalledWith(
      { project: "demo", stage: "draw", queuePages: true },
      expect.any(Object),
    );
    expect(screen.getByRole("img", {
      name: "Page 2: generation in progress",
    })).toBeTruthy();
  });

  it("explains OCR mismatches with full evidence and routes redraws through the draft", () => {
    pageIssues = [{
      id: "page-issue-draw-page-001-render-002-misspelled_lettering",
      issue_type: "misspelled_lettering",
      classification: "invariant_failure",
      correction_kind: "render_fidelity",
      correction_owner: "draw",
      page_number: 1,
      render_revision: 2,
      evidence: [
        'expected_text=["Open the door.", "Run!"]',
        'recognized_text=["Open the dor.", "Run!"]',
      ],
      requested_correction: "OCR lettering does not exactly match canonical wording.",
      status: "open",
      resolution_revision: null,
    }];
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.click(screen.getByRole("tab", { name: "Checks" }));

    expect(screen.getByText("Some lettering does not match")).toBeTruthy();
    expect(screen.getByText("Open the door. · Run!")).toBeTruthy();
    expect(screen.getByText("Open the dor. · Run!")).toBeTruthy();
    expect(screen.getByText("EXACT DIFFERENCES", { exact: false })).toBeTruthy();
    // No implicit per-issue redraw: fixes wait in the draft until previewed and submitted.
    expect(screen.queryByRole("button", { name: "CORRECT PAGE FINDINGS" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "DISMISS FALSE POSITIVE" }));
    expect(dismissIssue).toHaveBeenCalledWith({
      project: "demo",
      pageNumber: 1,
      issueId: "page-issue-draw-page-001-render-002-misspelled_lettering",
    });
    // Redraws route through the draft: on the Page tab the finding waits selected once editing is opened.
    fireEvent.click(screen.getByRole("tab", { name: "Page" }));
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));
    expect(screen.getByRole("checkbox", { name: /OCR lettering does not exactly match/ })).toHaveProperty("checked", true);
  });

  it("summarizes insertions, deletions and reorders across every differing segment", () => {
    pageIssues = [{
      id: "page-issue-draw-page-001-render-002-missing_lettering",
      issue_type: "missing_lettering",
      classification: "invariant_failure",
      correction_kind: "render_fidelity",
      correction_owner: "draw",
      page_number: 1,
      render_revision: 2,
      evidence: [
        'expected_text=["First.", "Second.", "Third."]',
        'recognized_text=["Third.", "First.", "Extra!"]',
      ],
      requested_correction: "OCR lettering does not exactly match canonical wording.",
      status: "open",
      resolution_revision: null,
    }];
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.click(screen.getByRole("tab", { name: "Checks" }));

    expect(screen.getByText("EXACT DIFFERENCES · 3")).toBeTruthy();
    expect(screen.getByText(/Moved:/)).toBeTruthy();
    expect(screen.getByText(/Missing:/)).toBeTruthy();
    expect(screen.getByText(/Extra:/)).toBeTruthy();
  });

  it("generates one complete page from an undrawn page card", () => {
    includeUndrawnPage = true;
    generatePage.mockImplementation((_variables, options) => {
      options?.onSuccess?.({ job: { id: "job-page-2" } });
    });
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "GENERATE COMPLETE PAGE" }));
    expect(generatePage).toHaveBeenCalledWith(
      { project: "demo", pageNumber: 2 },
      expect.any(Object),
    );
    expect(trackGenerationJobs).toHaveBeenLastCalledWith("demo", ["job-page-2"]);
    expect(screen.getByRole("button", { name: "DRAWING PAGE…" })).toHaveProperty("disabled", true);
  });

  it("explains when the image provider blocks a complete page", async () => {
    includeUndrawnPage = true;
    generationJobResults = [{
      id: "job-page-16",
      status: "failed",
      classification: "provider_blocked",
      user_message: "The image provider declined this scene but did not say which detail caused it. Your work is unchanged.",
      recoverable: true,
      error: "raw LiteLLM gateway error",
    }];
    generatePage.mockImplementation((_variables, options) => {
      options?.onSuccess?.({ job: { id: "job-page-16" } });
    });
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "GENERATE COMPLETE PAGE" }));

    expect(await screen.findByText("WE COULDN'T DRAW THIS PAGE")).toBeTruthy();
    expect(screen.getByText(
      "The image provider declined this scene but did not say which detail caused it. Your page plan is unchanged.",
    )).toBeTruthy();
    expect(screen.getByText(
      "Draw without references keeps the page plan and exact lettering, but character and setting details may vary. You can review the result before continuing.",
    )).toBeTruthy();
    expect(screen.queryByText("raw LiteLLM gateway error")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "DRAW WITHOUT REFERENCES" }));
    expect(generatePage).toHaveBeenLastCalledWith(
      { project: "demo", pageNumber: 2, depiction: "less_graphic" },
      expect.any(Object),
    );
  });

  it("keeps a provider failure visible after the temporary job is gone", () => {
    includeUndrawnPage = true;
    persistedPageFailure = {
      page_number: 2,
      request_sha256: "f".repeat(64),
      failed_at: "2026-07-30T16:00:00Z",
      phase: "generation",
      classification: "provider_blocked",
      recoverable: true,
      user_message: "The image provider declined this scene.",
      error: "finish_reason=SAFETY",
    };

    renderRoom();

    expect(screen.getByText("WE COULDN'T DRAW THIS PAGE")).toBeTruthy();
    expect(screen.getByRole("button", { name: "DRAW WITHOUT REFERENCES" })).toBeTruthy();
  });

  it("lets the author retry a recoverable image-service failure", () => {
    includeUndrawnPage = true;
    persistedPageFailure = {
      page_number: 2,
      request_sha256: "f".repeat(64),
      failed_at: "2026-07-30T16:00:00Z",
      phase: "generation",
      classification: "service_unavailable",
      recoverable: true,
      user_message: "We could not reach the image service.",
      error: "gateway connection could not be established",
    };

    renderRoom();

    const retry = screen.getByRole("button", { name: "TRY AGAIN" });
    expect(retry).toBeTruthy();
    fireEvent.click(retry);
    expect(generatePage).toHaveBeenCalledWith(
      { project: "demo", pageNumber: 2 },
      expect.any(Object),
    );
  });

  it("retries a failed text check without redrawing the page", () => {
    persistedRenderedFailure = {
      page_number: 1,
      request_sha256: "f".repeat(64),
      failed_at: "2026-07-30T16:00:00Z",
      phase: "analysis",
      classification: "analysis_error",
      recoverable: true,
      user_message: "The page is already drawn, but its text check failed.",
      error: "invalid OCR response shape",
    };

    renderRoom();

    expect(screen.getByText("TEXT CHECK INCOMPLETE")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "RETRY TEXT CHECK" }));
    expect(analyzePage).toHaveBeenCalledWith({
      project: "demo",
      pageNumber: 1,
    });
  });

  it("continues to Book through the Draw checkpoint", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "CONTINUE TO BOOK" }));
    expect(continueToBook).toHaveBeenCalledWith(
      { project: "demo", stage: "draw" },
      expect.any(Object),
    );
  });

  it("opens gallery-first with the page image immediately visible", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    const reviseTab = screen.getByRole("tab", { name: "Page" });
    expect(reviseTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Visual review" }).getAttribute("aria-selected")).toBe("false");
    expect(screen.getByRole("tab", { name: "Checks" }).getAttribute("aria-selected")).toBe("false");
    // Artwork and the opt-in editing entry render in the first viewport, not behind reading overlays.
    expect(screen.getByAltText("Complete page 1, render revision 2")).toBeTruthy();
    expect(screen.getByRole("button", { name: "MAKE CHANGES" })).toBeTruthy();
    // Editing stays closed until requested.
    expect(screen.queryByLabelText(/Manual request/)).toBeNull();
    // Visual and checks views stay out of the default viewport.
    expect(screen.queryByText("VISUAL REVIEW")).toBeNull();
    expect(screen.queryByText("ISSUE HISTORY")).toBeNull();
  });

  it("switches between visual and checks views and keeps the draft mounted", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));
    fireEvent.change(screen.getByLabelText(/Manual request/), {
      target: { value: "Keep the reveal, but restore the approved face." },
    });

    fireEvent.click(screen.getByRole("tab", { name: "Visual review" }));
    expect(screen.getByRole("tab", { name: "Visual review" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("VISUAL REVIEW")).toBeTruthy();
    expect(screen.queryByText("ISSUE HISTORY")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Checks" }));
    expect(screen.getByText("ISSUE HISTORY")).toBeTruthy();

    // Unsaved draft state survives tab switches: the draft stays mounted hidden.
    fireEvent.click(screen.getByRole("tab", { name: "Page" }));
    expect(screen.getByLabelText(/Manual request/)).toHaveProperty(
      "value",
      "Keep the reveal, but restore the approved face.",
    );
  });

  it("never shows blanket Confirmed while revised visual concerns remain", () => {
    pageIssues = [
      {
        id: "page-issue-draw-page-001-render-002-misspelled_lettering",
        issue_type: "misspelled_lettering",
        classification: "invariant_failure",
        correction_kind: "render_fidelity",
        correction_owner: "draw",
        page_number: 1,
        render_revision: 2,
        evidence: [
          'expected_text=["Open the door."]',
          'recognized_text=["Open the door."]',
        ],
        requested_correction: "OCR lettering does not exactly match canonical wording.",
        status: "resolved",
        resolution_revision: 2,
      },
      ...[1, 2, 3, 4].map((index) => ({
        id: `page-issue-visual-${index}`,
        issue_type: "identity",
        classification: "editorial_issue",
        correction_kind: "render_fidelity",
        correction_owner: "draw",
        page_number: 1,
        render_revision: 1,
        evidence: [`Face differs from approved reference ${index}`],
        requested_correction: "Restore the approved face",
        status: "revised",
        resolution_revision: null,
      })),
    ];
    renderRoom();

    const card = screen.getByRole("button", { name: "Open page 1, revision 2" });
    expect(card.textContent).toContain("Needs visual review");
    expect(card.textContent).not.toContain("Confirmed");
  });

  it("does not infer page acceptance from resolved findings", () => {
    pageIssues = [{
      id: "page-issue-1",
      issue_type: "identity",
      classification: "editorial_issue",
      correction_kind: "render_fidelity",
      correction_owner: "draw",
      page_number: 1,
      render_revision: 1,
      evidence: ["Face differs from approved reference"],
      requested_correction: "Restore the approved face",
      status: "resolved",
      resolution_revision: 2,
    }];
    renderRoom();

    const card = screen.getByRole("button", { name: "Open page 1, revision 2" });
    expect(card.textContent).not.toContain("Confirmed");
    expect(card.textContent).not.toContain("Needs visual review");
  });

  it("opens the book adaptation reading drawer from the gallery heading", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "BOOK ADAPTATION" }));

    const drawer = screen.getByRole("dialog", { name: "BOOK ADAPTATION" });
    expect(drawer).toBeTruthy();
    expect(screen.getByText("Narrative treatment")).toBeTruthy();
    expect(screen.getByText("A quarrel seeds the voyage")).toBeTruthy();
    expect(screen.getByText("Adapted beats")).toBeTruthy();
    expect(screen.getByText("Mara argues at the market")).toBeTruthy();
    // No storyboard editing or omission UI lives in the gallery.
    expect(screen.queryByText("EDITORIAL FINDINGS")).toBeNull();
    expect(screen.queryByText("SAVED CHANGES")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Close reading panel" }));
    expect(screen.queryByRole("dialog", { name: "BOOK ADAPTATION" })).toBeNull();
  });

  it("opens the page plan reading drawer from the gallery heading", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "PAGE PLAN" }));

    const drawer = screen.getByRole("dialog", { name: "PAGE PLAN" });
    expect(drawer).toBeTruthy();
    expect(screen.getByText("Book rhythm")).toBeTruthy();
    expect(screen.getByText("A slow-burn rhythm")).toBeTruthy();
    expect(screen.getByText("Planned pages")).toBeTruthy();
    expect(screen.getByText("One dominant reveal")).toBeTruthy();
    expect(screen.getByText("Hold, then reveal")).toBeTruthy();
  });

  it("opens the reading drawer from a deep link", () => {
    render(
      <MemoryRouter initialEntries={["/project/demo/pages?reading=page-plan"]}>
        <I18nProvider>
          <Routes>
            <Route path="/project/:id/pages" element={<PagesRoom />} />
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("dialog", { name: "PAGE PLAN" })).toBeTruthy();
  });
});
