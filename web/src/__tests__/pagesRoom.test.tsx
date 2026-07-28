import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { SHOW_DEV_CONTENT_KEY } from "../lib/devContent";
import type { EditorialIssue, StageStatus } from "../types/api";

const createIssue = vi.fn();
const correctIssue = vi.fn();
const continueToBook = vi.fn();
const generatePage = vi.fn();
const runPipeline = vi.fn();
const trackGenerationJobs = vi.fn((project?: string, ids: string[] = []) => {
  void project;
  void ids;
  return { data: { jobs: [] } };
});
let includeUndrawnPage = false;
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
let completePagesUnavailable = false;
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

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({
    data: {
      stages: stageStatuses,
    },
  }),
  useAdaptation: () => ({
    data: {
      editorial_issues: adaptationIssues,
    },
  }),
  useBookPlan: () => ({ data: { editorial_issues: planIssues } }),
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
        issues: [{
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
  useCreatePageIssue: () => ({ mutate: createIssue, isPending: false }),
  useCorrectPageIssue: () => ({ mutate: correctIssue, isPending: false }),
  useAcceptPageIssue: () => ({ mutate: vi.fn(), isPending: false }),
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
    createIssue.mockReset();
    correctIssue.mockReset();
    continueToBook.mockReset();
    generatePage.mockReset();
    runPipeline.mockReset();
    trackGenerationJobs.mockClear();
    includeUndrawnPage = false;
    completePagesUnavailable = false;
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

  it("keeps internal editorial diagnostics out of the author journey", () => {
    adaptationIssues = [
      {
        id: "adapt-issue-1",
        owner_stage: "adapt",
        code: "rushed_reaction_or_aftermath",
        message: "The aftermath is compressed.",
        evidence: ["Beat 1 reaches a transition without an aftermath."],
      },
      {
        id: "shared-continuity-issue",
        owner_stage: "adapt",
        code: "continuity_state_mismatch",
        message: "A location transition may skip an intermediate place.",
        evidence: ["Expected the studio; found Providence."],
      },
      {
        id: "adapt-issue-2",
        owner_stage: "adapt",
        code: "rushed_reaction_or_aftermath",
        message: "The aftermath is compressed.",
        evidence: ["Beat 2 reaches a transition without an aftermath."],
      },
    ];
    planIssues = [
      {
        id: "plan-issue-1",
        owner_stage: "plan",
        code: "weak_page_turn",
        message: "The reveal lacks a page-turn setup.",
        evidence: ["Page 1 is none; page 2 is none."],
      },
      {
        id: "shared-continuity-issue",
        owner_stage: "plan",
        code: "continuity_state_mismatch",
        message: "A location transition may skip an intermediate place.",
        evidence: ["Expected the studio; found Providence."],
      },
    ];

    renderRoom();

    expect(screen.queryByText("4 diagnostics")).toBeNull();
    expect(screen.queryByText("SHOW DIAGNOSTICS")).toBeNull();
    expect(screen.queryByText("The aftermath is compressed.")).toBeNull();
    expect(screen.queryByText("The reveal lacks a page-turn setup.")).toBeNull();
    expect(screen.getByText("PAGE GALLERY")).toBeTruthy();
  });

  it("shows validation signals as internal diagnostics with Dev Content enabled", () => {
    window.localStorage.setItem(SHOW_DEV_CONTENT_KEY, "1");
    adaptationIssues = [
      {
        id: "adapt-issue-1",
        owner_stage: "adapt",
        code: "rushed_reaction_or_aftermath",
        message: "The aftermath is compressed.",
        evidence: ["Beat 1 reaches a transition without an aftermath."],
      },
      {
        id: "adapt-issue-2",
        owner_stage: "adapt",
        code: "rushed_reaction_or_aftermath",
        message: "The aftermath is compressed.",
        evidence: ["Beat 2 reaches a transition without an aftermath."],
      },
    ];
    planIssues = [{
      id: "plan-issue-1",
      owner_stage: "plan",
      code: "weak_page_turn",
      message: "The reveal lacks a page-turn setup.",
      evidence: ["Page 1 is none; page 2 is none."],
    }];

    renderRoom();

    expect(screen.getByText("3 diagnostics")).toBeTruthy();
    expect(screen.getByText("DEV CONTENT")).toBeTruthy();
    expect(
      screen.getByText(
        "Internal validation signals for development inspection. They do not block the book or require author action.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("The aftermath is compressed.")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "SHOW DIAGNOSTICS" }));

    expect(screen.getAllByText("The aftermath is compressed.")).toHaveLength(1);
    expect(screen.getByText("×2")).toBeTruthy();
    expect(screen.getByText("The reveal lacks a page-turn setup.")).toBeTruthy();
    expect(screen.getByText("Beat 1 reaches a transition without an aftermath.")).toBeTruthy();
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

  it("shows complete-page thumbnails and revision history", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    expect(screen.getByAltText("Complete page 1, revision 2")).toBeTruthy();
    expect(screen.getByText("Revision 1 → Revision 2")).toBeTruthy();
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
    fireEvent.click(screen.getByText("CANONICAL PAGE INTENT"));
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBe(dialog);

    fireEvent.click(dialog);
    expect(screen.queryByRole("dialog", { name: "Page 1 review" })).toBeNull();
  });

  it("creates a page issue and requests a complete-page correction", () => {
    correctIssue.mockImplementation((_variables, options) => {
      options?.onSuccess?.({ job: { id: "job-correction-1" } });
    });
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));

    fireEvent.change(screen.getByLabelText("What needs correction?"), {
      target: { value: "Keep the reveal, but restore the approved face." },
    });
    fireEvent.click(screen.getByRole("button", { name: "ADD PAGE ISSUE" }));
    expect(createIssue).toHaveBeenCalledWith(expect.objectContaining({
      project: "demo",
      pageNumber: 1,
      requestedCorrection: "Keep the reveal, but restore the approved face.",
    }));

    fireEvent.click(screen.getByRole("button", { name: "CORRECT COMPLETE PAGE" }));
    expect(correctIssue).toHaveBeenCalledWith(
      {
        project: "demo",
        pageNumber: 1,
        issueId: "page-issue-1",
      },
      expect.any(Object),
    );
    expect(trackGenerationJobs).toHaveBeenLastCalledWith("demo", ["job-correction-1"]);
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

  it("continues to Book through the Draw checkpoint", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "CONTINUE TO BOOK" }));
    expect(continueToBook).toHaveBeenCalledWith(
      { project: "demo", stage: "draw" },
      expect.any(Object),
    );
  });
});
