import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
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
const cancelQueuedPages = vi.fn();
const recoverChecks = vi.fn();
const estimateChecks = vi.fn();
const finishChecks = vi.fn();
let analysisChecked = true;
let briefApproved = true;
type TestStageInfo = {
  status: StageStatus;
  stale: boolean;
  error?: string;
  items_done?: number;
  items_total?: number;
};
let stageStatuses: Record<"adapt" | "plan" | "draw", TestStageInfo> = {
  adapt: { status: "complete", stale: false },
  plan: { status: "complete", stale: false },
  draw: { status: "awaiting_review", stale: false },
};
let includeUndrawnPage = false;
let includeThirdUndrawnPage = false;
let completePagesUnavailable = false;
let placementReviewNeeded = false;
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
  is_current_page?: boolean;
  status: "queued" | "running" | "complete" | "failed" | "cancelled";
  classification?: string;
  user_message?: string;
  recoverable?: boolean;
  error?: string | null;
  payload?: { page_number: number };
}> = [];
let generationJobsLoading = false;
let projectRunning = false;
let stageEstimateFetching = false;
let previewResult: Record<string, unknown> | undefined;
let estimateError: Error | null = null;
const retryEstimate = vi.fn();
const cost: CostEstimate = { estimate_credits: 7, reserved_credits: 10, reservation_multiplier: 1.4, confidence: "variable" };

vi.mock("../api/queries", () => ({
  useCompletePage: () => ({ data: undefined }),
  usePageSource: () => ({
    data: {
      page_number: 1, page_revision: 2, geometry_render_revision: null,
      panels: [{ id: "panel-1", order: 1, panel_role: "standard", box: null }],
      passages: [{ scene_title: "The market", units: [{ id: "source-1", ordinal: 1, segments: [
        { text: "Mara argued at the market.", kind: "depicted", content_ids: ["panel-1"] },
      ] }] }],
    },
    error: null,
    isLoading: false,
  }),
  useProjectStatus: () => ({
    data: {
      stages: { ...stageStatuses, brief: { status: briefApproved ? "complete" : "awaiting_review", approved: briefApproved } },
      style_selected: true,
      is_running: projectRunning,
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
      pages: [{ page_number: 1, revision: 2, content_sha256: "a".repeat(64) }],
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
        lettering_placement_review_needed: placementReviewNeeded,
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
      }] : []), ...(includeThirdUndrawnPage ? [{
        page: {
          page_number: 3,
          revision: 1,
          content_sha256: "c".repeat(64),
          content: [],
          reading_order: [],
        },
        active_render: null,
        issues: [],
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
  useCancelQueuedPageJobs: () => ({ mutate: cancelQueuedPages, isPending: false, error: null }),
  useGenerationJobs: () => ({
    data: { jobs: generationJobResults.map((job) => ({
      kind: "complete_page_draw",
      payload: { page_number: 2 },
      queued_at: "2026-09-07T12:00:00Z",
      ...job,
    })) },
    isLoading: generationJobsLoading,
  }),
  useCreditBalance: () => ({ data: { balance_credits: 100 } }),
  useCreditPackages: () => ({ data: { packages: [] }, isLoading: false }),
  useStyles: () => ({ data: undefined }),
  useStageEstimate: () => ({ data: cost, error: estimateError, isFetching: stageEstimateFetching, refetch: retryEstimate }),
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

function LocationProbe() {
  return <output aria-label="Current route">{useLocation().search}</output>;
}

function renderRoom(url = "/project/demo/pages") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[url]}>
      <I18nProvider>
        <Routes>
          <Route path="/project/:id/pages" element={<><PagesRoom /><LocationProbe /></>} />
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
    cancelQueuedPages.mockReset();
    runPipeline.mockImplementation((_variables, options) => options?.onSuccess?.());
    includeUndrawnPage = false;
    includeThirdUndrawnPage = false;
    completePagesUnavailable = false;
    placementReviewNeeded = false;
    pageIssues = undefined;
    persistedPageFailure = null;
    persistedRenderedFailure = null;
    analysisChecked = true;
    briefApproved = true;
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
    generationJobsLoading = false;
    projectRunning = false;
    stageEstimateFetching = false;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "awaiting_review", stale: false },
    };
  });

  afterEach(() => {
    usePipelineStore.setState(usePipelineStore.getInitialState());
  });

  it("sends a revised brief back to Story instead of offering a rejected start", () => {
    briefApproved = false;
    stageStatuses.adapt = { status: "pending", stale: false };
    completePagesUnavailable = true;
    renderRoom();
    expect(screen.getByText("Approve your brief first")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start this step" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Review and approve brief" }));
    expect(runPipeline).not.toHaveBeenCalled();
  });

  it("offers an adaptation rerun after drawing has begun, with explicit impact and consent", () => {
    stageStatuses.draw = { status: "running", stale: true };
    renderRoom();
    expect(screen.getByRole("button", { name: /Start adaptation over/ }).closest("footer")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Start adaptation over/ }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText(/archived and replaced/)).toBeTruthy();
    expect(within(dialog).getByText(/Drawing waits for you/)).toBeTruthy();
    expect(within(dialog).getByText(/~7/)).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: /Start adaptation over/ }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: true, retryFailed: undefined }, expect.any(Object),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("keeps adaptation rerun available when the saved page plan cannot load", () => {
    completePagesUnavailable = true;
    renderRoom();
    expect((screen.getByRole("button", { name: /Start adaptation over/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it.each(["project", "page", "loading"])("disables adaptation rerun while %s work is active or unknown", (kind) => {
    projectRunning = kind === "project";
    generationJobsLoading = kind === "loading";
    if (kind === "page") generationJobResults = [{ id: "queued-page", status: "queued" }];
    renderRoom();
    expect((screen.getByRole("button", { name: /Start adaptation over/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it.each(["loading", "failed"])("blocks rerun confirmation when the estimate is %s", (state) => {
    stageEstimateFetching = state === "loading";
    if (state === "failed") estimateError = new Error("Offline");
    renderRoom();
    expect(screen.getByRole("button", { name: /Start adaptation over/ }).closest("footer")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Start adaptation over/ }));
    const dialog = screen.getByRole("alertdialog");
    expect((within(dialog).getByRole("button", { name: /Start adaptation over/ }) as HTMLButtonElement).disabled).toBe(true);
    if (state === "failed") {
      fireEvent.click(within(dialog).getByRole("button", { name: "Retry estimate" }));
      expect(retryEstimate).toHaveBeenCalledOnce();
    }
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Cancel" })[1]);
    expect(runPipeline).not.toHaveBeenCalled();
  });

  it("keeps a rejected rerun visible in the confirmation so it can be retried", () => {
    runPipeline.mockImplementation((_variables, options) => options?.onError?.(new Error("Wait for all project jobs to finish.")));
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: /Start adaptation over/ }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: /Start adaptation over/ }));
    expect(within(screen.getByRole("alertdialog")).getByRole("alert").textContent).toContain("Wait for all project jobs to finish.");
  });

  it("counts saved artwork against all planned pages even when the gallery is filtered", () => {
    includeUndrawnPage = true;
    renderRoom("/project/demo/pages?filter=needs-review");

    expect(screen.getByText("1 of 2 pages drawn")).toBeTruthy();
    const progress = screen.getByRole("progressbar", { name: "Drawing progress" });
    expect(progress.getAttribute("value")).toBe("1");
    expect(progress.getAttribute("max")).toBe("2");
    expect(screen.queryByRole("button", { name: "Open page 2, revision 0" })).toBeNull();
  });

  it("opens flagged pages directly in Checks without starting paid work", () => {
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "REVIEW FLAGGED PAGES (1)" }));

    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByRole("button", { name: "Text & findings" }).getAttribute("aria-pressed")).toBe("true");
    expect(generatePage).not.toHaveBeenCalled();
    expect(analyzePage).not.toHaveBeenCalled();
    expect(reviewVisuals).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close page review" }));
    expect(screen.getByRole("button", { name: "Needs review (1)" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("uses the artwork as the single review action and keeps revision detail in the dialog", () => {
    renderRoom();

    expect(screen.queryByRole("button", { name: "Review page 1" })).toBeNull();
    expect(screen.queryByText("Revision 2")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByText("Revision 2")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(dialog).getByAltText("Complete page 1, render revision 2")).toBeTruthy();
    expect(generatePage).not.toHaveBeenCalled();
    expect(runPipeline).not.toHaveBeenCalled();
    expect(analyzePage).not.toHaveBeenCalled();
  });

  it("offers Start reading when drawn pages have no unresolved findings", () => {
    pageIssues = [];
    renderRoom();
    expect(screen.queryByRole("button", { name: /REVIEW FLAGGED PAGES/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Start reading" }));

    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
    expect(generatePage).not.toHaveBeenCalled();
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
    fireEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Resume adaptation" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: false, retryFailed: undefined },
      expect.any(Object),
    );
  });

  it("offers a non-destructive Adapt resume when Plan is blocked by a stale review", () => {
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "failed", stale: false, error: "Narrative review is failed or stale. Rerun Adapt before drawing." },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;
    renderRoom();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Resume adaptation" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Resume adaptation" }));
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
    expect(screen.getByText("The story needs more visual moments to fill the planned pages.")).toBeTruthy();
    expect(screen.getByText("Check details").closest("details")?.open).toBe(false);
    expect(screen.queryByText("These contract failures block the book and cannot be accepted.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Start adaptation over" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(confirmation.textContent).toContain("archived and replaced");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Start adaptation over" }));
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

    expect(screen.getByText("Work in progress")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
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
    expect(screen.queryByLabelText(/What would you like to change/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));

    // The open Draw suggestion arrives pre-selected in the draft.
    expect(screen.getByRole("checkbox", { name: /Restore the approved face/ })).toHaveProperty("checked", true);
    fireEvent.change(screen.getByLabelText(/What would you like to change/), {
      target: { value: "Keep the reveal, but restore the approved face." },
    });
    expect(screen.getByRole("button", { name: "Review changes" })).toHaveProperty("disabled", false);
    expect(previewCorrections).not.toHaveBeenCalled();

    // Submission is blocked until an explicit preview runs.
    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(submitCorrections).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Review changes" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
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
    expect(previewBody.changes[1].instruction).toBe("Keep the reveal, but restore the approved face.");
    expect(screen.getByLabelText(/What would you like to change/)).toHaveProperty("value", "");
    expect(previewCorrections).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(submitCorrections).toHaveBeenCalledWith(
      expect.objectContaining({ project: "demo", pageNumber: 1 }),
      expect.any(Object),
    );
    expect(screen.getByText("Correction queued. The draft is locked.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Review changes" })).toBeNull();
    expect(screen.getByLabelText(/What would you like to change/)).toHaveProperty("disabled", true);
  });

  it("requires a new review after the requested wording changes", () => {
    previewCorrections.mockImplementation((_variables, options) => {
      previewResult = stubPreviewResult();
      options?.onSuccess?.(previewResult);
    });
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));

    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(screen.getByRole("button", { name: "Generate revision" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/What would you like to change/), {
      target: { value: "A request that has not been added yet" },
    });
    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(submitCorrections).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(previewCorrections.mock.calls[1][0].body.changes).toHaveLength(2);
    expect(previewCorrections.mock.calls[1][0].body.changes[1].instruction)
      .toBe("A request that has not been added yet");
    expect(screen.getByRole("button", { name: "Generate revision" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Edit request: Restore the approved face/ }));
    fireEvent.change(screen.getByDisplayValue("Restore the approved face"), {
      target: { value: "Restore the approved face and keep the lighting" },
    });

    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(submitCorrections).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    expect(previewCorrections).toHaveBeenCalledTimes(3);
    expect(previewCorrections.mock.calls[2][0].body.changes).toHaveLength(2);
    expect(previewCorrections.mock.calls[2][0].body.changes[0].instruction)
      .toBe("Restore the approved face and keep the lighting");
    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(submitCorrections.mock.calls[0][0].body)
      .toEqual(previewCorrections.mock.calls[2][0].body);
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

    fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate revision" }));

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

  it("restores one-confirmation retry for all incomplete pages after a server restart", () => {
    includeUndrawnPage = true;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "running", stale: true },
    };
    renderRoom();

    expect(screen.getByText("1 of 2 pages drawn")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "DRAW REMAINING PAGES" }));
    const confirmation = screen.getByRole("alertdialog", { name: "Retry the remaining pages?" });
    expect(within(confirmation).getByText(
      "Only pages without a saved render will be queued. Completed artwork stays available to review.",
    )).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();

    fireEvent.click(within(confirmation).getByRole("button", { name: "CONFIRM RETRY" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "draw", queuePages: true },
      expect.any(Object),
    );
    expect(screen.getByText("1 of 2 pages drawn")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Page 2: generation in progress" })).toBeTruthy();
  });

  it("waits for current page-job status before offering a batch retry", () => {
    includeUndrawnPage = true;
    generationJobsLoading = true;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "running", stale: true },
    };
    renderRoom();

    expect(screen.queryByRole("button", { name: "DRAW REMAINING PAGES" })).toBeNull();
  });

  it("offers to batch the remaining pages after choosing one-by-one", () => {
    includeUndrawnPage = true;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "running", stale: false },
    };
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "DRAW REMAINING PAGES" }));
    expect(screen.getByRole("alertdialog", { name: "Queue all undrawn pages?" })).toBeTruthy();
  });

  it("keeps the remaining-pages action visible during an individual draw and enables it afterward", () => {
    includeUndrawnPage = true;
    includeThirdUndrawnPage = true;
    stageStatuses.draw = { status: "running", stale: false };
    generationJobResults = [{ id: "single-page", status: "running", payload: { page_number: 2 } }];
    const room = renderRoom();

    const queue = screen.getByRole("button", { name: "DRAW REMAINING PAGES" }) as HTMLButtonElement;
    expect(queue.disabled).toBe(true);
    expect(screen.getByText("One page still needs artwork. Completed pages are saved. Queue it after reviewing the current estimate.")).toBeTruthy();
    expect(screen.getByText("Wait for the current page to finish before queuing the rest.")).toBeTruthy();

    generationJobResults = [];
    room.unmount();
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "DRAW REMAINING PAGES" }));
    expect(screen.getByRole("alertdialog", { name: "Queue all undrawn pages?" })).toBeTruthy();
  });

  it("offers to cancel only queued pages while another page is already running", () => {
    includeUndrawnPage = true;
    includeThirdUndrawnPage = true;
    stageStatuses.draw = { status: "running", stale: false };
    generationJobResults = [
      { id: "running-page", status: "running", payload: { page_number: 2 } },
      { id: "waiting-page", status: "queued", payload: { page_number: 3 } },
    ];
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "CANCEL QUEUED PAGES (1)" }));
    expect(cancelQueuedPages).toHaveBeenCalledWith("demo");
    expect(screen.getByRole("img", { name: "Page 2: generation in progress" })).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "Text & findings" }));

    expect(screen.getByText("Possible wording difference")).toBeTruthy();
    expect(screen.getByText("Open the door. · Run!")).toBeTruthy();
    expect(screen.getByText("Open the dor. · Run!")).toBeTruthy();
    expect(screen.getByText("POSSIBLE DIFFERENCES", { exact: false })).toBeTruthy();
    // No implicit per-issue redraw: fixes wait in the draft until previewed and submitted.
    expect(screen.queryByRole("button", { name: "CORRECT PAGE FINDINGS" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "TEXT LOOKS CORRECT" }));
    expect(dismissIssue).toHaveBeenCalledWith({
      project: "demo",
      pageNumber: 1,
      issueId: "page-issue-draw-page-001-render-002-misspelled_lettering",
    }, expect.any(Object));
    // Redraws route through the draft: on the Page tab the finding waits selected once editing is opened.
    fireEvent.click(screen.getByRole("button", { name: "Page" }));
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));
    expect(screen.getByRole("checkbox", { name: /OCR lettering does not exactly match/ })).toHaveProperty("checked", false);
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
    fireEvent.click(screen.getByRole("button", { name: "Text & findings" }));

    expect(screen.getByText("POSSIBLE DIFFERENCES · 3")).toBeTruthy();
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

    expect(screen.queryByRole("button", { name: "Open page 2, revision 0" })).toBeNull();
    const generate = screen.getByRole("button", { name: "GENERATE COMPLETE PAGE" });
    expect(generate.closest("article")?.children).toHaveLength(1);
    fireEvent.click(generate);
    expect(generatePage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
    expect(generatePage).toHaveBeenCalledWith(
      { project: "demo", pageNumber: 2 },
      expect.any(Object),
    );
    expect(screen.getByRole("img", { name: "Page 2: generation in progress" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "DRAWING PAGE…" })).toBeNull();
    expect(screen.queryByText("Not generated")).toBeNull();
  });

  it.each(["failed", "running"] as const)("ignores %s jobs from an earlier page plan", async (jobStatus) => {
    includeUndrawnPage = true;
    generationJobResults = [{
      id: "old-edition-job", status: jobStatus, is_current_page: false,
      classification: "generation_error", recoverable: true,
      error: "Server stopped before this job started.",
    }];
    renderRoom();
    // Let terminal-job reconciliation run as well as the initial page cards.
    await waitFor(() => expect(screen.getByRole("button", { name: "Failed (0)" })).toBeTruthy());
    expect(screen.queryByText("IMAGE GENERATION FAILED")).toBeNull();
    expect(screen.getByRole("button", { name: "Drawing (0)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "GENERATE COMPLETE PAGE" })).toBeTruthy();
    expect(generatePage).not.toHaveBeenCalled();
  });

  it.each(["running", "complete"] as const)("restores queued pages after refresh while the preceding page is %s", async (status) => {
    includeUndrawnPage = true;
    generationJobResults = [
      { id: "first", status, is_current_page: true, payload: { page_number: 1 } },
      { id: "waiting", status: "queued", is_current_page: true, payload: { page_number: 2 } },
    ];
    renderRoom();
    await waitFor(() => expect(screen.getByText(`${status === "running" ? 2 : 1} pages drawing or queued`)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /DRAW REMAINING PAGES/ })).toBeNull();
    expect(screen.getByRole("img", { name: "Page 2: generation in progress" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "DRAWING PAGE…" })).toBeNull();
    expect(screen.queryByText("IMAGE GENERATION FAILED")).toBeNull();
    expect(runPipeline).not.toHaveBeenCalled();
  });

  it.each(["provider_blocked", "generation_error", "empty_response"] as const)("offers less-graphic recovery for %s without automatic generation", (classification) => {
    includeUndrawnPage = true;
    generationJobResults = [{
      id: "job-page-16",
      status: "failed",
      classification,
      user_message: classification === "provider_blocked"
        ? "The image provider declined this scene but did not say which detail caused it. Your work is unchanged."
        : undefined,
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
    const failedCard = retry.closest("article")!;
    expect(within(failedCard).queryByText("READY TO DRAW")).toBeNull();
    expect(failedCard.children).toHaveLength(1);
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

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Text & findings" }));
    fireEvent.click(screen.getByRole("button", { name: "CHECK PAGE TEXT" }));
    expect(analyzePage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "CONFIRM TEXT CHECK" }));
    expect(analyzePage).toHaveBeenCalledWith({
      project: "demo",
      pageNumber: 1,
    }, expect.any(Object));
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("continues to Book with unchecked artwork without running or charging for OCR", () => {
    analysisChecked = false;
    pageIssues = [];
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "CONTINUE TO BOOK" }));
    expect(continueToBook).toHaveBeenCalledWith({ project: "demo", stage: "draw" }, expect.any(Object));
    expect(recoverChecks).not.toHaveBeenCalled();
    expect(estimateChecks).not.toHaveBeenCalled();
    expect(analyzePage).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
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
    expect(screen.queryByText("Artwork saved · Text not checked")).toBeNull();
    expect(screen.getByRole("button", { name: "Open page 1, revision 2" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "TRY AGAIN" })).toBeNull();
    room.unmount();
    analysisChecked = true;
    briefApproved = true;
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
    expect(screen.getByRole("button", { name: "Text & findings" }).getAttribute("aria-pressed")).toBe("false");
    // Artwork and the opt-in editing entry render in the first viewport, not behind reading overlays.
    expect(screen.getByAltText("Complete page 1, render revision 2")).toBeTruthy();
    expect(screen.getByRole("button", { name: "MAKE CHANGES" })).toBeTruthy();
    // Editing stays closed until requested.
    expect(screen.queryByLabelText(/What would you like to change/)).toBeNull();
    // Visual and checks views stay out of the default viewport.
    expect(screen.queryByText("VISUAL REVIEW")).toBeNull();
    expect(screen.queryByText("ISSUE HISTORY")).toBeNull();
  });

  it("shows the manuscript source for the open page in its own tab", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Source" }));

    expect(screen.getByRole("button", { name: "Source" }).getAttribute("aria-pressed")).toBe("true");
    const region = screen.getByRole("region", { name: "Source" });
    expect(within(region).getByText("Mara argued at the market.").tagName).toBe("MARK");
    expect(within(region).getByText("Panel outlines are not available for this artwork.")).toBeTruthy();
  });

  it("switches between visual and checks views and keeps the draft mounted", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));
    fireEvent.change(screen.getByLabelText(/What would you like to change/), {
      target: { value: "Keep the reveal, but restore the approved face." },
    });

    fireEvent.click(screen.getByRole("button", { name: "Back to page" }));
    expect(screen.queryByLabelText(/What would you like to change/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "MAKE CHANGES" }));
    expect(screen.getByLabelText(/What would you like to change/)).toHaveProperty(
      "value", "Keep the reveal, but restore the approved face.",
    );

    fireEvent.click(screen.getByRole("button", { name: "Visual review" }));
    expect(screen.getByRole("button", { name: "Visual review" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("VISUAL REVIEW")).toBeTruthy();
    expect(screen.queryByText("ISSUE HISTORY")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Text & findings" }));
    expect(screen.getByText("ISSUE HISTORY")).toBeTruthy();

    // Unsaved draft state survives tab switches: the draft stays mounted hidden.
    fireEvent.click(screen.getByRole("button", { name: "Page" }));
    expect(screen.getByLabelText(/What would you like to change/)).toHaveProperty(
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
    expect(screen.getByText("Needs visual review")).toBeTruthy();
    expect(card.textContent).not.toContain("Confirmed");
  });

  it("marks a clean page whose editable lettering still needs a placement check", () => {
    pageIssues = [];
    placementReviewNeeded = true;
    renderRoom();

    expect(screen.getByText("Needs placement")).toBeTruthy();
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

  it("opens book adaptation as a full reading workspace and returns to the gallery", () => {
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "BOOK ADAPTATION" }));

    expect(screen.getByRole("region", { name: "BOOK ADAPTATION" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open page 1, revision 2" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Narrative treatment" })).toBeTruthy();
    expect(screen.getByText("A quarrel seeds the voyage")).toBeTruthy();
    expect(screen.getByText("Mara argues at the market")).toBeTruthy();
    expect(screen.queryByText("EDITORIAL FINDINGS")).toBeNull();
    expect(screen.queryByText("SAVED CHANGES")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Back to pages" }));
    expect(screen.queryByRole("region", { name: "BOOK ADAPTATION" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open page 1, revision 2" })).toBeTruthy();
  });

  it("switches reading documents in the URL and preserves the gallery filter without generating", () => {
    renderRoom("/project/demo/pages?filter=needs-review");
    fireEvent.click(screen.getByRole("button", { name: "BOOK ADAPTATION" }));
    expect(screen.getByLabelText("Current route").textContent).toContain("reading=adaptation");
    fireEvent.click(screen.getByRole("button", { name: "PAGE PLAN" }));
    expect(screen.getByRole("region", { name: "PAGE PLAN" })).toBeTruthy();
    expect(screen.getByLabelText("Current route").textContent).toContain("reading=page-plan");
    expect(screen.getByText("A slow-burn rhythm")).toBeTruthy();
    expect(screen.getByText("One dominant reveal")).toBeTruthy();
    expect(screen.getByText("Hold, then reveal")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back to pages" }));
    expect(screen.getByLabelText("Current route").textContent).not.toContain("reading=");
    expect(screen.getByRole("button", { name: "Needs review (1)" }).getAttribute("aria-pressed")).toBe("true");
    expect(generatePage).not.toHaveBeenCalled();
    expect(runPipeline).not.toHaveBeenCalled();
    expect(submitCorrections).not.toHaveBeenCalled();
  });

  it("opens the full reading workspace from a deep link", () => {
    renderRoom("/project/demo/pages?reading=page-plan");
    expect(screen.getByRole("region", { name: "PAGE PLAN" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { name: "PAGE PLAN" })).toBe(document.activeElement);
  });

  it("opens a Book finding on the requested page and review view", () => {
    includeUndrawnPage = true;
    renderRoom("/project/demo/pages?page=1&review=checks&filter=needs-review");
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByRole("button", { name: "Text & findings" }).getAttribute("aria-pressed")).toBe("true");
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
    expect(screen.getByRole("button", { name: "Text & findings" }).getAttribute("aria-pressed")).toBe("true");
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
    expect(screen.getByRole("button", { name: "GENERATE COMPLETE PAGE" })).toBeTruthy();
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
    expect(screen.getByRole("button", { name: "GENERATE COMPLETE PAGE" })).toBeTruthy();
  });

  it("shows a persisted Draw batch failure when page plans are already available", () => {
    includeUndrawnPage = true;
    stageStatuses.draw = { status: "failed", stale: false, error: "Durable generation queue is unavailable" };
    renderRoom();
    expect(screen.getByRole("alert").textContent).toContain("Durable generation queue is unavailable");
    expect(screen.getByRole("button", { name: /DRAW REMAINING PAGES/ })).toBeTruthy();
  });
});
