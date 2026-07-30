import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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

vi.mock("../api/queries", () => ({
  useProjects: () => projectsResult,
  useCreateProject: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useImportStory: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useRunPipeline: () => ({ mutate: vi.fn() }),
  useGenerateProjectCover: () => generateCoverMutation,
  useDeleteProject: () => deleteProjectMutation,
}));

import { Library } from "../pages/Library";

function renderLibrary() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <I18nProvider>
          <Library />
        </I18nProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Library first-run (Issue #0)", () => {
  beforeEach(() => {
    generateCoverMutation.mutate.mockReset();
    generateCoverMutation.isPending = false;
    generateCoverMutation.variables = undefined;
    deleteProjectMutation.mutate.mockReset();
    deleteProjectMutation.isPending = false;
    deleteProjectMutation.variables = undefined;
  });

  it("shows the first-issue invitation with the 4-station teaching strip", () => {
    projectsResult.data = [];
    renderLibrary();

    expect(screen.getByText("ISSUE #0")).toBeTruthy();
    expect(screen.getByText("Every production starts with a manuscript.")).toBeTruthy();
    expect(screen.getByText("THE PRODUCTION LINE")).toBeTruthy();
    // The 4 stations render as a teaching strip.
    expect(screen.getByText("Story")).toBeTruthy();
    expect(screen.getByText("Look")).toBeTruthy();
    expect(screen.getByText("Pages")).toBeTruthy();
    expect(screen.getByText("Book")).toBeTruthy();
    expect(screen.getByRole("button", { name: "START NEW PROJECT" })).toBeTruthy();
    // The Studio Telemetry widget no longer exists anywhere.
    expect(screen.queryByText("ARCHIVE FILES")).toBeNull();
    expect(screen.queryByText("Studio telemetry")).toBeNull();
  });

  it("leaves non-empty libraries untouched", () => {
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

    expect(screen.queryByText("ISSUE #0")).toBeNull();
    // No telemetry widget for non-empty libraries either.
    expect(screen.queryByText("ARCHIVE FILES")).toBeNull();
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
