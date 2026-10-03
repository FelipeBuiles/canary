import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectSummary } from "../types/api";
import { I18nProvider } from "../i18n";

const projectsResult: { data: ProjectSummary[]; isLoading: boolean; error: null; refetch: () => void } = {
  data: [],
  isLoading: false,
  error: null,
  refetch: vi.fn(),
};
const generateCoverMutation = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined as { project: string } | undefined,
};
const deleteProjectMutation = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined as { id: string } | undefined,
};

const runPipeline = vi.fn();
const createProjectMutation = { mutate: vi.fn(), isPending: false, error: null };
const importStoryMutation = { mutate: vi.fn(), isPending: false, error: null };
vi.mock("../api/queries", () => ({
  useProjects: () => projectsResult,
  useCreateProject: () => createProjectMutation,
  useImportStory: () => importStoryMutation,
  useRunPipeline: () => ({ mutate: runPipeline }),
  useShortStories: () => ({ data: [], isLoading: false, isError: false, refetch: vi.fn() }),
  useGenerateProjectCover: () => generateCoverMutation,
  useDeleteProject: () => deleteProjectMutation,
}));

import { Library } from "../pages/Library";

function LocationProbe() {
  return <output aria-label="Current route">{useLocation().pathname}</output>;
}
function renderLibrary() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <I18nProvider>
          <Library />
          <LocationProbe />
        </I18nProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Library first-run (Issue #0)", () => {
  beforeEach(() => {
    runPipeline.mockReset();
    createProjectMutation.mutate.mockReset();
    importStoryMutation.mutate.mockReset();
    generateCoverMutation.mutate.mockReset();
    generateCoverMutation.isPending = false;
    generateCoverMutation.variables = undefined;
    deleteProjectMutation.mutate.mockReset();
    deleteProjectMutation.isPending = false;
    deleteProjectMutation.variables = undefined;
  });

  it("offers one creation entry with a public generated page and contains keyboard focus", async () => {
    const user = userEvent.setup();
    projectsResult.data = [];
    renderLibrary();
    expect(screen.getByRole("img", { name: /Generated comic page/ }).getAttribute("src")).toBe("/marketing/elm-and-keep-page-12.webp");
    const opener = screen.getByRole("button", { name: "NEW PRODUCTION" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    for (let index = 0; index < 12; index += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("creates a source-only project and leaves generation for the Story decision", async () => {
    const user = userEvent.setup();
    projectsResult.data = [];
    importStoryMutation.mutate.mockImplementation((_input, options) => options.onSuccess({ id: "prepared-source" }));
    renderLibrary();
    await user.click(screen.getByRole("button", { name: "NEW PRODUCTION" }));
    await user.click(screen.getByText("HAVE A STORY CODE OR LINK?"));
    await user.type(screen.getByLabelText("Library of Short Stories code or URL"), "the-open-window");
    await user.click(screen.getByRole("button", { name: "CONTINUE" }));
    await user.click(screen.getByRole("button", { name: "CONTINUE" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "CREATE PROJECT" }));
    expect(importStoryMutation.mutate).toHaveBeenCalledOnce();
    expect(runPipeline).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Current route").textContent).toBe("/project/prepared-source/story");
  });

  it("opens the first part after uploading a book with several parts", async () => {
    const user = userEvent.setup();
    projectsResult.data = [];
    createProjectMutation.mutate.mockImplementation((_input, options) => options.onSuccess({ id: "full-book", part_id: "part_0001" }));
    const view = renderLibrary();
    await user.click(screen.getByRole("button", { name: "NEW PRODUCTION" }));
    await user.click(screen.getByRole("button", { name: "UPLOAD MANUSCRIPT" }));
    await user.upload(view.container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(["Book"], "book.txt", { type: "text/plain" }));
    await user.click(screen.getByRole("button", { name: "CONTINUE" }));
    await user.click(screen.getByRole("button", { name: "CONTINUE" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "CREATE PROJECT" }));

    expect(runPipeline).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Current route").textContent).toBe("/project/full-book~part_0001/story");
  });

  it("finds productions by title or author and recovers from an empty search", async () => {
    const user = userEvent.setup();
    projectsResult.data = [
      { id: "one", name: "one", project_name: "The Open Window", author: "Saki", created_at: "2026-06-01", furthest_stage: "extract", is_running: false, has_cover: false, cover_job: null, total_cost_credits: 0 },
      { id: "two", name: "two", project_name: "Dracula", author: "Bram Stoker", created_at: "2026-06-01", furthest_stage: "style", is_running: false, has_cover: false, cover_job: null, total_cost_credits: 0 },
    ];
    renderLibrary();
    const search = screen.getByRole("searchbox", { name: "Find a production" });
    await user.type(search, " SAKI ");
    expect(screen.getByText("The Open Window")).toBeTruthy();
    expect(screen.queryByText("Dracula")).toBeNull();
    await user.clear(search);
    await user.type(search, "missing");
    expect(screen.getByText("No matching productions")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByText("Dracula")).toBeTruthy();
    expect(generateCoverMutation.mutate).not.toHaveBeenCalled();
  });

  it("shows existing productions without generating covers", () => {
    projectsResult.data = [
      {
        id: "demo",
        project_name: "Demo",
        author: null,
        created_at: "2026-06-01T00:00:00Z",
        furthest_stage: "extract",
        is_running: false,
        has_cover: false,
        cover_job: null,
        total_cost_credits: 0,
      } as unknown as ProjectSummary,
    ];
    renderLibrary();

    expect(screen.queryByRole("img", { name: /Generated comic page/ })).toBeNull();
    expect(screen.getByText("Demo")).toBeTruthy();
    expect(generateCoverMutation.mutate).not.toHaveBeenCalled();
  });

  it("labels active cover work and offers a retry after failure", async () => {
    const user = userEvent.setup();
    const project = {
      id: "demo",
      project_name: "Demo",
      author: null,
      created_at: "2026-06-01T00:00:00Z",
      furthest_stage: "style",
      is_running: false,
      has_cover: false,
      total_cost_credits: 0,
    };

    projectsResult.data = [{
      ...project,
      cover_job: { status: "running" },
    } as unknown as ProjectSummary];
    const view = renderLibrary();
    expect(screen.getByText("DRAWING COVER…")).toBeTruthy();

    projectsResult.data = [{
      ...project,
      cover_job: { status: "failed" },
    } as unknown as ProjectSummary];
    view.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <I18nProvider>
            <Library />
          </I18nProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "COVER FAILED — RETRY" }));
    expect(generateCoverMutation.mutate).toHaveBeenCalledWith(
      { project: "demo" },
      expect.objectContaining({ onError: expect.any(Function) }),
    );
  });

  it("offers a recovery delete for an incompatible project", async () => {
    const user = userEvent.setup();
    projectsResult.data = [{
      id: "legacy-id",
      project_name: "Old Book",
      author: null,
      created_at: "2026-06-01T00:00:00Z",
      furthest_stage: null,
      is_running: false,
      has_cover: false,
      cover_job: null,
      total_cost_credits: 0,
      incompatible: true,
    } as unknown as ProjectSummary];

    renderLibrary();

    expect(screen.getByText("Needs reset")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "REMOVE OLD PROJECT" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toBeTruthy();
    await user.type(screen.getByPlaceholderText("Old Book"), "Old Book");
    await user.click(within(dialog).getByRole("button", { name: "REMOVE OLD PROJECT" }));

    expect(deleteProjectMutation.mutate).toHaveBeenCalledWith(
      { id: "legacy-id" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });
});
