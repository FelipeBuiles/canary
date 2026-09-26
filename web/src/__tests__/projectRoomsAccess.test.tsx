import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectStatus } from "../types/api";
import { I18nProvider } from "../i18n";

const mocks = vi.hoisted(() => ({ status: undefined as ProjectStatus | undefined, error: null as Error | null, refetch: vi.fn(), mount: vi.fn() }));
vi.mock("../api/queries", () => ({ useProjectStatus: () => ({ data: mocks.status, error: mocks.error, refetch: mocks.refetch }) }));
vi.mock("../hooks/useSSE", () => ({ useSSE: vi.fn() }));
vi.mock("../api/events", () => ({ trackProductEvent: vi.fn() }));
import { ProjectRooms } from "../layout/ProjectRooms";

function ProtectedRoom() { mocks.mount(); return <p>Room content</p>; }
function tree(route = "pages") {
  return <I18nProvider><MemoryRouter initialEntries={[`/project/demo/${route}`]}><Routes>
    <Route path="/project/:id" element={<ProjectRooms />}>
      <Route path="pages" element={<ProtectedRoom />} />
      <Route path="book" element={<ProtectedRoom />} />
      <Route path="story" element={<p>Story recovery</p>} />
      <Route path="settings" element={<p>Project settings</p>} />
    </Route>
  </Routes></MemoryRouter></I18nProvider>;
}

beforeEach(() => { vi.clearAllMocks(); mocks.status = undefined; mocks.error = null; });
describe("ProjectRooms access boundary", () => {
  it("does not mount room data consumers while loading or on a status error", () => {
    const view = render(tree());
    expect(screen.getByRole("status").textContent).toContain("Checking project progress");
    expect(mocks.mount).not.toHaveBeenCalled();
    mocks.error = new Error("Offline");
    view.rerender(tree());
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.refetch).toHaveBeenCalledOnce();
    expect(mocks.mount).not.toHaveBeenCalled();
  });

  it.each(["pages", "book"])("guards a direct %s URL and links to the accessible recovery room", (route) => {
    mocks.status = { stages: {}, style_selected: false } as ProjectStatus;
    render(tree(route));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Coming up:");
    expect(mocks.mount).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("link", { name: "Continue in Story" }));
    expect(screen.getByText("Story recovery")).toBeTruthy();
  });

  it("unlocks automatically on fresh progress and relocks on invalidation", () => {
    mocks.status = { stages: {}, style_selected: false } as ProjectStatus;
    const view = render(tree());
    mocks.status = { style_selected: true, stages: Object.fromEntries(["extract", "brief", "style", "cast"].map((stage) => [stage, { status: "complete", approved: true }])) } as ProjectStatus;
    view.rerender(tree());
    expect(screen.getByText("Room content")).toBeTruthy();
    mocks.status.stages.brief.status = "awaiting_review";
    view.rerender(tree());
    expect(screen.queryByText("Room content")).toBeNull();
    expect(screen.getByText("Review and approve your story brief.")).toBeTruthy();
  });

  it("keeps settings available during a status failure", () => {
    mocks.error = new Error("Offline");
    render(tree("settings"));
    expect(screen.getByText("Project settings")).toBeTruthy();
  });
});
