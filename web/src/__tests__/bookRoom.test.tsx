import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const exportBook = vi.fn();
const finishPreflight = vi.fn();
let unresolvedIssueIds: string[] = [];
let acceptedIssueIds: string[] = ["page-issue-1"];
let invariantFailures: Array<{
  id: string;
  owner_stage: "draw";
  code: string;
  message: string;
  evidence: string[];
  blocking?: true;
}> = [];
let preflightLoading = false;
let finishStatus = "pending";
let drawStatus = "complete";

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({
    data: {
      finish_ready: finishStatus === "complete",
      stages: {
        finish: { status: finishStatus },
        draw: { status: drawStatus },
      },
    },
  }),
  useFinishPreflight: (...args: [string | undefined, boolean]) => {
    finishPreflight(...args);
    return {
      data: preflightLoading ? undefined : {
        edition_revision: 1,
        pages: [
          {
            page_number: 1,
            comic_page_revision: 2,
            render_revision: 3,
            invariant_failures: invariantFailures,
            unresolved_editorial_issue_ids: unresolvedIssueIds,
            accepted_editorial_issue_ids: acceptedIssueIds,
          },
        ],
        correction_requests: [],
        packages: [{ format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 }],
        packaging_failures: [],
      },
      isLoading: preflightLoading,
      error: null,
    };
  },
  useExport: () => ({ mutate: exportBook, isPending: false, data: null, error: null }),
  useCreditBalance: () => ({ data: undefined }),
}));

import { BookRoom } from "../pages/rooms/BookRoom";

function renderRoom() {
  render(
    <MemoryRouter initialEntries={["/project/demo/book"]}>
      <I18nProvider>
        <Routes>
          <Route path="/project/:id/book" element={<BookRoom />} />
        </Routes>
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("BookRoom", () => {
  beforeEach(() => {
    exportBook.mockReset();
    finishPreflight.mockReset();
    unresolvedIssueIds = [];
    acceptedIssueIds = ["page-issue-1"];
    invariantFailures = [];
    preflightLoading = false;
    finishStatus = "pending";
    drawStatus = "complete";
  });

  it("runs Finish preflight automatically after Draw completes", () => {
    renderRoom();

    expect(finishPreflight).toHaveBeenCalledWith("demo", true);
  });

  it("shows Finish preflight and accepted issue evidence", () => {
    renderRoom();

    expect(screen.getByRole("heading", { name: "FINISH PREFLIGHT" })).toBeTruthy();
    expect(screen.getByText("1 page ready")).toBeTruthy();
    expect(screen.getByText("1 accepted editorial issue")).toBeTruthy();
    expect(screen.queryByText(/compose/i)).toBeNull();
    expect(screen.queryByText("page-issue-1")).toBeNull();
  });

  it("shows a clean result as success instead of a warning", () => {
    acceptedIssueIds = [];
    renderRoom();

    expect(screen.getByText("NO EDITORIAL ISSUES")).toBeTruthy();
    expect(screen.getByText("No editorial issues")).toBeTruthy();
    expect(screen.queryByText("Finish preflight runs before the first export. It does not call an image model.")).toBeNull();
  });

  it("separates technical findings from editorial issue decisions", () => {
    acceptedIssueIds = [];
    invariantFailures = [{
      id: "finish-page-001-exact_ocr_status",
      owner_stage: "draw",
      code: "exact_ocr_status",
      message: "Active page render lacks exact canonical OCR status.",
      evidence: ["The detector result needs visual review."],
      blocking: true,
    }];
    renderRoom();

    expect(screen.getByText("1 technical findings")).toBeTruthy();
    expect(screen.getByText("NO EDITORIAL ISSUES")).toBeTruthy();
    expect(screen.getByText("No editorial issues")).toBeTruthy();
    expect(screen.getByText("Active page render lacks exact canonical OCR status.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "EXPORT PDF" })).toHaveProperty("disabled", true);
  });

  it("keeps export disabled while the automatic preflight is running", () => {
    preflightLoading = true;
    renderRoom();

    expect(screen.getByText("CHECKING THE BOOK…")).toBeTruthy();
    expect(screen.getByRole("button", { name: "EXPORT PDF" })).toHaveProperty("disabled", true);
  });

  it("exports the verified book", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "EXPORT PDF" }));
    expect(exportBook).toHaveBeenCalledWith({
      project: "demo",
      format: "pdf",
    });
  });

  it("blocks export while preflight still has an unresolved page issue", () => {
    unresolvedIssueIds = ["page-issue-2"];
    renderRoom();

    expect(screen.getByRole("button", { name: "EXPORT PDF" })).toHaveProperty("disabled", true);
  });
});
