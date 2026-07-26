import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const createIssue = vi.fn();
const correctIssue = vi.fn();
const continueToBook = vi.fn();
const generatePage = vi.fn();
const trackGenerationJobs = vi.fn((project?: string, ids: string[] = []) => {
  void project;
  void ids;
  return { data: { jobs: [] } };
});
let includeUndrawnPage = false;

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({
    data: {
      stages: {
        adapt: { status: "complete" },
        plan: { status: "complete" },
        draw: { status: "awaiting_review" },
      },
    },
  }),
  useAdaptation: () => ({
    data: {
      editorial_issues: [{
        id: "adapt-issue-1",
        owner_stage: "adapt",
        code: "rushed_aftermath",
        message: "The aftermath is compressed.",
        evidence: ["Source units 80–92"],
      }],
    },
  }),
  useBookPlan: () => ({ data: { editorial_issues: [] } }),
  useCompletePages: () => ({
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
  }),
  useGenerateCompletePage: () => ({ mutate: generatePage, isPending: false }),
  useCreatePageIssue: () => ({ mutate: createIssue, isPending: false }),
  useCorrectPageIssue: () => ({ mutate: correctIssue, isPending: false }),
  useAcceptPageIssue: () => ({ mutate: vi.fn(), isPending: false }),
  useApproveStage: () => ({ mutate: continueToBook, isPending: false }),
  useRunPipeline: () => ({ mutate: vi.fn(), isPending: false }),
  useGenerationJobs: (project: string | undefined, ids: string[]) => trackGenerationJobs(project, ids),
  useCreditBalance: () => ({ data: undefined }),
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
    createIssue.mockReset();
    correctIssue.mockReset();
    continueToBook.mockReset();
    generatePage.mockReset();
    trackGenerationJobs.mockClear();
    includeUndrawnPage = false;
  });

  it("shows Adapt and Plan exceptions before page generation", () => {
    renderRoom();

    expect(screen.getByRole("heading", { name: "ADAPT & PLAN EXCEPTIONS" })).toBeTruthy();
    expect(screen.getByText("The aftermath is compressed.")).toBeTruthy();
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
    expect(screen.getByRole("dialog", { name: "Page 1 review" })).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
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

  it("continues to Book through the Draw checkpoint", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "CONTINUE TO BOOK" }));
    expect(continueToBook).toHaveBeenCalledWith(
      { project: "demo", stage: "draw" },
      expect.any(Object),
    );
  });
});
