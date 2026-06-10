import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ProjectSummary } from "../types/api";
import { I18nProvider } from "../i18n";

const projectsResult: { data: ProjectSummary[]; isLoading: boolean; error: null; refetch: () => void } = {
  data: [],
  isLoading: false,
  error: null,
  refetch: vi.fn(),
};

vi.mock("../api/queries", () => ({
  useProjects: () => projectsResult,
  useCreateProject: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useImportStory: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useRunPipeline: () => ({ mutate: vi.fn() }),
  useGenerateProjectCover: () => ({ mutate: vi.fn() }),
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
  it("replaces telemetry zeros and the bare card with the first-issue invitation", () => {
    projectsResult.data = [];
    renderLibrary();

    expect(screen.getByText("AWAITING FIRST PRODUCTION")).toBeTruthy();
    expect(screen.getByText("ISSUE #0")).toBeTruthy();
    expect(screen.getByText("Every production starts with a manuscript.")).toBeTruthy();
    expect(screen.getByText("THE PRODUCTION LINE")).toBeTruthy();
    // The 8 UI stages render as a teaching strip.
    expect(screen.getByText("Extract")).toBeTruthy();
    expect(screen.getByText("Letter & Compose")).toBeTruthy();
    expect(screen.getByRole("button", { name: "START NEW PROJECT" })).toBeTruthy();
    // Telemetry zeros are gone.
    expect(screen.queryByText("ARCHIVE FILES")).toBeNull();
  });

  it("leaves non-empty libraries untouched", () => {
    projectsResult.data = [
      {
        id: "demo",
        project_name: "Demo",
        author: null,
        created_at: "2026-06-01T00:00:00Z",
        furthest_stage: null,
        is_running: false,
        has_cover: false,
        cover_job: null,
        total_cost_credits: 0,
      } as unknown as ProjectSummary,
    ];
    renderLibrary();

    expect(screen.queryByText("ISSUE #0")).toBeNull();
    expect(screen.queryByText("AWAITING FIRST PRODUCTION")).toBeNull();
    expect(screen.getByText("ARCHIVE FILES")).toBeTruthy();
    expect(screen.getByText("Demo")).toBeTruthy();
  });
});
