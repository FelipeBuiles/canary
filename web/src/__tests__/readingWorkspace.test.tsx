import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { GenerationJob, ProjectStatus } from "../types/api";

const mocks = vi.hoisted(() => ({ adaptation: vi.fn(), plan: vi.fn(), pages: vi.fn(), bible: vi.fn(() => ({ data: undefined })), refetch: vi.fn(), credits: vi.fn() }));
vi.mock("../api/queries", () => ({ useAdaptation: mocks.adaptation, useBookPlan: mocks.plan, useCompletePages: mocks.pages, useStoryBible: mocks.bible }));
vi.mock("../hooks/useNeedsCredits", () => ({ useNeedsCredits: mocks.credits }));
import { ReadingWorkspace } from "../components/pages/ReadingWorkspace";
import { StagePlaceholder } from "../components/composites/StagePlaceholder";
const queued = { kind: "pipeline_stage", stage: "adapt", payload: {}, status: "queued" } as GenerationJob;
const cover = { kind: "project_cover", status: "running" } as GenerationJob;
function status(stageStatus = "pending", jobs: GenerationJob[] = []): ProjectStatus {
  return { stages: { adapt: { status: stageStatus }, plan: { status: stageStatus } }, active_jobs: jobs } as unknown as ProjectStatus;
}
function tree(projectStatus: ProjectStatus, kind: "adaptation" | "page-plan" = "adaptation") {
  return <I18nProvider><ReadingWorkspace project="demo" kind={kind} status={projectStatus} onClose={vi.fn()} onKindChange={vi.fn()} /></I18nProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  // A stale 404 must be ignored for disabled queries while generating.
  for (const query of [mocks.adaptation, mocks.plan, mocks.pages]) query.mockReturnValue({ error: new Error("404"), refetch: mocks.refetch });
});
describe("documents before generation", () => {
  it.each(["adaptation", "page-plan"] as const)("does not request an ungenerated %s or present a retry error", (kind) => {
    render(tree(status(), kind));
    expect(mocks.adaptation).not.toHaveBeenCalled();
    expect(mocks.plan).not.toHaveBeenCalled();
    expect(mocks.pages).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(screen.queryByRole("region")).toBeNull();
  });
  it.each(["adaptation", "page-plan"] as const)("keeps the %s view locked during a cover wait", (kind) => {
    render(tree(status("pending", [queued, cover]), kind));
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("enables the document after completion and preserves genuine read errors", () => {
    const view = render(tree(status()));
    view.rerender(tree(status("complete")));
    expect(mocks.adaptation).toHaveBeenLastCalledWith("demo");
    expect(screen.getByRole("alert").textContent).toContain("could not be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.refetch).toHaveBeenCalledOnce();
  });
  it("keeps failed document generation locked", () => {
    render(tree(status("failed")));
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("locks the Page plan tab while adaptation is readable but planning is unfinished", () => {
    const project = status("complete");
    project.stages.plan.status = "running";
    render(tree(project));
    expect(screen.getByRole("button", { name: "Page plan" })).toHaveProperty("disabled", true);
  });
  it("suppresses credit gates and start/retry controls while already queued", () => {
    render(<I18nProvider><StagePlaceholder project="demo" stage="adapt" status="failed" activeJobs={[queued, cover]} allowPendingStart /></I18nProvider>);
    expect(screen.getByText("Your cover is being drawn")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(mocks.credits).not.toHaveBeenCalled();
  });
});
