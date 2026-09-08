import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n";
import type { FinishPreflight } from "../types/api";
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
let finishStageStatus = "complete";
let drawStageStatus = "complete";

function drawnPage(pageNumber: number, spreadRole: "single" | "left" | "right" = "single", revision: number | null = 1) {
  return {
    page: { page_number: pageNumber, spread_role: spreadRole },
    active_render: revision === null ? null : { render: { revision } },
    issues: [],
    analysis_recovery: { status: revision === null ? "undrawn" : "checked", requires_paid_call: false },
  };
}
let drawnPages = [drawnPage(1)];

vi.mock("../api/queries", () => ({
  useProviderUsage: () => ({ data: undefined }),
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
}));

vi.mock("../api/pages", async (importOriginal) => ({
  ...await importOriginal<typeof PagesApi>(),
  recoverPageChecks: (...args: unknown[]) => recoverChecks(...args),
  runFinishPreflight: (...args: unknown[]) => finishChecks(...args),
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
  finishStageStatus = "complete";
  drawStageStatus = "complete";
  rerunPreflight.mockReset();
  recoverChecks.mockReset();
  finishChecks.mockReset().mockResolvedValue({ status: "done" });
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
    expect(screen.getByRole("button", { name: "Recover missing text checks" })).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "Recover missing text checks" }));
    await screen.findByText(/Retained evidence needs parser repair/);
    await waitFor(() => expect(finishChecks).toHaveBeenCalledWith("demo"));
    expect(recoverChecks).toHaveBeenCalledOnce();
    expect(recoverChecks).toHaveBeenCalledWith("demo", false, {});
    expect(exportBook).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("keeps accepted editorial decisions inspectable without blocking packaging", () => {
    preflight.pages[0].accepted_editorial_issue_ids = ["accepted-concern"];
    renderRoom();
    fireEvent.click(screen.getByText("Accepted decisions"));
    expect(screen.getByRole("link", { name: "Page 1 · 1 accepted" }).getAttribute("href")).toBe("/project/demo/pages?page=1&review=visual");
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", false);
  });

  it("routes technical and editorial blockers to their distinct page reviews", () => {
    preflight.pages[0].invariant_failures = [{ id: "file", owner_stage: "draw", code: "missing", message: "Page file missing", evidence: [] }];
    preflight.pages[0].unresolved_editorial_issue_ids = ["visual-concern"];
    renderRoom();
    expect(screen.getByRole("link", { name: "Open page checks · Page 1" }).getAttribute("href")).toBe("/project/demo/pages?page=1&review=checks");
    expect(screen.getByRole("link", { name: "Review page 1" }).getAttribute("href")).toBe("/project/demo/pages?page=1&review=visual");
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
  });

  it("links correction requests to the exact page checks", () => {
    preflight.correction_requests = [{ id: "correction", page_number: 7, failure_codes: ["lettering"], requested_correction: "Restore missing caption" }];
    renderRoom();
    expect(screen.getByRole("link", { name: "Open page checks · Page 7" }).getAttribute("href")).toBe("/project/demo/pages?page=7&review=checks");
  });

  it("recovers an unavailable preflight inline without enabling export", () => {
    preflightError = new Error("Unavailable");
    renderRoom();
    expect(screen.getByRole("button", { name: "Create PDF" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Retry edition checks" }));
    expect(retryPreflight).toHaveBeenCalledOnce();
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
    expect(screen.getByRole("heading", { name: "Edition ready" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "DOWNLOAD PDF" }).getAttribute("href")).toBe("/api/projects/demo/export/pdf");
    expect(screen.queryByRole("button", { name: "Create PDF" })).toBeNull();
    expect(screen.getByRole("button", { name: "Create CBZ" })).toBeTruthy();
    expect(exportBook).not.toHaveBeenCalled();
  });

  it("does not promise cached downloads while package availability is being rechecked", () => {
    preflight.packages = [{ format: "pdf", relative_path: "exports/comic.pdf", byte_size: 2048 }];
    preflightRefreshing = true;
    renderRoom();
    expect(screen.queryByRole("heading", { name: "Edition ready" })).toBeNull();
    expect(screen.queryByRole("link", { name: "DOWNLOAD PDF" })).toBeNull();
    fireEvent.click(screen.getByText("Rebuild package"));
    expect(screen.getByRole("button", { name: "Rebuild PDF" })).toHaveProperty("disabled", true);
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
    expect(screen.queryByRole("heading", { name: "Edition ready" })).toBeNull();
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
    expect(screen.getByRole("heading", { name: "Edition ready" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "DOWNLOAD PDF" }).getAttribute("href")).toBe("/saved-edition.pdf");
    room.unmount();
    renderRoom();
    expect(screen.getByRole("heading", { name: "Edition ready" })).toBeTruthy();
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
    expect(within(reader).getByAltText("Page 1 — Page 1").getAttribute("src")).toBe("/api/projects/demo/pages/1/renders/1/preview/reader");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(within(reader).getByText("End of book")).toBeTruthy();
    fireEvent.click(within(reader).getByRole("button", { name: "Back to edition" }));
    expect(screen.queryByRole("dialog", { name: "Book reader" })).toBeNull();
  });

  it("keeps a facing pair together and preserves its page when switching layouts", () => {
    drawnPages = [drawnPage(1), drawnPage(2, "left"), drawnPage(3, "right")];
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("slider", { name: "Jump to page" }).getAttribute("aria-valuetext")).toBe("Pages 2–3");
    fireEvent.click(screen.getByRole("button", { name: "SPREADS" }));
    expect(screen.getByRole("slider", { name: "Jump to page" }).getAttribute("aria-valuetext")).toBe("Page 2");
  });

  it("does not hijack keyboard input intended for the page slider", () => {
    drawnPages = [drawnPage(1), drawnPage(2), drawnPage(3)];
    renderRoom();
    fireEvent.click(screen.getByRole("button", { name: "Read your book" }));
    const slider = screen.getByRole("slider", { name: "Jump to page" });
    act(() => slider.focus());
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(slider.getAttribute("aria-valuetext")).toBe("Page 1");
    fireEvent.change(slider, { target: { value: "1" } });
    expect(slider.getAttribute("aria-valuetext")).toBe("Page 2");
  });
});
