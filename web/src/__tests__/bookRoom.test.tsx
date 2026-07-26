import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const exportBook = vi.fn();
let unresolvedIssueIds: string[] = [];

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({
    data: {
      finish_ready: true,
      stages: { finish: { status: "complete" } },
    },
  }),
  useFinishPreflight: () => ({
    data: {
      edition_revision: 1,
      pages: [
        {
          page_number: 1,
          comic_page_revision: 2,
          render_revision: 3,
          invariant_failures: [],
          unresolved_editorial_issue_ids: unresolvedIssueIds,
          accepted_editorial_issue_ids: ["page-issue-1"],
        },
      ],
      correction_requests: [],
      packages: [{ format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 }],
      packaging_failures: [],
    },
    isLoading: false,
    error: null,
  }),
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
    unresolvedIssueIds = [];
  });

  it("shows Finish preflight and accepted issue evidence", () => {
    renderRoom();

    expect(screen.getByRole("heading", { name: "FINISH PREFLIGHT" })).toBeTruthy();
    expect(screen.getByText("1 page ready")).toBeTruthy();
    expect(screen.getByText("1 accepted editorial issue")).toBeTruthy();
    expect(screen.queryByText(/compose/i)).toBeNull();
    expect(screen.queryByText("page-issue-1")).toBeNull();
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
