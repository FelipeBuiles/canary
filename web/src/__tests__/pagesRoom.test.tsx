import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n";
import { SHOW_DEV_CONTENT_KEY } from "../lib/devContent";
import { usePipelineStore } from "../store/pipeline";
import type * as PagesApi from "../api/pages";
import type { CostEstimate, EditorialIssue, StageStatus } from "../types/api";

const previewCorrections = vi.fn();
const submitCorrections = vi.fn();
const reviewVisuals = vi.fn();
const dismissIssue = vi.fn();
const analyzePage = vi.fn();
const continueToBook = vi.fn();
const generatePage = vi.fn();
const runPipeline = vi.fn();
const recoverChecks = vi.fn();
const estimateChecks = vi.fn();
const finishChecks = vi.fn();
let analysisChecked = true;
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
  payload?: { page_number: number };
}> = [];
let previewResult: Record<string, unknown> | undefined;
let estimateError: Error | null = null;
const retryEstimate = vi.fn();
const cost: CostEstimate = { estimate_credits: 7, reserved_credits: 10, reservation_multiplier: 1.4, confidence: "variable" };

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({
    data: {
      stages: stageStatuses,
      style_selected: true,
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
        analysis_recovery: { status: analysisChecked ? "checked" : "requires_ocr", requires_paid_call: !analysisChecked },
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
        analysis_recovery: { status: "undrawn", requires_paid_call: false },
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
  useGenerationJobs: () => ({
    data: { jobs: generationJobResults.map((job) => ({
      kind: "complete_page_draw",
      payload: { page_number: 2 },
      queued_at: "2026-09-07T12:00:00Z",
      ...job,
    })) },
  }),
  useCreditBalance: () => ({ data: { balance_credits: 100 } }),
  useCreditPackages: () => ({ data: { packages: [] }, isLoading: false }),
  useStyles: () => ({ data: undefined }),
  useStageEstimate: () => ({ data: cost, error: estimateError, refetch: retryEstimate }),
  useCompletePageBatchEstimate: () => ({ data: cost, error: estimateError, refetch: retryEstimate }),
  useCompletePageEstimate: () => ({ data: estimateError ? undefined : cost, error: estimateError, refetch: retryEstimate }),
  usePageAnalysisEstimate: () => ({ data: cost, error: estimateError, refetch: retryEstimate }),
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
    useVisualReviewEstimate: () => ({ data: cost }),
    useReviewPageVisuals: () => ({ mutate: reviewVisuals, isPending: false, data: undefined, error: null }),
  };
});

vi.mock("../api/pages", async (importOriginal) => ({
  ...await importOriginal<typeof PagesApi>(),
  recoverPageChecks: (...args: unknown[]) => recoverChecks(...args),
  getPageCheckEstimate: (...args: unknown[]) => estimateChecks(...args),
  runFinishPreflight: (...args: unknown[]) => finishChecks(...args),
}));

import { PagesRoom } from "../pages/rooms/PagesRoom";

function renderRoom(url = "/project/demo/pages") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[url]}>
      <I18nProvider>
        <Routes>
          <Route path="/project/:id/pages" element={<PagesRoom />} />
        </Routes>
      </I18nProvider>
    </MemoryRouter></QueryClientProvider>,
  );
}

describe("PagesRoom", () => {
  beforeEach(() => {
    usePipelineStore.setState({ connect: vi.fn(), events: [] });
    window.localStorage.removeItem(SHOW_DEV_CONTENT_KEY);
    window.localStorage.clear();
    window.sessionStorage.clear();
    estimateError = null;
    retryEstimate.mockReset();
    previewCorrections.mockReset();
    submitCorrections.mockReset();
    reviewVisuals.mockReset();
    dismissIssue.mockReset();
    previewResult = undefined;
    analyzePage.mockReset();
    continueToBook.mockReset();
    generatePage.mockReset();
    runPipeline.mockReset();
    runPipeline.mockImplementation((_variables, options) => options?.onSuccess?.());
    includeUndrawnPage = false;
    completePagesUnavailable = false;
    pageIssues = undefined;
    persistedPageFailure = null;
    persistedRenderedFailure = null;
    analysisChecked = true;
    recoverChecks.mockReset();
    estimateChecks.mockReset();
    finishChecks.mockReset().mockResolvedValue({ status: "done" });
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

  afterEach(() => {
    usePipelineStore.setState(usePipelineStore.getInitialState());
  });


  it("offers to retry Adapt when Adapt failed before Plan started", () => {
    stageStatuses = {
      adapt: { status: "failed", stale: false },
      plan: { status: "pending", stale: false },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Retry stage" }));
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

    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Start this step" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Start this step" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Retry stage" }));
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

    expect(screen.getByText("Adapt must split the story into enough visual beats.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restart this step" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByText(/clear all downstream work/i)).toBeTruthy();
    expect(within(confirmation).getByText("PLAN")).toBeTruthy();
    expect(within(confirmation).getByText("DRAW")).toBeTruthy();
    expect(within(confirmation).getByText("FINISH")).toBeTruthy();
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Restart this step" }));
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

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Page 1 review" })).toBeNull();
  });

  it("closes page review when the backdrop is clicked but not its content", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    fireEvent.click(screen.getByRole("button", { name: "Page" }));
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
    expect(screen.getByRole("checkbox", { name: /Restore the approved face/ })).toHaveProperty("checked", true);
    expect(previewCorrections).toHaveBeenCalledOnce();
    expect(submitCorrections).toHaveBeenCalledOnce();
  });

  it("offers queue-all or one-by-one when Draw starts", () => {
    includeUndrawnPage = true;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "pending", stale: false },
    };
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "GO ONE BY ONE" }));
    expect(runPipeline).toHaveBeenLastCalledWith(
      { project: "demo", stage: "draw", queuePages: false },
      expect.any(Object),
    );

    fireEvent.click(screen.getByRole("button", { name: "QUEUE ALL PAGES" }));
    expect(runPipeline).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM QUEUE" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Checks" }));

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
    }, expect.any(Object));
    // Redraws route through the draft: on the Page tab the finding waits selected once editing is opened.
    fireEvent.click(screen.getByRole("button", { name: "Page" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Checks" }));

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
    expect(generatePage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
    expect(generatePage).toHaveBeenCalledWith(
      { project: "demo", pageNumber: 2 },
      expect.any(Object),
    );
    expect(screen.getByRole("button", { name: "DRAWING PAGE…" })).toHaveProperty("disabled", true);
  });

  it("explains when the image provider blocks a complete page", () => {
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

    expect(screen.queryByText("raw LiteLLM gateway error")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "DRAW LESS GRAPHIC VERSION" }));
    expect(generatePage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
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
    fireEvent.click(screen.getByRole("button", { name: "DRAW LESS GRAPHIC VERSION" }));
    expect(generatePage).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
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
    expect(generatePage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
    expect(generatePage).toHaveBeenCalledWith(
      { project: "demo", pageNumber: 2 },
      expect.any(Object),
    );
  });

  it("retries a failed text check without redrawing the page", () => {
    analysisChecked = false;
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

    fireEvent.click(screen.getByRole("button", { name: "RETRY TEXT CHECK" }));
    expect(analyzePage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM TEXT CHECK" }));
    expect(analyzePage).toHaveBeenCalledWith({
      project: "demo",
      pageNumber: 1,
    }, expect.any(Object));
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("recovers missing evidence before seeking explicit OCR-only consent on Continue", async () => {
    analysisChecked = false;
    pageIssues = [];
    const imageHash = "c".repeat(64);
    recoverChecks.mockResolvedValueOnce({ pages: [{ page_number: 1, status: "requires_ocr" }] })
      .mockImplementationOnce(async () => {
        analysisChecked = true;
        return { pages: [{ page_number: 1, status: "checked" }] };
      });
    estimateChecks.mockResolvedValue({ ...cost, paid_pages: 1, pages: [{
      page_number: 1, status: "requires_ocr", requires_paid_call: true, render_image_sha256: imageHash,
    }] });
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "CONTINUE TO BOOK" }));
    await screen.findByRole("alertdialog");
    expect(recoverChecks).toHaveBeenCalledOnce();
    expect(recoverChecks).toHaveBeenCalledWith("demo", false, {});
    expect(continueToBook).not.toHaveBeenCalled();
    expect(generatePage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM TEXT CHECK" }));
    await waitFor(() => expect(recoverChecks).toHaveBeenLastCalledWith("demo", true, { 1: imageHash }));
    await waitFor(() => expect(finishChecks).toHaveBeenCalledTimes(2));
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("does not let a historical generation failure mask recoverable evidence or recovered analysis", () => {
    analysisChecked = false;
    persistedRenderedFailure = {
      phase: "analysis", classification: "analysis_error", recoverable: true,
      user_message: "Artwork saved", error: "OCR envelope invalid",
    };
    generationJobResults = [{
      id: "old-image-job", status: "failed", classification: "generation_error",
      recoverable: true, error: "Old generic failure", payload: { page_number: 1 },
    }];
    const room = renderRoom();
    expect(screen.getByRole("button", { name: "RETRY TEXT CHECK" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "TRY AGAIN" })).toBeNull();
    room.unmount();
    analysisChecked = true;
    renderRoom();
    expect(screen.queryByRole("button", { name: "RETRY TEXT CHECK" })).toBeNull();
    expect(screen.queryByText("Old generic failure")).toBeNull();
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

    const reviseTab = screen.getByRole("button", { name: "Page" });
    expect(reviseTab.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Visual review" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: "Checks" }).getAttribute("aria-pressed")).toBe("false");
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

    fireEvent.click(screen.getByRole("button", { name: "Visual review" }));
    expect(screen.getByRole("button", { name: "Visual review" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("VISUAL REVIEW")).toBeTruthy();
    expect(screen.queryByText("ISSUE HISTORY")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Checks" }));
    expect(screen.getByText("ISSUE HISTORY")).toBeTruthy();

    // Unsaved draft state survives tab switches: the draft stays mounted hidden.
    fireEvent.click(screen.getByRole("button", { name: "Page" }));
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

  it("opens a Book finding on the requested page and review view", () => {
    includeUndrawnPage = true;
    renderRoom("/project/demo/pages?page=1&review=checks&filter=needs-review");
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByRole("button", { name: "Checks" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(within(dialog).getByRole("button", { name: "NEXT PAGE" }));
    expect(screen.getByRole("dialog", { name: "Page 2 review" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "NEXT UNRESOLVED" }));
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close page review" }));
    expect(screen.queryByRole("button", { name: "Open page 2, revision 0" })).toBeNull();
    expect(screen.getByRole("button", { name: "Needs review (1)" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("restores review context in this session but lets explicit links win", () => {
    window.sessionStorage.setItem("page-review:v2:signed-out:demo", "page=1&review=checks&filter=needs-review");
    const first = renderRoom();
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Checks" }).getAttribute("aria-pressed")).toBe("true");
    first.unmount();
    renderRoom("/project/demo/pages?page=1&review=visual&filter=all");
    expect(screen.getByRole("button", { name: "Visual review" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("ignores invalid review URL values without choosing an arbitrary page", () => {
    renderRoom("/project/demo/pages?page=-3&review=unknown&filter=unknown");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "All (1)" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    expect(screen.getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("restores server-side drawing jobs and keeps completed artwork inspectable", () => {
    includeUndrawnPage = true;
    generationJobResults = [{ id: "resumed-job", status: "running" }];
    renderRoom("/project/demo/pages?filter=drawing");
    expect(screen.getByRole("button", { name: "Drawing (1)" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("img", { name: "Page 2: generation in progress" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Inspect completed page 1" }));
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBeTruthy();
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("blocks paid drawing when the estimate fails and preserves the gallery context", () => {
    includeUndrawnPage = true;
    estimateError = new Error("Estimate unavailable");
    renderRoom("/project/demo/pages?filter=all");
    fireEvent.click(screen.getByRole("button", { name: "GENERATE COMPLETE PAGE" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("alert").textContent).toContain("Estimate unavailable");
    fireEvent.click(within(dialog).getByRole("button", { name: "RETRY ESTIMATE" }));
    expect(retryEstimate).toHaveBeenCalledOnce();
    expect(generatePage).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getAllByRole("button", { name: /Cancel/i })[0]);
    expect(screen.getByRole("button", { name: "Open page 2, revision 0" })).toBeTruthy();
  });

  it("keeps a submission error next to consent without automatically retrying", () => {
    includeUndrawnPage = true;
    generatePage.mockImplementation((_variables, options) => options.onError(new Error("Connection interrupted")));
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "GENERATE COMPLETE PAGE" }));
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
    expect(within(screen.getByRole("alertdialog")).getByRole("alert").textContent).toContain("Connection interrupted");
    expect(generatePage).toHaveBeenCalledOnce();
    fireEvent.click(within(screen.getByRole("alertdialog")).getAllByRole("button", { name: /Cancel/i })[0]);
    expect(screen.getByRole("alert").textContent).toContain("Connection interrupted");
    expect(screen.getByRole("button", { name: "Open page 2, revision 0" })).toBeTruthy();
  });
});
