import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n";
import { SHOW_DEV_CONTENT_KEY } from "../lib/devContent";
import { usePipelineStore } from "../store/pipeline";
import type * as PagesApi from "../api/pages";
import type { CostEstimate, EditorialIssue, StageStatus, StageValidation } from "../types/api";
import { ApiError } from "../api/client";

const productEvent = vi.fn();
vi.mock("../api/events", () => ({ trackProductEvent: (...args: unknown[]) => productEvent(...args) }));
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
  error_code?: string | null;
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
let letteringMode: "hybrid" | undefined;
let pageIssues: Array<Record<string, unknown>> | undefined;
let persistedPageFailure: Record<string, unknown> | null = null;
let persistedRenderedFailure: Record<string, unknown> | null = null;
let adaptationIssues: EditorialIssue[] = [];
let planIssues: EditorialIssue[] = [];
let adaptValidation: Pick<StageValidation, "invariant_failures" | "recommendations"> | undefined;
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

const fixtures = {
  pageSource: () => ({
    data: {
      page_number: 1, page_revision: 2, geometry: null, lettering: [],
      passages: [{ scene_title: "The market", units: [{ id: "source-1", ordinal: 1, segments: [
        { text: "Mara argued at the market.", kind: "depicted", lettering_item_ids: [] },
      ] }] }],
    },
    error: null,
    isLoading: false,
  }),
  status: () => ({
    data: {
      stages: { ...stageStatuses, brief: { status: briefApproved ? "complete" : "awaiting_review", approved: briefApproved } },
      style_selected: true,
      is_running: projectRunning,
    },
  }),
  adaptation: () => ({
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
  plan: () => ({
    data: {
      pages: [{ page_number: 1, revision: 2, content_sha256: "a".repeat(64) }],
      rhythm_summary: "A slow-burn rhythm",
      target_page_min: 1,
      target_page_max: 4,
      editorial_issues: planIssues,
    },
  }),
  validation: (_project: string | undefined, stage: string) => ({
    data: stage === "plan" ? planValidation : adaptValidation,
  }),
  pages: () => completePagesUnavailable ? ({
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
        ...(letteringMode ? { lettering_mode: letteringMode } : {}),
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
  jobs: () => ({
    data: { jobs: generationJobResults.map((job) => ({
      kind: "complete_page_draw",
      payload: { page_number: 2 },
      queued_at: "2026-09-07T12:00:00Z",
      ...job,
    })) },
    isLoading: generationJobsLoading,
  }),

};

vi.mock("../api/client", async importOriginal => ({
  ...await importOriginal<typeof import("../api/client")>(),
  apiFetch: (path: string, options?: RequestInit) => fetchFixture(path, options),
}));

function callbackResponse(spy: ReturnType<typeof vi.fn<(...args: unknown[]) => unknown>>, variables: unknown, fallback: unknown = {}) {
  return new Promise((resolve, reject) => {
    if (spy.getMockImplementation()) spy(variables, { onSuccess: resolve, onError: reject });
    else { spy(variables, { onSuccess: resolve, onError: reject }); resolve(fallback); }
  });
}

async function fetchFixture(path: string, options?: RequestInit): Promise<unknown> {
  const url = new URL(path, "http://localhost");
  const tail = url.pathname.replace("/projects/demo", "");
  const pageNumber = Number(tail.match(/^\/pages\/(\d+)/)?.[1] ?? 1);
  const variables = { project: "demo", pageNumber };
  if (options?.method === "POST") {
    const body = options.body ? JSON.parse(String(options.body)) : undefined;
    if (tail === "/run") {
      const params = Object.fromEntries(url.searchParams);
      return callbackResponse(runPipeline, { project: "demo", ...(params.stage ? { stage: params.stage } : {}),
        ...(params.stage !== "draw" ? { rerun: params.rerun === "1", retryFailed: undefined } : { queuePages: params.queue_pages === "1" }),
        ...(params.rerun === "1" ? { rerun: true } : {}), ...(params.retry_failed === "1" ? { retryFailed: true } : {}),
        ...(params.queue_pages === "1" ? { queuePages: true } : {}),
        ...(params.confirmed_archive_pages ? { confirmedArchivePages: Number(params.confirmed_archive_pages) } : {}),
      });
    }
    if (tail.startsWith("/approve/")) return callbackResponse(continueToBook, { project: "demo", stage: tail.split("/").at(-1) });
    if (tail === "/jobs/cancel-queued-pages") { cancelQueuedPages("demo"); return { cancelled_job_ids: [] }; }
    if (tail.endsWith("/corrections/preview")) return callbackResponse(previewCorrections, { ...variables, body });
    if (tail.endsWith("/corrections")) return callbackResponse(submitCorrections, { ...variables, body }, { job: { id: "correction", kind: "complete_page_draw", status: "queued", payload: { page_number: pageNumber }, queued_at: "2026-09-07T12:00:00Z" } });
    if (tail.endsWith("/visual-review")) return callbackResponse(reviewVisuals, variables);
    if (tail.endsWith("/generate")) return callbackResponse(generatePage, { ...variables, ...(body?.depiction === "less_graphic" ? { depiction: "less_graphic" } : {}) }, { job: { id: "admitted", kind: "complete_page_draw", status: "queued", payload: { page_number: pageNumber }, queued_at: "2026-09-07T12:00:00Z" } });
    if (tail.endsWith("/analyze")) return callbackResponse(analyzePage, variables);
    if (tail.endsWith("/dismiss")) return callbackResponse(dismissIssue, { ...variables, issueId: tail.split("/").at(-2) });
    return {};
  }
  if (tail === "/status") return fixtures.status().data;
  if (tail === "/adaptation") return fixtures.adaptation().data;
  if (tail === "/book-plan") return fixtures.plan().data;
  if (tail.startsWith("/validation/")) return fixtures.validation("demo", tail.split("/").at(-1)!).data ?? null;
  if (tail === "/pages") { if (completePagesUnavailable) throw new Error("Page plan is unavailable"); return fixtures.pages().data; }
  if (tail.endsWith("/source")) return fixtures.pageSource().data;
  if (tail === "/jobs") { if (generationJobsLoading) return new Promise(() => {}); return fixtures.jobs().data; }
  if (tail.includes("estimate")) {
    retryEstimate();
    if (stageEstimateFetching) return new Promise(() => {});
    if (estimateError) throw estimateError;
    return cost;
  }
  if (path === "/credits/balance") return { balance_credits: 100 };
  if (path === "/billing/packages") return { packages: [] };
  if (tail.endsWith("/visual-review")) return { cached: true, page_number: 1, render_revision: 2, render_image_sha256: "0".repeat(64), report: null, finding_issues: [], references: [] };
  if (/^\/pages\/\d+$/.test(tail)) return null;
  return null;
}

function seedRoom(client: QueryClient) {
  const entries: Array<[unknown[], unknown]> = [
    [["project", "demo", "status"], fixtures.status().data],
    [["project", "demo", "adaptation"], fixtures.adaptation().data],
    [["project", "demo", "book-plan"], fixtures.plan().data],
    [["project", "demo", "complete-pages"], fixtures.pages().data],
    [["project", "demo", "generation-jobs", []], generationJobsLoading ? undefined : fixtures.jobs().data],
    [["project", "demo", "validation", "adapt"], adaptValidation ?? null],
    [["project", "demo", "validation", "plan"], planValidation ?? null],
    [["credits", "balance"], { balance_credits: 100 }],
    [["billing", "packages"], { packages: [] }],
    [["project", "demo", "styles"], null],
  ];
  for (const [key, data] of entries) if (data !== undefined) client.setQueryData(key, data);
  for (const stage of stageEstimateFetching || estimateError ? [] : ["adapt", "plan", "draw"]) {
    for (const suffix of [[], ["restart"]]) client.setQueryData(["project", "demo", "estimate", stage, ...suffix], cost);
  }
  client.setQueryData(["project", "demo", "page-batch-estimate"], cost);
  for (const number of [1, 2, 3]) {
    client.setQueryData(["project", "demo", "complete-pages", number], null);
    client.setQueryData(["project", "demo", "complete-pages", number, "source"], fixtures.pageSource().data);
    client.setQueryData(["project", "demo", "page-analysis-estimate", number], cost);
    for (const depiction of ["canonical", "less_graphic"]) client.setQueryData(["project", "demo", "page-estimate", number, depiction], cost);
  }
  if (completePagesUnavailable) client.getQueryCache().build(client, { queryKey: ["project", "demo", "complete-pages"] }).setState({ status: "error", error: new Error("Page plan is unavailable") });
}

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
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false, staleTime: Infinity }, mutations: { retry: false } } });
  seedRoom(client);
  const room = () => (
    <QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[url]}>
      <I18nProvider>
        <Routes>
          <Route path="/project/:id/pages" element={<><PagesRoom /><LocationProbe /></>} />
          <Route path="/project/:id/story" element={<h1>Story brief</h1>} />
        </Routes>
      </I18nProvider>
    </MemoryRouter></QueryClientProvider>
  );
  const result = render(room());
  return { ...result, rerenderRoom: () => { seedRoom(client); result.rerender(room()); } };
}

describe("PagesRoom", () => {
  beforeEach(() => {
    productEvent.mockClear();
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
    letteringMode = undefined;
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
    adaptValidation = undefined;
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
    cleanup();
    usePipelineStore.setState(usePipelineStore.getInitialState());
  });

  it("sends a revised brief back to Story instead of offering a rejected start", async () => {
    briefApproved = false;
    stageStatuses.adapt = { status: "pending", stale: false };
    completePagesUnavailable = true;
    renderRoom();
    expect(screen.getByText("Approve your brief first")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start this step" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Review and approve brief" }));
    expect(screen.getByRole("heading", { name: "Story brief" })).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
  });

  it("offers an adaptation rerun after drawing has stopped, with explicit impact and consent", async () => {
    stageStatuses.draw = { status: "failed", stale: true };
    renderRoom();
    expect(screen.getByRole("button", { name: /Start adaptation over/ }).closest("footer")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Start adaptation over/ }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText(/archived and replaced/)).toBeTruthy();
    expect(within(dialog).getByText(/Drawing waits for you/)).toBeTruthy();
    expect(within(dialog).getByText(/~7/)).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: /Start adaptation over/ }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: true, retryFailed: undefined }, expect.any(Object),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(generatePage).not.toHaveBeenCalled();
  });

  it.each(["running", "pending"] as const)("offers no adaptation restart while the first page plan is %s", async (planStatus) => {
    stageStatuses.adapt = { status: "complete", stale: false };
    stageStatuses.plan = { status: planStatus, stale: false };
    stageStatuses.draw = { status: "pending", stale: false };
    completePagesUnavailable = true;
    renderRoom();
    expect(screen.queryByRole("button", { name: /Start adaptation over/ })).toBeNull();
  });

  it("keeps adaptation rerun available when the saved page plan cannot load", async () => {
    completePagesUnavailable = true;
    renderRoom();
    expect((screen.getByRole("button", { name: /Start adaptation over/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it.each(["project", "stage", "queued page", "running page"])("hides the action footer during %s work and restores it when work settles", async (kind) => {
    projectRunning = kind === "project";
    if (kind === "stage") stageStatuses.draw.status = "running";
    if (kind === "queued page" || kind === "running page") {
      generationJobResults = [{ id: "active-page", status: kind === "queued page" ? "queued" : "running", payload: { page_number: 1 } }];
    }
    const view = renderRoom();
    expect(view.container.querySelector("footer")).toBeNull();
    expect(screen.queryByRole("button", { name: /Start adaptation over/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Continue to Book" })).toBeNull();
    view.unmount();
    projectRunning = false;
    stageStatuses.draw.status = "awaiting_review";
    generationJobResults = [];
    renderRoom();
    expect(screen.getByRole("button", { name: /Start adaptation over/ }).closest("footer")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continue to Book" })).toBeTruthy();
  });

  it("hides the fallback footer while project work runs without loaded pages", async () => {
    projectRunning = true;
    completePagesUnavailable = true;
    const view = renderRoom();
    expect(view.container.querySelector("footer")).toBeNull();
    expect(screen.queryByRole("button", { name: /Start adaptation over/ })).toBeNull();
  });

  it("disables adaptation rerun while generation jobs are loading", async () => {
    generationJobsLoading = true;
    renderRoom();
    expect(screen.getByRole("button", { name: /Start adaptation over/ })).toHaveProperty("disabled", true);
  });

  it.each(["loading", "failed"])("blocks rerun confirmation when the estimate is %s", async (state) => {
    stageEstimateFetching = state === "loading";
    if (state === "failed") estimateError = new Error("Offline");
    renderRoom();
    expect(screen.getByRole("button", { name: /Start adaptation over/ }).closest("footer")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Start adaptation over/ }));
    const dialog = screen.getByRole("alertdialog");
    expect((within(dialog).getByRole("button", { name: /Start adaptation over/ }) as HTMLButtonElement).disabled).toBe(true);
    if (state === "failed") {
      await userEvent.click(within(dialog).getByRole("button", { name: "Retry estimate" }));
      expect(retryEstimate.mock.calls.length).toBeGreaterThanOrEqual(2);
    }
    await userEvent.click(within(dialog).getAllByRole("button", { name: "Cancel" })[1]);
    expect(runPipeline).not.toHaveBeenCalled();
  });

  it("keeps a rejected rerun visible in the confirmation so it can be retried", async () => {
    runPipeline.mockImplementation((_variables, options) => options?.onError?.(new Error("Wait for all project jobs to finish.")));
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: /Start adaptation over/ }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: /Start adaptation over/ }));
    expect(within(screen.getByRole("alertdialog")).getByRole("alert").textContent).toContain("Wait for all project jobs to finish.");
  });

  it("counts saved artwork against all planned pages even when the gallery is filtered", async () => {
    includeUndrawnPage = true;
    renderRoom("/project/demo/pages?filter=needs-review");

    expect(screen.getByText("1 of 2 pages drawn")).toBeTruthy();
    const progress = screen.getByRole("progressbar", { name: "Drawing progress" });
    expect(progress.getAttribute("value")).toBe("1");
    expect(progress.getAttribute("max")).toBe("2");
    expect(screen.queryByRole("button", { name: "Open page 2, revision 0" })).toBeNull();
  });

  it("opens flagged pages on the Page tab with their checks, without starting paid work", async () => {
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Needs you 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(dialog).getByRole("region", { name: "Checks" })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Text & findings" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Visual review" })).toBeNull();
    expect(generatePage).not.toHaveBeenCalled();
    expect(analyzePage).not.toHaveBeenCalled();
    expect(reviewVisuals).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Close page review" }));
    expect(screen.getByRole("button", { name: "Needs you 1" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("uses the artwork as the single review action and keeps revision detail in the dialog", async () => {
    renderRoom();

    expect(screen.queryByRole("button", { name: "Review page 1" })).toBeNull();
    expect(screen.queryByText("Revision 2")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByText("Revision 2")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(dialog).getByAltText("Complete page 1, render revision 2")).toBeTruthy();
    expect(generatePage).not.toHaveBeenCalled();
    expect(runPipeline).not.toHaveBeenCalled();
    expect(analyzePage).not.toHaveBeenCalled();
  });

  it("counts deliberate loaded review once, without inferring acceptance", async () => {
    pageIssues = [];
    renderRoom();
    expect(productEvent).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Read" }));
    expect(productEvent).not.toHaveBeenCalled();
    const image = within(screen.getByRole("dialog")).getByAltText("Complete page 1, render revision 2");
    fireEvent.load(image);
    expect(productEvent).toHaveBeenCalledExactlyOnceWith("page_viewed", {
      projectId: "demo", properties: { page_number: 1, render_revision: 2 },
    });
    fireEvent.load(image);
    expect(productEvent).toHaveBeenCalledTimes(1);
  });

  it("does not count restored or deep-linked review as deliberate viewing", async () => {
    renderRoom("/project/demo/pages?page=1&review=page");
    fireEvent.load(within(screen.getByRole("dialog")).getByAltText("Complete page 1, render revision 2"));
    expect(productEvent).not.toHaveBeenCalled();
  });

  it("offers Read when drawn pages have no unresolved findings", async () => {
    pageIssues = [];
    renderRoom();
    expect(screen.queryByRole("button", { name: /Review \d+ flagged/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Read" }));

    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
    expect(generatePage).not.toHaveBeenCalled();
  });


  it("offers to retry Adapt when Adapt failed before Plan started", async () => {
    stageStatuses = {
      adapt: { status: "failed", stale: false },
      plan: { status: "pending", stale: false },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(runPipeline).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    await userEvent.click(within(confirmation).getByRole("button", { name: "Resume adaptation" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: false, retryFailed: undefined },
      expect.any(Object),
    );
  });

  it("offers a non-destructive Adapt resume when Plan is blocked by a stale review", async () => {
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "failed", stale: false, error: "Narrative review is failed or stale. Rerun Adapt before drawing." },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;
    renderRoom();
    expect(runPipeline).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Resume adaptation" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: false, retryFailed: undefined },
      expect.any(Object),
    );
  });

  it("offers to start Adapt when a recovered project is pending", async () => {
    stageStatuses = {
      adapt: { status: "pending", stale: false },
      plan: { status: "pending", stale: false },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(runPipeline).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Start this step" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    await userEvent.click(within(confirmation).getByRole("button", { name: "Start this step" }));
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

  it("offers to retry Adapt when a server restart left it stale", async () => {
    stageStatuses = {
      adapt: { status: "running", stale: true },
      plan: { status: "pending", stale: false },
      draw: { status: "pending", stale: false },
    };
    completePagesUnavailable = true;

    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "Resume adaptation" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    await userEvent.click(within(confirmation).getByRole("button", { name: "Resume adaptation" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: false, retryFailed: undefined },
      expect.any(Object),
    );
  });

  it.each([false, true])("keeps Plan findings visible when the Adapt report has findings: %s", async (hasAdaptFindings) => {
    stageStatuses = {
      adapt: { status: "failed", stale: false },
      plan: { status: "failed", stale: false },
      draw: { status: "pending", stale: false },
    };
    adaptValidation = {
      invariant_failures: hasAdaptFindings ? [{
        id: "adapt-story", owner_stage: "adapt", code: "missing_essential_event",
        message: "Missing requirement essential_event_001", evidence: [],
      }] : [],
      recommendations: [],
    };
    planValidation = {
      invariant_failures: [{
        id: "plan-camera", owner_stage: "plan", code: "missing_panel_camera",
        message: "Missing camera", evidence: [],
      }],
      recommendations: [],
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(screen.getByRole("region", { name: "Page flow and staging" })).toBeTruthy();
    expect(Boolean(screen.queryByRole("region", { name: "Story coverage" }))).toBe(hasAdaptFindings);
    expect(screen.getByText("Resume or restart adaptation to check the script again before page planning continues.")).toBeTruthy();
    expect(screen.queryByText("Retry page planning to check these pages again.")).toBeNull();
    expect(runPipeline).not.toHaveBeenCalled();
  });

  it("leaves historic validation findings out of the current failure summary", async () => {
    stageStatuses.plan = { status: "failed", stale: false };
    adaptValidation = {
      invariant_failures: [{ id: "old-adapt", owner_stage: "adapt", code: "missing_essential_event",
        message: "Old script failure", evidence: [] }],
      recommendations: [],
    };
    planValidation = {
      invariant_failures: [{ id: "current-plan", owner_stage: "plan", code: "missing_panel_camera",
        message: "Current page failure", evidence: [] }],
      recommendations: [],
    };
    completePagesUnavailable = true;

    renderRoom();

    expect(screen.getByRole("region", { name: "Page flow and staging" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Story coverage" })).toBeNull();
    expect(screen.queryByText("Old script failure")).toBeNull();
  });

  it("regenerates Adapt when Plan reports undersegmented upstream beats", async () => {
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
    expect(within(screen.getByRole("region", { name: "Page flow and staging" })).getByText("Technical details").closest("details")?.open).toBe(false);
    expect(screen.queryByText("These contract failures block the book and cannot be accepted.")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Start adaptation over" }));
    const confirmation = screen.getByRole("alertdialog");
    expect(confirmation.textContent).toContain("archived and replaced");
    expect(within(confirmation).getByLabelText("about 7 credits")).toBeTruthy();
    expect(within(confirmation).getByLabelText("10 credits")).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();
    await userEvent.click(within(confirmation).getByRole("button", { name: "Start adaptation over" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "adapt", rerun: true, retryFailed: undefined },
      expect.any(Object),
    );
  });

  it("restores persisted Adapt progress after a refresh", async () => {
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

  it("shows the render canvas and revision history", async () => {
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    expect(screen.getByAltText("Complete page 1, render revision 2")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Compare with revision 1" })).toBeTruthy();
    expect(screen.queryByText("page-issue-1")).toBeNull();
    expect(screen.queryByText("rushed_aftermath")).toBeNull();
  });

  it("opens page review as an accessible dialog and closes it with Escape", async () => {
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(dialog).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Page 1 review" })).toBeNull();
  });

  it("closes page review when the backdrop is clicked but not its content", async () => {
    const user = userEvent.setup();
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    await userEvent.click(screen.getByRole("button", { name: "Page" }));
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBe(dialog);

    await user.click(dialog);
    expect(screen.queryByRole("dialog", { name: "Page 1 review" })).toBeNull();
  });

  it("keeps correction wording when text selection ends outside page review", async () => {
    const user = userEvent.setup();
    renderRoom();
    await user.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    const field = screen.getByLabelText("Describe a change");
    await user.type(field, "Restore the approved face.");
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });

    await user.pointer([
      { keys: "[MouseLeft>]", target: field, offset: 0 },
      { target: dialog },
      { keys: "[/MouseLeft]", target: dialog },
    ]);

    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBe(dialog);
    expect(field).toHaveProperty("value", "Restore the approved face.");
    expect(previewCorrections).not.toHaveBeenCalled();
    expect(submitCorrections).not.toHaveBeenCalled();
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

  it("submits selected suggestions and manual requests as one correction after preview", async () => {
    previewCorrections.mockImplementation((_variables, options) => {
      previewResult = stubPreviewResult();
      options?.onSuccess?.(previewResult);
    });
    submitCorrections.mockImplementation((_variables, options) => {
      options?.onSuccess?.({ status: "queued", job: { id: "job-correction-1" }, selected_issue_ids: ["page-issue-1"] });
    });
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    // Nothing is included until the author chooses it.
    expect(screen.queryByLabelText("Change 1")).toBeNull();
    expect(screen.getByRole("button", { name: "Add a change to review" })).toHaveProperty("disabled", true);
    await userEvent.click(within(screen.getByRole("region", { name: "Checks" })).getByRole("button", { name: "Add to changes" }));
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "Restore the approved face");
    fireEvent.change(screen.getByLabelText("Describe a change"), {
      target: { value: "Keep the reveal, but restore the approved face." },
    });
    expect(screen.getByRole("button", { name: "Review 2 changes" })).toHaveProperty("disabled", false);
    expect(previewCorrections).not.toHaveBeenCalled();

    // Submission is blocked until an explicit preview runs.
    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(submitCorrections).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Review 2 changes" }));
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
    expect(screen.getByLabelText("Describe a change")).toHaveProperty("value", "");
    expect(previewCorrections).toHaveBeenCalledOnce();

    await userEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(submitCorrections).toHaveBeenCalledWith(
      expect.objectContaining({ project: "demo", pageNumber: 1 }),
      expect.any(Object),
    );
    expect(screen.getByText("Redrawing this page")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^REVIEW .*CHANGE/ })).toBeNull();
    expect(screen.getByText(/You can close this page/)).toBeTruthy();
    expect(screen.getByLabelText("Change 1")).toHaveProperty("disabled", true);
  });

  it("requires a new review after the requested wording changes", async () => {
    previewCorrections.mockImplementation((_variables, options) => {
      previewResult = stubPreviewResult();
      options?.onSuccess?.(previewResult);
    });
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Add to changes" }));

    await userEvent.click(screen.getByRole("button", { name: "Review 1 change" }));
    expect(screen.getByRole("button", { name: "Generate revision" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Describe a change"), {
      target: { value: "A request that has not been added yet" },
    });
    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(submitCorrections).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Review 2 changes" }));
    expect(previewCorrections.mock.calls[1][0].body.changes).toHaveLength(2);
    expect(previewCorrections.mock.calls[1][0].body.changes[1].instruction)
      .toBe("A request that has not been added yet");
    expect(screen.getByRole("button", { name: "Generate revision" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Change 1"), {
      target: { value: "Restore the approved face and keep the lighting" },
    });

    expect(screen.queryByRole("button", { name: "Generate revision" })).toBeNull();
    expect(submitCorrections).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Review 2 changes" }));
    expect(previewCorrections).toHaveBeenCalledTimes(3);
    expect(previewCorrections.mock.calls[2][0].body.changes).toHaveLength(2);
    expect(previewCorrections.mock.calls[2][0].body.changes[0].instruction)
      .toBe("Restore the approved face and keep the lighting");
    await userEvent.click(screen.getByRole("button", { name: "Generate revision" }));
    expect(submitCorrections.mock.calls[0][0].body)
      .toEqual(previewCorrections.mock.calls[2][0].body);
  });

  it("shows the reason when a correction cannot be queued", async () => {
    previewCorrections.mockImplementation((_variables, options) => {
      previewResult = stubPreviewResult();
      options?.onSuccess?.(previewResult);
    });
    submitCorrections.mockImplementation((_variables, options) => {
      options?.onError?.(new Error("Saved edition conflict"));
    });
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Add to changes" }));

    await userEvent.click(screen.getByRole("button", { name: "Review 1 change" }));
    await userEvent.click(screen.getByRole("button", { name: "Generate revision" }));

    expect(screen.getByRole("alert").textContent).toContain("Saved edition conflict");
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "Restore the approved face");
    expect(previewCorrections).toHaveBeenCalledOnce();
    expect(submitCorrections).toHaveBeenCalledOnce();
  });

  it("offers queue-all or one-by-one when Draw starts", async () => {
    includeUndrawnPage = true;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "pending", stale: false },
    };
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "GO ONE BY ONE" }));
    expect(runPipeline).toHaveBeenLastCalledWith(
      { project: "demo", stage: "draw", queuePages: false },
      expect.any(Object),
    );

    await userEvent.click(screen.getByRole("button", { name: "QUEUE ALL PAGES" }));
    expect(runPipeline).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "CONFIRM QUEUE" }));
    expect(runPipeline).toHaveBeenLastCalledWith(
      { project: "demo", stage: "draw", queuePages: true },
      expect.any(Object),
    );
    expect(screen.getByRole("img", {
      name: "Page 2: generation in progress",
    })).toBeTruthy();
  });

  it("restores one-confirmation retry for all incomplete pages after a server restart", async () => {
    includeUndrawnPage = true;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "running", stale: true },
    };
    renderRoom();

    expect(screen.getByText("1 of 2 pages drawn")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "DRAW REMAINING PAGES" }));
    const confirmation = screen.getByRole("alertdialog", { name: "Retry the remaining pages?" });
    expect(within(confirmation).getByText(
      "Only pages without a saved render will be queued. Completed artwork stays available to review.",
    )).toBeTruthy();
    expect(runPipeline).not.toHaveBeenCalled();

    await userEvent.click(within(confirmation).getByRole("button", { name: "CONFIRM RETRY" }));
    expect(runPipeline).toHaveBeenCalledWith(
      { project: "demo", stage: "draw", queuePages: true },
      expect.any(Object),
    );
    expect(screen.getByText("1 of 2 pages drawn")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Page 2: generation in progress" })).toBeTruthy();
  });

  it("waits for current page-job status before offering a batch retry", async () => {
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

  it("offers to batch the remaining pages after choosing one-by-one", async () => {
    includeUndrawnPage = true;
    stageStatuses = {
      adapt: { status: "complete", stale: false },
      plan: { status: "complete", stale: false },
      draw: { status: "running", stale: false },
    };
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "DRAW REMAINING PAGES" }));
    expect(screen.getByRole("alertdialog", { name: "Queue all undrawn pages?" })).toBeTruthy();
  });

  it("keeps the remaining-pages action visible during an individual draw and enables it afterward", async () => {
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
    await userEvent.click(screen.getByRole("button", { name: "DRAW REMAINING PAGES" }));
    expect(screen.getByRole("alertdialog", { name: "Queue all undrawn pages?" })).toBeTruthy();
  });

  it("offers to stop a fully queued remaining batch and hides the action after cancellation", async () => {
    includeUndrawnPage = true;
    includeThirdUndrawnPage = true;
    stageStatuses.draw = { status: "running", stale: false };
    generationJobResults = [
      { id: "running-page", status: "running", payload: { page_number: 2 } },
      { id: "waiting-page", status: "queued", payload: { page_number: 3 } },
    ];
    const room = renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "STOP QUEUED DRAWING (1)" }));
    expect(cancelQueuedPages).toHaveBeenCalledWith("demo");
    expect(screen.getByRole("img", { name: "Page 2: generation in progress" })).toBeTruthy();

    generationJobResults[1].status = "cancelled";
    room.rerenderRoom();
    await waitFor(() => expect(screen.queryByRole("button", { name: /STOP QUEUED DRAWING/ })).toBeNull());
  });

  it.each(["queued", "running"] as const)("hides the stop action for one %s page", async (status) => {
    includeUndrawnPage = true;
    stageStatuses.draw = { status: "running", stale: false };
    generationJobResults = [{ id: "single-page", status, payload: { page_number: 2 } }];
    const room = renderRoom();
    expect(screen.queryByRole("button", { name: /STOP QUEUED DRAWING/ })).toBeNull();

    // Other unfinished pages do not turn a one-at-a-time request into a batch.
    includeThirdUndrawnPage = true;
    room.rerenderRoom();
    expect(screen.queryByRole("button", { name: /STOP QUEUED DRAWING/ })).toBeNull();
  });

  it("keeps the batch stop action out of page details", async () => {
    includeUndrawnPage = true;
    includeThirdUndrawnPage = true;
    stageStatuses.draw = { status: "running", stale: false };
    generationJobResults = [
      { id: "running-page", status: "running", payload: { page_number: 2 } },
      { id: "waiting-page", status: "queued", payload: { page_number: 3 } },
    ];
    renderRoom("/project/demo/pages?page=1&review=page");
    const review = within(screen.getByRole("dialog", { name: "Page 1 review" }));
    expect(review.queryByRole("button", { name: /STOP QUEUED DRAWING/ })).toBeNull();
    expect(screen.getByRole("button", { name: "STOP QUEUED DRAWING (1)" })).toBeTruthy();
  });

  it("explains OCR mismatches with full evidence and routes redraws through the draft", async () => {
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

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    expect(screen.getByText("Possible wording difference")).toBeTruthy();
    expect(screen.getByText("Open the door. · Run!")).toBeTruthy();
    expect(screen.getByText("Open the dor. · Run!")).toBeTruthy();
    expect(screen.getByText("POSSIBLE DIFFERENCES", { exact: false })).toBeTruthy();
    // No implicit per-issue redraw: fixes wait in the draft until previewed and submitted.
    expect(screen.queryByRole("button", { name: "CORRECT PAGE FINDINGS" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Not a problem" }));
    expect(dismissIssue).toHaveBeenCalledWith({
      project: "demo",
      pageNumber: 1,
      issueId: "page-issue-draw-page-001-render-002-misspelled_lettering",
    }, expect.any(Object));
    // Fix routes through the draft: the finding becomes an editable change in place.
    await userEvent.click(screen.getByRole("button", { name: "Add to changes" }));
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "OCR lettering does not exactly match canonical wording.");
    expect(screen.queryByRole("button", { name: "Add to changes" })).toBeNull();
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("summarizes insertions, deletions and reorders across every differing segment", async () => {
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

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    expect(screen.getByText("POSSIBLE DIFFERENCES · 3")).toBeTruthy();
    expect(screen.getByText(/Moved:/)).toBeTruthy();
    expect(screen.getByText(/Missing:/)).toBeTruthy();
    expect(screen.getByText(/Extra:/)).toBeTruthy();
  });

  it("generates one complete page from an undrawn page card", async () => {
    includeUndrawnPage = true;
    generatePage.mockImplementation((_variables, options) => {
      options?.onSuccess?.({ job: { id: "job-page-2" } });
    });
    renderRoom();

    expect(screen.queryByRole("button", { name: "Open page 2, revision 0" })).toBeNull();
    const generate = screen.getByRole("button", { name: "Draw page" });
    expect(within(generate.closest("article")!).getAllByRole("button")).toEqual([generate]);
    await userEvent.click(generate);
    expect(generatePage).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
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
    await waitFor(() => expect(screen.getByRole("button", { name: "Draw page" })).toBeTruthy());
    expect(screen.queryByText("IMAGE GENERATION FAILED")).toBeNull();
    // Empty filters are hidden: neither the old failure nor the old run counts.
    expect(screen.queryByRole("button", { name: /^Failed/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Drawing/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Draw page" })).toBeTruthy();
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

  it.each(["provider_blocked", "generation_error", "empty_response"] as const)("offers less-graphic recovery for %s without automatic generation", async (classification) => {
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

    await userEvent.click(screen.getByRole("button", { name: "DRAW LESS GRAPHIC VERSION" }));
    expect(generatePage).not.toHaveBeenCalled();
    await act(async () => { await userEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" })); });
    expect(generatePage).toHaveBeenLastCalledWith(
      { project: "demo", pageNumber: 2, depiction: "less_graphic" },
      expect.any(Object),
    );
  });

  it("keeps a provider failure visible after the temporary job is gone", async () => {
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
    await userEvent.click(screen.getByRole("button", { name: "DRAW LESS GRAPHIC VERSION" }));
    expect(generatePage).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("lets the author retry a recoverable image-service failure", async () => {
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
    expect(within(failedCard).queryByText("Ready to draw")).toBeNull();
    expect(within(failedCard).getAllByRole("button")).toEqual([retry]);
    await userEvent.click(retry);
    expect(generatePage).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
    expect(generatePage).toHaveBeenCalledWith(
      { project: "demo", pageNumber: 2 },
      expect.any(Object),
    );
  });

  it("retries a failed text check without redrawing the page", async () => {
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

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    expect(screen.getByText("The text check didn't finish.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Check text again" }));
    expect(analyzePage).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "CONFIRM TEXT CHECK" }));
    expect(analyzePage).toHaveBeenCalledWith({
      project: "demo",
      pageNumber: 1,
    }, expect.any(Object));
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("never asks for a manual check while pages are still drawing", async () => {
    analysisChecked = false;
    includeUndrawnPage = true;
    generationJobResults = [{ id: "drawing-job", status: "running" }];
    renderRoom();
    expect(screen.queryByRole("button", { name: "Check again" })).toBeNull();
    expect(screen.queryByText(/text check didn't finish/)).toBeNull();
  });

  it.each(["queued", "running"] as const)("hides suggestion actions until a %s revision finishes", async (status) => {
    pageIssues = [
      {
        id: "page-issue-manual-1", issue_type: "manual_change", status: "revised",
        requested_correction: "Close the upper eye.", resolution_revision: 2,
      },
      {
        id: `visual-review-${"a".repeat(64)}-1`, issue_type: "visual_prop", status: "open",
        requested_correction: "Restore the approved gun.", resolution_revision: null,
      },
      {
        id: "page-issue-manual-2", issue_type: "manual_change", status: "open",
        requested_correction: "Move the lamp.", resolution_revision: null,
      },
      {
        id: "page-issue-text-1", issue_type: "misspelled_lettering", status: "open",
        requested_correction: "Restore the caption.", resolution_revision: null,
        evidence: ['expected_text=["Hello"]', 'recognized_text=["Helo"]', "crop_check_status=inconclusive", "crop_check_complete=false"],
      },
    ].map((issue) => ({
      classification: "editorial_issue", correction_kind: "render_fidelity", correction_owner: "draw",
      page_number: 1, render_revision: 1, evidence: [issue.requested_correction], ...issue,
    }));
    generationJobResults = [{ id: "new-revision", status, payload: { page_number: 1 } }];
    const room = renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    const checks = screen.getByRole("region", { name: "Checks" });
    expect(within(checks).getByText("Checks run when the page finishes drawing.")).toBeTruthy();
    expect(within(checks).getAllByText("Close the upper eye.").length).toBeGreaterThan(0);
    expect(within(checks).queryByText(/does it look fixed/i)).toBeNull();
    expect(within(checks).queryAllByRole("button")).toHaveLength(0);

    generationJobResults = [{ id: "new-revision", status: "complete", payload: { page_number: 1 } }];
    await act(async () => room.rerenderRoom());
    expect(within(checks).getByText(/does it look fixed/i)).toBeTruthy();
    for (const name of ["Still wrong", "Looks fixed", "Add to changes", "Not a problem", "Withdraw request", "DOUBLE-CHECK"]) {
      expect(within(checks).getAllByRole("button", { name }).length).toBeGreaterThan(0);
    }
    expect(generatePage).not.toHaveBeenCalled();
    expect(dismissIssue).not.toHaveBeenCalled();
  });

  it("clears an automatic visual finding as not a problem, or fixes it through the draft", async () => {
    pageIssues = [{
      id: `visual-review-${"a".repeat(64)}-1`,
      issue_type: "visual_prop",
      classification: "editorial_issue",
      correction_kind: "render_fidelity",
      correction_owner: "draw",
      page_number: 1,
      render_revision: 2,
      evidence: ["Panel 3: The scar ring is on the fourth finger.", "Expected: base of the third finger."],
      requested_correction: "Move the scar ring to the third finger.",
      status: "open",
      resolution_revision: null,
    }];
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    const checks = screen.getByRole("region", { name: "Checks" });
    expect(within(checks).getByText("1 thing to look at.", { exact: false })).toBeTruthy();
    expect(within(checks).getByText("Object")).toBeTruthy();
    await userEvent.click(within(checks).getByRole("button", { name: "Not a problem" }));
    expect(dismissIssue).toHaveBeenCalledWith({
      project: "demo", pageNumber: 1, issueId: `visual-review-${"a".repeat(64)}-1`,
    }, expect.any(Object));
    // The observed problem leads; the suggested fix waits behind Details until Fix makes it the change.
    expect(within(checks).getByText("Panel 3: The scar ring is on the fourth finger.")).toBeTruthy();
    await userEvent.click(within(checks).getByRole("button", { name: "Add to changes" }));
    expect(within(checks).getByLabelText("Change 1")).toHaveProperty("value", "Move the scar ring to the third finger.");
    expect(within(checks).getByText(/In your changes/)).toBeTruthy();
    await userEvent.click(within(checks).getByRole("button", { name: "Remove" }));
    expect(within(checks).getByRole("button", { name: "Add to changes" })).toBeTruthy();
    expect(reviewVisuals).not.toHaveBeenCalled();
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("treats a finding a newer check already cleared as done, not as an error", async () => {
    dismissIssue.mockImplementation((_vars, options: { onError?: (error: Error) => void }) => options.onError?.(
      new Error(`API 422: page issue 'visual-review-${"a".repeat(64)}-1' was not found`),
    ));
    pageIssues = [{
      id: `visual-review-${"a".repeat(64)}-1`, issue_type: "visual_prop", classification: "editorial_issue",
      correction_kind: "render_fidelity", correction_owner: "draw", page_number: 1, render_revision: 2,
      evidence: ["Panel 3: The scar ring is on the fourth finger."], requested_correction: "Move the scar ring.",
      status: "open", resolution_revision: null,
    }];
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    await userEvent.click(within(screen.getByRole("region", { name: "Checks" })).getAllByRole("button", { name: "Not a problem" })[0]);
    expect(dismissIssue).toHaveBeenCalled();
    expect(screen.queryByText(/was not found/)).toBeNull();
    expect(screen.queryByText("Your decision was not saved. Try again.", { exact: false })).toBeNull();
  });

  it("continues to Book with unchecked artwork without running or charging for OCR", async () => {
    analysisChecked = false;
    pageIssues = [];
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Continue to Book" }));
    expect(continueToBook).toHaveBeenCalledWith({ project: "demo", stage: "draw" }, expect.any(Object));
    expect(recoverChecks).not.toHaveBeenCalled();
    expect(estimateChecks).not.toHaveBeenCalled();
    expect(analyzePage).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("does not let a historical generation failure mask recoverable evidence or recovered analysis", async () => {
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
    await act(async () => { renderRoom(); });
    expect(screen.queryByRole("button", { name: "RETRY TEXT CHECK" })).toBeNull();
    expect(screen.queryByText("Old generic failure")).toBeNull();
  });

  it("continues to Book through the Draw checkpoint", async () => {
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "Continue to Book" }));
    expect(continueToBook).toHaveBeenCalledWith(
      { project: "demo", stage: "draw" },
      expect.any(Object),
    );
  });

  it("opens gallery-first with the page image immediately visible", async () => {
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    const reviseTab = screen.getByRole("button", { name: "Page" });
    expect(reviseTab.getAttribute("aria-pressed")).toBe("true");
    // Integrated lettering lives in the art: only the page (with its checks) and its source.
    expect(screen.queryByRole("button", { name: "Lettering" })).toBeNull();
    expect(screen.getByRole("button", { name: "Source" }).getAttribute("aria-pressed")).toBe("false");
    // Artwork renders in the first viewport, not behind reading overlays; changes are written beside it.
    expect(screen.getByAltText("Complete page 1, render revision 2")).toBeTruthy();
    expect(screen.getByLabelText("Describe a change")).toBeTruthy();
    // The checks sit with the page, below the artwork.
    expect(screen.getByRole("region", { name: "Checks" })).toBeTruthy();
  });

  it("offers the Lettering tab only for editable lettering", async () => {
    letteringMode = "hybrid";
    renderRoom("/project/demo/pages?page=1&review=lettering");
    expect(screen.getByRole("button", { name: "Lettering" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("falls back to the page when an integrated page is linked to Lettering", async () => {
    renderRoom("/project/demo/pages?page=1&review=lettering");
    expect(screen.queryByRole("button", { name: "Lettering" })).toBeNull();
    expect(screen.getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("region", { name: "Checks" })).toBeTruthy();
  });

  it("shows the manuscript source for the open page under Source", async () => {
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Source" }));

    expect(screen.getByRole("button", { name: "Source" }).getAttribute("aria-pressed")).toBe("true");
    const region = screen.getByRole("region", { name: "Source" });
    expect(within(region).getByText("Mara argued at the market.").tagName).toBe("MARK");
    expect(within(region).getByText("Lettering positions are not available for this artwork.")).toBeTruthy();
  });

  it("switches to Source and back and keeps the draft mounted", async () => {
    renderRoom();

    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    fireEvent.change(screen.getByLabelText("Describe a change"), {
      target: { value: "Keep the reveal, but restore the approved face." },
    });

    await userEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByRole("button", { name: "Source" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("region", { name: "Source" })).toBeTruthy();

    // Unsaved draft state survives tab switches: the draft stays mounted hidden.
    await userEvent.click(screen.getByRole("button", { name: "Page" }));
    expect(screen.getByLabelText("Describe a change")).toHaveProperty(
      "value",
      "Keep the reveal, but restore the approved face.",
    );
  });

  it("never shows blanket Confirmed while revised visual concerns remain", async () => {
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
    expect(screen.getByText("Confirm fix")).toBeTruthy();
    expect(card.textContent).not.toContain("Confirmed");
  });

  it("marks a clean page whose editable lettering still needs a placement check", async () => {
    pageIssues = [];
    placementReviewNeeded = true;
    renderRoom();

    expect(screen.getByText("Needs placement")).toBeTruthy();
  });

  it("does not infer page acceptance from resolved findings", async () => {
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

  it("opens book adaptation as a full reading workspace and returns to the gallery", async () => {
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Page documents" }));
    await userEvent.click(screen.getByRole("button", { name: "Adaptation" }));

    expect(screen.getByRole("region", { name: "Adaptation" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open page 1, revision 2" })).toBeNull();
    expect(screen.getByRole("complementary", { name: "Throughline" })).toBeTruthy();
    expect(screen.getByText("A quarrel seeds the voyage")).toBeTruthy();
    expect(screen.getByText("Mara argues at the market")).toBeTruthy();
    expect(screen.queryByText("EDITORIAL FINDINGS")).toBeNull();
    expect(screen.queryByText("SAVED CHANGES")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Back to pages" }));
    expect(screen.queryByRole("region", { name: "Adaptation" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open page 1, revision 2" })).toBeTruthy();
  });

  it("switches reading documents in the URL and preserves the gallery filter without generating", async () => {
    renderRoom("/project/demo/pages?filter=needs-review");
    await userEvent.click(screen.getByRole("button", { name: "Page documents" }));
    await userEvent.click(screen.getByRole("button", { name: "Adaptation" }));
    expect(screen.getByLabelText("Current route").textContent).toContain("reading=adaptation");
    await userEvent.click(screen.getByRole("button", { name: "Page plan" }));
    expect(screen.getByRole("region", { name: "Page plan" })).toBeTruthy();
    expect(screen.getByLabelText("Current route").textContent).toContain("reading=page-plan");
    expect(screen.getByText("A slow-burn rhythm")).toBeTruthy();
    expect(screen.getByText("One dominant reveal")).toBeTruthy();
    expect(screen.getAllByText("Hold, then reveal").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Back to pages" }));
    expect(screen.getByLabelText("Current route").textContent).not.toContain("reading=");
    expect(screen.getByRole("button", { name: "Needs you 1" }).getAttribute("aria-pressed")).toBe("true");
    expect(generatePage).not.toHaveBeenCalled();
    expect(runPipeline).not.toHaveBeenCalled();
    expect(submitCorrections).not.toHaveBeenCalled();
  });

  it("opens the full reading workspace from a deep link", async () => {
    renderRoom("/project/demo/pages?reading=page-plan");
    expect(screen.getByRole("region", { name: "Page plan" })).toBe(document.activeElement);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each(["adaptation", "page-plan"])("returns unfinished %s deep links to Pages without a reading header", async (kind) => {
    stageStatuses.adapt.status = "running";
    stageStatuses.plan.status = "pending";
    renderRoom(`/project/demo/pages?reading=${kind}&filter=needs-review`);
    expect(screen.queryByRole("region", { name: "Adaptation" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Page plan" })).toBeNull();
    expect(screen.getByLabelText("Current route").textContent).not.toContain("reading=");
    expect(screen.getByLabelText("Current route").textContent).toContain("filter=needs-review");
    await userEvent.click(screen.getByRole("button", { name: "Page documents" }));
    expect(screen.getByRole("button", { name: "Adaptation" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Page plan" })).toHaveProperty("disabled", true);
  });

  it("opens a Book finding on the requested page and review view", async () => {
    includeUndrawnPage = true;
    renderRoom("/project/demo/pages?page=1&review=page&filter=needs-review");
    const dialog = screen.getByRole("dialog", { name: "Page 1 review" });
    expect(within(dialog).getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(within(dialog).getByRole("button", { name: "NEXT PAGE" }));
    expect(screen.getByRole("dialog", { name: "Page 2 review" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Next that needs you · 1" }));
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Close page review" }));
    expect(screen.queryByRole("button", { name: "Open page 2, revision 0" })).toBeNull();
    expect(screen.getByRole("button", { name: "Needs you 1" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("restores review context in this session but lets explicit links win", async () => {
    window.sessionStorage.setItem("page-review:v2:signed-out:demo", "page=1&review=source&filter=needs-review");
    const first = renderRoom();
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Source" }).getAttribute("aria-pressed")).toBe("true");
    first.unmount();
    renderRoom("/project/demo/pages?page=1&review=page&filter=all");
    expect(screen.getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("ignores invalid review URL values without choosing an arbitrary page", async () => {
    renderRoom("/project/demo/pages?page=-3&review=unknown&filter=unknown");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "All 1" }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    expect(screen.getByRole("button", { name: "Page" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("restores server-side drawing jobs and keeps completed artwork inspectable", async () => {
    includeUndrawnPage = true;
    generationJobResults = [{ id: "resumed-job", status: "running" }];
    renderRoom("/project/demo/pages?filter=drawing");
    expect(screen.getByRole("button", { name: "Drawing 1" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("img", { name: "Page 2: generation in progress" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Inspect completed page 1" }));
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBeTruthy();
    expect(generatePage).not.toHaveBeenCalled();
  });

  it("blocks paid drawing when the estimate fails and preserves the gallery context", async () => {
    includeUndrawnPage = true;
    estimateError = new Error("Estimate unavailable");
    renderRoom("/project/demo/pages?filter=all");
    await userEvent.click(screen.getByRole("button", { name: "Draw page" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("alert").textContent).toContain("Estimate unavailable");
    await userEvent.click(within(dialog).getByRole("button", { name: "RETRY ESTIMATE" }));
    expect(retryEstimate.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(generatePage).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getAllByRole("button", { name: /Cancel/i })[0]);
    expect(screen.getByRole("button", { name: "Draw page" })).toBeTruthy();
  });

  it("keeps a submission error next to consent without automatically retrying", async () => {
    includeUndrawnPage = true;
    generatePage.mockImplementation((_variables, options) => options.onError(new Error("Connection interrupted")));
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Draw page" }));
    await userEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
    expect(within(screen.getByRole("alertdialog")).getByRole("alert").textContent).toContain("Connection interrupted");
    expect(generatePage).toHaveBeenCalledOnce();
    await userEvent.click(within(screen.getByRole("alertdialog")).getAllByRole("button", { name: /Cancel/i })[0]);
    expect(screen.getByRole("alert").textContent).toContain("Connection interrupted");
    expect(screen.getByRole("button", { name: "Draw page" })).toBeTruthy();
  });

  it("shows a persisted Draw batch failure when page plans are already available", async () => {
    includeUndrawnPage = true;
    stageStatuses.draw = { status: "failed", stale: false, error: "Durable generation queue is unavailable" };
    renderRoom();
    expect(screen.getByRole("alert").textContent).toContain("Durable generation queue is unavailable");
    expect(screen.getByRole("button", { name: /DRAW REMAINING PAGES/ })).toBeTruthy();
  });

  it.each([true, false])("explains a storage rejection in the gallery, including saved raw failures (structured: %s)", async (structured) => {
    includeUndrawnPage = true;
    const raw = "413: {'code': 'storage_budget_exceeded', 'used_bytes': 7991982797, 'limit_bytes': 5368709120}";
    stageStatuses.draw = { status: "failed", stale: false,
      error: structured ? "Account storage is full." : raw,
      error_code: structured ? "storage_budget_exceeded" : null,
    };
    renderRoom();
    expect(screen.getByRole("heading", { name: "Account storage is full" })).toBeTruthy();
    expect(screen.getByText("Delete projects you no longer need from their settings, then return here to try again.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Manage projects" }).getAttribute("href")).toBe("/");
    expect(screen.getByText("Technical details").closest("details")?.open).toBe(false);
    if (!structured) expect(screen.getByText(raw, { exact: false }).closest("details")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Complete page thumbnail 1, revision 2" })).toBeTruthy();
    expect(generatePage).not.toHaveBeenCalled();
    expect(runPipeline).not.toHaveBeenCalled();
  });

  it("offers project management for an immediate storage rejection without retrying the draw", async () => {
    includeUndrawnPage = true;
    generatePage.mockImplementation((_variables, options) => options.onError(new ApiError(413,
      "Account storage is full. Delete projects you no longer need from their settings, then try again.",
      "storage_budget_exceeded",
    )));
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Draw page" }));
    await userEvent.click(screen.getByRole("button", { name: "CONFIRM DRAW" }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("heading", { name: "Account storage is full" })).toBeTruthy();
    expect(within(dialog).getByRole("link", { name: "Manage projects" }).getAttribute("href")).toBe("/");
    expect(within(dialog).queryByText(/API 413/)).toBeNull();
    expect(generatePage).toHaveBeenCalledOnce();
  });
});
