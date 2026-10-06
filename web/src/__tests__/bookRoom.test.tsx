import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setMedia } from "mock-match-media";
import { I18nProvider } from "../i18n";
import type { CreditHistoryPage, FinishPreflight } from "../types/api";
import type * as PagesApi from "../api/pages";

const exportBook = vi.fn();
const rerunPreflight = vi.fn();
const retryPreflight = vi.fn();
let preflight: FinishPreflight;
let preflightLoading = false;
let preflightRefreshing = false;
let preflightError: Error | null = null;
let exportError: Error | null = null;
let pendingFormat: "pdf" | "cbz" | null = null;
let devDiagnostics = false;
const recoverChecks = vi.fn();
const finishChecks = vi.fn();
const replanEstimate = vi.fn();
const replanPage = vi.fn();
let finishStageStatus = "complete";
let drawStageStatus = "complete";
let creditHistory: { pages: CreditHistoryPage[] };

function drawnPage(pageNumber: number, spreadRole: "single" | "left" | "right" = "single", revision: number | null = 1) {
  return {
    page: { page_number: pageNumber, spread_role: spreadRole },
    active_render: revision === null ? null : { render: { revision } },
    issues: [],
    analysis_recovery: { status: revision === null ? "undrawn" : "checked", requires_paid_call: false },
  };
}
let drawnPages = [drawnPage(1)];
const storyBible = {
  characters: [{ id: "kaitlin", name: "Kaitlin Morris", appearance_states: [
    { id: "kaitlin_clothes", label: "Son's old clothes" }, { id: "kaitlin_raincoat", label: "Oversized raincoat" },
  ] }],
  locations: [], props: [],
};


vi.mock("../api/queries", () => ({
  useCreditHistory: () => ({
    data: creditHistory,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
  }),
  useProjectStatus: () => ({ data: {
    project_name: "The Lantern Keeper",
    finish_ready: true,
    stages: { finish: { status: finishStageStatus }, draw: { status: drawStageStatus } },
  } }),
  useFinishPreflight: () => ({
    data: preflightLoading || preflightError ? undefined : {
      ...preflight,
      pages: preflight.pages.map((page) => ({ ...page, diagnostics: devDiagnostics ? [{
        id: "continuity", owner_stage: "plan", code: "continuity",
        message: "Internal continuity evidence", evidence: [],
      }] : [] })),
    },
    isLoading: preflightLoading,
    isFetching: preflightLoading || preflightRefreshing,
    error: preflightError,
    refetch: retryPreflight,
  }),
  useExport: () => ({ mutate: exportBook, isPending: pendingFormat !== null, variables: pendingFormat ? { format: pendingFormat } : undefined, error: exportError }),
  useCreditBalance: () => ({ data: undefined }),
  useCompletePages: () => ({ data: { pages: drawnPages } }),
  useRunFinishPreflight: () => ({ mutate: rerunPreflight, isPending: false, error: null }),
  useStoryBible: () => ({ data: storyBible }),
}));

vi.mock("../api/pages", async (importOriginal) => ({
  ...await importOriginal<typeof PagesApi>(),
  recoverPageChecks: (...args: unknown[]) => recoverChecks(...args),
  runFinishPreflight: (...args: unknown[]) => finishChecks(...args),
  getPageReplanEstimate: (...args: unknown[]) => replanEstimate(...args),
  replanPage: (...args: unknown[]) => replanPage(...args),
}));

import { BookRoom } from "../pages/rooms/BookRoom";

function renderRoom() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
    <MemoryRouter initialEntries={["/project/demo/book"]}>
      <I18nProvider><Routes><Route path="/project/:id/book" element={<BookRoom />} /></Routes></I18nProvider>
    </MemoryRouter></QueryClientProvider>,
  );
}

beforeEach(() => {
  exportBook.mockReset();
  retryPreflight.mockReset();
  preflightLoading = false;
  preflightRefreshing = false;
  preflightError = null;
  exportError = null;
  pendingFormat = null;
  devDiagnostics = false;
  creditHistory = { pages: [{ runs: [], limit: 30, offset: 0, has_more: false, month_used_credits: 0, spend_by_stage: {} }] };
  finishStageStatus = "complete";
  drawStageStatus = "complete";
  rerunPreflight.mockReset();
  recoverChecks.mockReset();
  finishChecks.mockReset().mockResolvedValue({ status: "done" });
  replanEstimate.mockReset().mockResolvedValue({ estimate_credits: 2, reserved_credits: 3, reservation_multiplier: 1.5, confidence: "variable" });
  replanPage.mockReset().mockResolvedValue({ page_number: 16, revision: 2 });
  window.localStorage.removeItem("canary.showDevContent");
  drawnPages = [drawnPage(1)];
  preflight = {
    edition_revision: 1,
    pages: [{ page_number: 1, comic_page_revision: 2, render_revision: 3,
      invariant_failures: [], unresolved_editorial_issue_ids: [], accepted_editorial_issue_ids: [] }],
    correction_requests: [], packages: [], packaging_failures: [],
  };
});

describe("BookRoom edition decisions", () => {
  it("shows the book credit ledger without provider costs or model internals", () => {
    creditHistory.pages[0].spend_by_stage = { style: 20, draw: 9 };
    creditHistory.pages[0].runs = [{
      run_id: "draw-1", job_id: "job-1", stage: "draw", project_id: "demo",
      started_at: "2026-09-20T14:00:00Z", last_activity_at: "2026-09-20T14:01:00Z",
      estimate_credits: 12, actual_credits: 9, returned_credits: 3, credits_added: 0,
      status: "complete", action: null, page_number: 4, rows: [{
        id: "charge-1", amount_credits: -9, status: "settled", stage: "draw",
        created_at: "2026-09-20T14:01:00Z", image_count: 1, label: "Page art", page_number: 4,
      }],
    }];
    renderRoom();
    expect(screen.getByRole("heading", { name: "CREDIT HISTORY" })).toBeTruthy();
    expect(screen.getByText("Spent on this book").parentElement?.textContent).toContain("29 credits");
    expect(screen.getByText("Drew page 4")).toBeTruthy();
    expect(screen.getByText("charged").parentElement?.textContent).toContain("9 credits charged");
    expect(screen.getByText("Reserved 12, charged 9, 3 returned to your balance.")).toBeTruthy();
    // A book's own history never names the project, so a part key cannot misname it.
    expect(screen.queryByText("Project no longer available")).toBeNull();
    expect(screen.queryByText(/USD|gemini|provider/i)).toBeNull();
  });

  it("summarises outstanding lettering acceptance as one optional check without blocking export", () => {
    preflight.pages = [1, 2, 3].map((page_number) => ({
      page_number, comic_page_revision: 1, render_revision: 1, lettering_placement_review_needed: page_number > 1,
      invariant_failures: [], unresolved_editorial_issue_ids: [], accepted_editorial_issue_ids: [],
    }));
    renderRoom();
    const check = screen.getByText("Lettering on 2 pages hasn’t been checked by eye").closest("li")!;
    expect(within(check).getByText("Optional")).toBeTruthy();
    expect(within(check).getByRole("link", { name: "Start with page 2" }).getAttribute("href"))
      .toBe("/project/demo/pages?page=2&review=lettering");
    expect(within(check).getByRole("link", { name: "Review lettering placement · Page 3" }).getAttribute("href"))
      .toBe("/project/demo/pages?page=3&review=lettering");
    expect(screen.getByText("2 pages to check by eye")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", false);
    expect(screen.queryByRole("region", { name: "TECHNICAL DIAGNOSTICS" })).toBeNull();
  });

  it("does not warn about placement for accepted or retained baked pages", () => {
    renderRoom();
    expect(screen.queryByText(/checked by eye/)).toBeNull();
    expect(screen.getByText("Every page is ready to export.")).toBeTruthy();
    expect(screen.getByText("Ready to export")).toBeTruthy();
  });

  it("explains a blocker once per page in the author's terms and names who it involves", () => {
    const failure = (content: string) => ({
      id: "finish-page-016-cross_page_appearance_state", owner_stage: "plan" as const, code: "cross_page_appearance_state",
      message: "Page-scoped appearance state is stale across pages.",
      artifact_ids: [content, "kaitlin", "kaitlin_clothes", "kaitlin_raincoat"],
      evidence: ["Page content cites states not yet activated for 'kaitlin': ['kaitlin_raincoat']."],
    });
    preflight.pages[0] = { ...preflight.pages[0], page_number: 16, invariant_failures: [failure("content_1"), failure("content_2")] };
    renderRoom();
    const check = screen.getByText("A character’s look is out of order").closest("li")!;
    expect(within(check).getByText("Blocks export")).toBeTruthy();
    expect(within(check).getByText("Kaitlin Morris · “Oversized raincoat”")).toBeTruthy();
    expect(within(check).getByText(/redrawing alone won’t clear it/)).toBeTruthy();
    // Two findings on the same page are one thing to fix, and the page is listed once.
    expect(within(check).getAllByRole("link")).toHaveLength(1);
    expect(within(check).getByRole("link", { name: "Open page · Page 16" }).getAttribute("href"))
      .toBe("/project/demo/pages?page=16&review=page");
    expect(screen.queryByText("Page-scoped appearance state is stale across pages.")).toBeNull();
    expect(screen.getByText("1 fix needed before export")).toBeTruthy();
    expect(screen.getAllByText("1 fix needed first")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
  });

  it("offers grouped check recovery when Finish is ready before Draw approval", () => {
    finishStageStatus = "pending";
    drawStageStatus = "awaiting_review";
    drawnPages = [drawnPage(1), drawnPage(2)];
    drawnPages.forEach((page) => {
      page.analysis_recovery = { status: "requires_ocr", requires_paid_call: true };
    });
    preflight.pages = [1, 2].map((page_number) => ({
      page_number, comic_page_revision: 1, render_revision: 1,
      invariant_failures: [{ id: `missing-${page_number}`, owner_stage: "draw", code: "exact_ocr_status",
        message: "Saved artwork needs text evidence", evidence: [`Render ${page_number}`] }],
      unresolved_editorial_issue_ids: [], accepted_editorial_issue_ids: [],
    }));
    renderRoom();
    expect(screen.getAllByText("Saved artwork needs text evidence")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Check again" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("link", { name: "Open page checks · Page 1" })).toBeTruthy();
  });

  it("groups missing evidence and refreshes preflight after free recovery without exporting", async () => {
    drawnPages = [drawnPage(1), drawnPage(2)];
    drawnPages.forEach((page) => { page.analysis_recovery.status = "cached_evidence"; });
    preflight.pages = [1, 2].map((page_number) => ({
      page_number, comic_page_revision: 1, render_revision: 1,
      invariant_failures: [{ id: `missing-${page_number}`, owner_stage: "draw", code: "ocr_evidence_missing",
        message: "Saved artwork needs text evidence", evidence: [`Render ${page_number}`] }],
      unresolved_editorial_issue_ids: [], accepted_editorial_issue_ids: [],
    }));
    recoverChecks.mockResolvedValue({ pages: [{ page_number: 1, status: "checked" },
      { page_number: 2, status: "failed", error: "Retained evidence needs parser repair" }] });
    renderRoom();
    expect(screen.getAllByText("Saved artwork needs text evidence")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
    expect(screen.getByText(/The text check didn't finish on 2 pages/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByText("The text check still didn't finish on 1 page.");
    expect(screen.queryByText(/Page 1:/)).toBeNull();  // One summary line, not a row per page.
    await waitFor(() => expect(finishChecks).toHaveBeenCalledWith("demo"));
    expect(recoverChecks).toHaveBeenCalledOnce();
    expect(recoverChecks).toHaveBeenCalledWith("demo", false, {});
    expect(exportBook).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("keeps accepted editorial decisions inspectable without blocking packaging", () => {
    preflight.pages[0].accepted_editorial_issue_ids = ["accepted-concern"];
    renderRoom();
    fireEvent.click(screen.getByText("Accepted decisions (1)"));
    expect(screen.getByRole("link", { name: "Page 1 · 1 accepted" }).getAttribute("href")).toBe("/project/demo/pages?page=1&review=page");
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", false);
  });

  it("re-plans a page that looks ahead only after the author confirms its estimate", async () => {
    preflight.pages[0] = { ...preflight.pages[0], page_number: 16, invariant_failures: [{
      id: "finish-page-016-cross_page_appearance_state", owner_stage: "plan", code: "cross_page_appearance_state",
      message: "Page-scoped appearance state is stale across pages.",
      artifact_ids: ["page_016_content_001", "kaitlin", "kaitlin_clothes", "kaitlin_raincoat"],
      evidence: ["Page content cites states not yet activated for 'kaitlin': ['kaitlin_raincoat']."],
    }] };
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Re-plan page 16" }));
    const drawer = await screen.findByRole("alertdialog");
    await waitFor(() => expect(within(drawer).getByText(/~2 credits/)).toBeTruthy());
    expect(replanEstimate).toHaveBeenCalledWith("demo", 16);
    expect(replanPage).not.toHaveBeenCalled();
    fireEvent.click(within(drawer).getByRole("button", { name: "Re-plan page 16" }));
    await waitFor(() => expect(replanPage).toHaveBeenCalledWith("demo", 16));
    await waitFor(() => expect(retryPreflight).toHaveBeenCalled());
  });

  it("does not offer a page re-plan for Adapt-owned chronology", () => {
    preflight.pages[0].invariant_failures = [{
      id: "finish-page-001-cross_page_appearance_state", owner_stage: "adapt", code: "cross_page_appearance_state",
      message: "Appearance-state chronology is inconsistent.", evidence: [],
    }];
    renderRoom();
    expect(screen.queryByRole("button", { name: /Re-plan page/ })).toBeNull();
  });

  it("routes technical and editorial blockers to their distinct page reviews", () => {
    preflight.pages[0].invariant_failures = [{ id: "file", owner_stage: "draw", code: "missing", message: "Page file missing", evidence: [] }];
    preflight.pages[0].unresolved_editorial_issue_ids = ["visual-concern"];
    renderRoom();
    expect(screen.getByRole("link", { name: "Open page checks · Page 1" }).getAttribute("href")).toBe("/project/demo/pages?page=1&review=page");
    expect(screen.getByRole("link", { name: "Review page 1" }).getAttribute("href")).toBe("/project/demo/pages?page=1&review=page");
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Create CBZ" })).toHaveProperty("disabled", true);
  });

  it("links correction requests to the exact page checks", () => {
    preflight.correction_requests = [{ id: "correction", page_number: 7, failure_codes: ["lettering"], requested_correction: "Restore missing caption" }];
    renderRoom();
    expect(screen.getByRole("link", { name: "Open page checks · Page 7" }).getAttribute("href")).toBe("/project/demo/pages?page=7&review=page");
  });

  it("recovers an unavailable preflight inline without enabling export", () => {
    preflightError = new Error("The check was interrupted. Please retry.");
    renderRoom();
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Create CBZ" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Retry edition checks" }));
    expect(retryPreflight).toHaveBeenCalledOnce();
    expect(screen.getByText("The check was interrupted. Please retry.")).toBeTruthy();
  });

  it("blocks both formats while a preflight is loading", () => {
    preflightLoading = true;
    renderRoom();
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Create CBZ" })).toHaveProperty("disabled", true);
  });

  it("keeps internal diagnostics out of author decisions and does not block export", () => {
    devDiagnostics = true;
    renderRoom();
    expect(screen.queryByText("Internal continuity evidence")).toBeNull();
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", false);
  });

  it("makes internal diagnostics inspectable with Dev Content enabled", () => {
    devDiagnostics = true;
    window.localStorage.setItem("canary.showDevContent", "1");
    renderRoom();
    expect(screen.getByText("Internal continuity evidence")).toBeTruthy();
  });

  it("restores a server-confirmed package receipt and download without requiring another export", () => {
    preflight.packages = [{ format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 }];
    renderRoom();
    expect(screen.getByText("Ready to download")).toBeTruthy();
    expect(screen.getByRole("link", { name: "DOWNLOAD PDF" }).getAttribute("href")).toBe("/api/projects/demo/export/pdf");
    expect(screen.queryByRole("button", { name: "Create PDF" })).toBeNull();
    expect(screen.getByRole("button", { name: "Create CBZ" })).toBeTruthy();
    expect(exportBook).not.toHaveBeenCalled();
  });

  it("offers each confirmed export as its own download without creating it again", () => {
    preflight.packages = [
      { format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 },
      { format: "cbz", relative_path: "exports/comic.cbz", byte_size: 4096 },
    ];
    renderRoom();
    expect(screen.getByRole("link", { name: "DOWNLOAD PDF" }).getAttribute("href"))
      .toBe("/api/projects/demo/export/pdf");
    expect(screen.getByRole("link", { name: "DOWNLOAD CBZ" }).getAttribute("href"))
      .toBe("/api/projects/demo/export/cbz");
    expect(screen.queryByRole("button", { name: "Create PDF" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create CBZ" })).toBeNull();
    expect(exportBook).not.toHaveBeenCalled();
  });

  it("does not promise cached downloads while package availability is being rechecked", () => {
    preflight.packages = [{ format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 }];
    preflightRefreshing = true;
    renderRoom();
    expect(screen.queryByText("Ready to download")).toBeNull();
    expect(screen.queryByRole("link", { name: "DOWNLOAD PDF" })).toBeNull();
    expect(screen.queryByText(/^1 page ready$/)).toBeNull();
    expect(screen.queryByText("Ready to package")).toBeNull();
    expect(screen.queryByText("No technical blockers")).toBeNull();
    expect(screen.getByRole("button", { name: "Create CBZ" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByText("Rebuild package"));
    expect(screen.getByRole("button", { name: "Rebuild PDF" })).toHaveProperty("disabled", true);
  });

  it("withholds a previously saved download when the edition has a new blocker", () => {
    preflight.packages = [{ format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 }];
    preflight.pages[0].unresolved_editorial_issue_ids = ["new-visual-concern"];
    renderRoom();
    expect(screen.queryByText("Ready to download")).toBeNull();
    expect(screen.queryByRole("link", { name: "DOWNLOAD PDF" })).toBeNull();
    fireEvent.click(screen.getByText("Rebuild package"));
    expect(screen.getByRole("button", { name: "Rebuild PDF" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Create CBZ" })).toHaveProperty("disabled", true);
    expect(exportBook).not.toHaveBeenCalled();
  });

  it("names the busy format and prevents competing package requests", () => {
    pendingFormat = "cbz";
    renderRoom();
    expect(screen.getByRole("button", { name: "Creating CBZ…" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
  });

  it("does not announce an edition ready when export returns no confirmed package", () => {
    exportBook.mockImplementation((_variables, callbacks) => callbacks.onSuccess({ url: null, preflight }));
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Create PDF" }));
    expect(screen.queryByText("Ready to download")).toBeNull();
  });

  it("reruns persisted packaging failures rather than only rereading the same report", () => {
    preflight.packaging_failures = [{ id: "package", owner_stage: "finish", code: "package", message: "Could not normalize files", evidence: [] }];
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Retry edition checks" }));
    expect(rerunPreflight).toHaveBeenCalledWith({ project: "demo" });
    expect(retryPreflight).not.toHaveBeenCalled();
  });

  it("shows a persistent receipt only after the server confirms the created package", () => {
    exportBook.mockImplementation((_variables, callbacks) => {
      preflight = { ...preflight, packages: [{ format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 }] };
      callbacks.onSuccess({ url: "/saved-edition.pdf", preflight });
    });
    const room = renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Create PDF" }));
    expect(screen.getByText("Ready to download")).toBeTruthy();
    expect(screen.getByRole("link", { name: "DOWNLOAD PDF" }).getAttribute("href")).toBe("/saved-edition.pdf");
    expect(screen.getByText("Edition ready · PDF").getAttribute("role")).toBe("status");
    room.unmount();
    renderRoom();
    expect(screen.getByText("Ready to download")).toBeTruthy();
    expect(screen.getByRole("link", { name: "DOWNLOAD PDF" }).getAttribute("href")).toBe("/api/projects/demo/export/pdf");
  });

  it("can rebuild a previously packaged PDF after a second format export fails", () => {
    preflight.packages = [{ format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 }];
    exportError = new Error("CBZ packaging failed");
    exportBook.mockImplementation((_variables, callbacks) => {
      exportError = null;
      callbacks.onSuccess({ url: "/rebuilt-edition.pdf", preflight });
    });
    renderRoom();
    expect(screen.getByRole("alert").textContent).toContain("CBZ packaging failed");
    fireEvent.click(screen.getByText("Rebuild package"));
    fireEvent.click(screen.getByRole("button", { name: "Rebuild PDF" }));
    expect(exportBook).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Rebuild PDF" }));
    expect(exportBook).toHaveBeenCalledWith(
      { project: "demo", format: "pdf", force: true },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
    expect(screen.getByRole("link", { name: "DOWNLOAD PDF" }).getAttribute("href")).toBe("/rebuilt-edition.pdf");
  });
});

describe("Book reader", () => {
  it("does not offer reading before a page has artwork", () => {
    drawnPages = [drawnPage(1, "single", null)];
    renderRoom();
    expect(screen.queryByRole("button", { name: "Read your book" })).toBeNull();
  });

  it("reads the saved rendition, reaches an intentional ending and returns to the edition", () => {
    drawnPages = [drawnPage(1), drawnPage(2)];
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    const reader = screen.getByRole("dialog", { name: "Book reader" });
    expect(within(reader).getByAltText("Page 1 — Page 1").getAttribute("src")).toBe("/api/projects/demo/pages/1/renders/1/preview/reader?delivery=2");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(within(reader).getByText("End of book")).toBeTruthy();
    fireEvent.click(within(reader).getByRole("button", { name: "Back to edition" }));
    expect(screen.queryByRole("dialog", { name: "Book reader" })).toBeNull();
    expect(exportBook).not.toHaveBeenCalled();
    expect(rerunPreflight).not.toHaveBeenCalled();
    expect(recoverChecks).not.toHaveBeenCalled();
  });

  it("keeps a facing pair together and preserves its page when switching layouts", () => {
    setMedia({ width: 1366, height: 768 });
    drawnPages = [drawnPage(1), drawnPage(2, "left"), drawnPage(3, "right")];
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("slider", { name: "Jump to page" }).getAttribute("aria-valuetext")).toBe("Pages 2–3 of 3");
    fireEvent.click(screen.getByRole("button", { name: "SPREADS" }));
    expect(screen.getByRole("slider", { name: "Jump to page" }).getAttribute("aria-valuetext")).toBe("Page 2 of 3");
  });

  it("reads single pages in narrow windows and keeps the page when the window widens", () => {
    setMedia({ width: 375, height: 812 });
    drawnPages = [drawnPage(1), drawnPage(2, "left"), drawnPage(3, "right")];
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    const slider = () => screen.getByRole("slider", { name: "Jump to page" });
    fireEvent.keyDown(window, { key: "ArrowRight" });
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(slider().getAttribute("aria-valuetext")).toBe("Page 3 of 3");
    act(() => setMedia({ width: 1366, height: 768 }));
    expect(slider().getAttribute("aria-valuetext")).toBe("Pages 2–3 of 3");
    // An explicit choice outlasts later window changes, on the page last turned to.
    fireEvent.click(screen.getByRole("button", { name: "SPREADS" }));
    act(() => setMedia({ width: 375, height: 812 }));
    act(() => setMedia({ width: 1366, height: 768 }));
    expect(slider().getAttribute("aria-valuetext")).toBe("Page 3 of 3");
  });

  it("covers the whole viewport instead of sitting inside the room's spacing", () => {
    drawnPages = [drawnPage(1)];
    const { container } = renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    const reader = screen.getByRole("dialog", { name: "Book reader" });
    expect(reader.parentElement).toBe(document.body);
    expect(container.contains(reader)).toBe(false);
  });

  it("does not hijack keyboard input intended for the page slider", () => {
    drawnPages = [drawnPage(1), drawnPage(2), drawnPage(3)];
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    const slider = screen.getByRole("slider", { name: "Jump to page" });
    act(() => slider.focus());
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(slider.getAttribute("aria-valuetext")).toBe("Page 1 of 3");
    fireEvent.change(slider, { target: { value: "1" } });
    expect(slider.getAttribute("aria-valuetext")).toBe("Page 2 of 3");
  });
});
