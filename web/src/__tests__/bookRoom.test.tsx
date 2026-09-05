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
let diagnostics: Array<{
  id: string;
  owner_stage: "plan";
  code: string;
  message: string;
  evidence: string[];
}> = [];
let preflightLoading = false;
let finishStatus = "pending";
let drawStatus = "complete";

function drawnPage(
  pageNumber: number,
  spreadRole: "single" | "left" | "right" | "spread" = "single",
  revision: number | null = 1,
) {
  return {
    page: { page_number: pageNumber, spread_role: spreadRole },
    active_render: revision === null ? null : { render: { revision } },
  };
}

let drawnPages: ReturnType<typeof drawnPage>[] = [drawnPage(1)];

vi.mock("../api/queries", () => ({
  useProviderUsage: () => ({ data: undefined }),
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
            diagnostics,
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
  useCompletePages: () => ({ data: { pages: drawnPages } }),
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
    diagnostics = [];
    window.localStorage.removeItem("canary.showDevContent");
    preflightLoading = false;
    finishStatus = "pending";
    drawStatus = "complete";
    drawnPages = [drawnPage(1)];
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

  it("keeps non-blocking continuity diagnostics out of the author view", () => {
    diagnostics = [{
      id: "finish-page-001-cross_page_appearance_state",
      owner_stage: "plan",
      code: "cross_page_appearance_state",
      message: "Page-scoped appearance state is stale across pages.",
      evidence: ["Internal state evidence."],
    }];

    renderRoom();

    expect(screen.queryByText("Page-scoped appearance state is stale across pages.")).toBeNull();
    expect(screen.getByRole("button", { name: "EXPORT PDF" })).not.toHaveProperty("disabled", true);
  });

  it("shows continuity diagnostics only with Dev Content enabled", () => {
    window.localStorage.setItem("canary.showDevContent", "1");
    diagnostics = [{
      id: "finish-page-001-cross_page_appearance_state",
      owner_stage: "plan",
      code: "cross_page_appearance_state",
      message: "Page-scoped appearance state is stale across pages.",
      evidence: ["Internal state evidence."],
    }];

    renderRoom();

    expect(screen.getByRole("heading", { name: "TECHNICAL DIAGNOSTICS" })).toBeTruthy();
    expect(screen.getByText("Page-scoped appearance state is stale across pages.")).toBeTruthy();
  });

  it("keeps export disabled while the automatic preflight is running", () => {
    preflightLoading = true;
    renderRoom();

    expect(screen.getByText("PREPARING PREFLIGHT…")).toBeTruthy();
    expect(screen.getByRole("button", { name: "EXPORT PDF" })).toHaveProperty("disabled", true);
  });

  it("exports the verified book", () => {
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "EXPORT PDF" }));
    expect(exportBook).toHaveBeenCalledWith(
      { project: "demo", format: "pdf" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("blocks export while preflight still has an unresolved page issue", () => {
    unresolvedIssueIds = ["page-issue-2"];
    renderRoom();

    expect(screen.getByRole("button", { name: "EXPORT PDF" })).toHaveProperty("disabled", true);
  });

  it("offers the reader once pages are drawn", () => {
    drawnPages = [drawnPage(1), drawnPage(2)];
    renderRoom();

    expect(screen.getByRole("heading", { name: "READ THE BOOK" })).toBeTruthy();
    expect(screen.getByText("2 pages drawn")).toBeTruthy();
  });

  it("hides the reader when no page has been drawn", () => {
    drawnPages = [drawnPage(1, "single", null)];
    renderRoom();

    expect(screen.queryByRole("heading", { name: "READ THE BOOK" })).toBeNull();
    expect(screen.queryByRole("button", { name: "START READING" })).toBeNull();
  });

  it("reads pages from the screen rendition tied to each render revision", () => {
    drawnPages = [drawnPage(1), drawnPage(2)];
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "START READING" }));

    const reader = screen.getByRole("dialog", { name: "Book reader" });
    expect(reader).toBeTruthy();
    const sources = Array.from(reader.querySelectorAll("img")).map((img) => img.getAttribute("src"));
    expect(sources).toContain("/api/projects/demo/pages/1/renders/1/preview/reader");
  });

  it("turns pages with the arrow keys and closes on Escape", () => {
    drawnPages = [drawnPage(1), drawnPage(2)];
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "START READING" }));
    expect(screen.getByText("Page 1")).toBeTruthy();

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText("Page 2")).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Book reader" })).toBeNull();
  });

  it("reads a facing pair as one spread", () => {
    drawnPages = [drawnPage(1), drawnPage(2, "left"), drawnPage(3, "right")];
    renderRoom();

    fireEvent.click(screen.getByRole("button", { name: "START READING" }));
    fireEvent.keyDown(window, { key: "ArrowRight" });

    expect(screen.getByText("Pages 2–3")).toBeTruthy();
  });
});
