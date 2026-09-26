import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "../api/client";
import type * as ApiClient from "../api/client";
import { I18nProvider } from "../i18n";
import { StagePlaceholder } from "../components/composites/StagePlaceholder";
import { ProjectRooms } from "../layout/ProjectRooms";

vi.mock("../api/client", async (original) => ({ ...await original<typeof ApiClient>(), apiFetch: vi.fn() }));
vi.mock("../hooks/useSSE", () => ({ useSSE: vi.fn() }));
const fetchMock = vi.mocked(apiFetch);
let missing: boolean;
let overrides: Record<string, string>;
let saveError: boolean;
let finishSave: (() => void) | undefined;
let holdSave: boolean;
let finishEstimate: (() => void) | undefined;
let holdEstimate: boolean;

beforeEach(() => {
  missing = false;
  overrides = { extract: "first", draw: "artist" };
  saveError = false;
  holdSave = false;
  holdEstimate = false;
  finishSave = undefined;
  finishEstimate = undefined;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (path, options) => {
    if (path.endsWith("/status")) {
      if (missing) throw new ApiError(404, "Project not found");
      return { id: "demo", is_running: false, stages: { extract: { status: "failed" } } };
    }
    if (path === "/credits/balance") return { balance_credits: 1000 };
    if (path.includes("/estimate")) {
      if (holdEstimate) await new Promise<void>((resolve) => { finishEstimate = resolve; });
      return { stage: "extract", estimate_credits: overrides.extract === "second" ? 25 : 12, reserved_credits: 30 };
    }
    if (path.endsWith("/config/")) {
      if (options?.method === "PATCH") {
        if (holdSave) await new Promise<void>((resolve) => { finishSave = resolve; });
        if (saveError) throw new ApiError(503, "Settings could not be saved");
        overrides = JSON.parse(options.body as string).dev_model_selections;
      }
      return { dev_model_selections: overrides };
    }
    if (path === "/account/model-settings") return {
      enabled: true, selections: { extract: "first" },
      stages: [{ id: "extract", label: "1. Extract", model_ids: ["first", "second"] }, { id: "draw", label: "7. Draw", model_ids: ["artist"] }],
      models: ["first", "second", "artist"].map((id) => ({ id, label: id, provider: "test", funding: "api" })),
    };
    if (path === "/events") return {};
    if (path.includes("/run")) throw new ApiError(503, "Test stops before generation");
    throw new Error(`Unexpected request: ${path}`);
  });
});

function setup(element: React.ReactNode, { route = "/project/demo/story", guarded = false, cached = false } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (cached) client.setQueryData(["project", "demo", "status"], { id: "demo", is_running: false, stages: {} });
  render(<QueryClientProvider client={client}><I18nProvider><MemoryRouter initialEntries={[route]}><Routes>
    <Route path="/" element={<p>Project library</p>} />
    {guarded ? <Route path="/project/:id" element={<ProjectRooms />}>
      <Route path="story" element={element} /><Route path="settings" element={element} />
    </Route> : <Route path="/project/:id/story" element={element} />}
  </Routes></MemoryRouter></I18nProvider></QueryClientProvider>);
  return client;
}
const recovery = <StagePlaceholder project="demo" stage="extract" status="failed" errorCode="model_refusal" error="Provider declined" />;

describe("Extraction refusal recovery", () => {
  it("explains a saved stale-hold error as billing maintenance, not a model refusal", async () => {
    setup(<StagePlaceholder project="demo" stage="extract" status="failed" error="{'message': 'Expired credit reservation requires reconciliation', 'code': 'P0001'}" />);
    expect(screen.getByText("Credit hold needs attention")).toBeTruthy();
    expect(screen.getByText("An earlier credit hold is blocking new work. No model request was started.")).toBeTruthy();
    await screen.findByRole("combobox", { name: "1. Extract" });
    expect(screen.queryByText("Model declined this content")).toBeNull();
  });
  it("saves just the extraction choice, refreshes the estimate, and waits for explicit retry", async () => {
    holdSave = true;
    setup(recovery);
    const select = await screen.findByRole("combobox", { name: "1. Extract" });
    expect(screen.queryByRole("combobox", { name: "7. Draw" })).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry stage" })).toHaveProperty("disabled", false));
    fireEvent.click(screen.getByRole("button", { name: "Retry stage" }));
    fireEvent.change(select, { target: { value: "second" } });
    await waitFor(() => expect(finishSave).toBeTypeOf("function"));
    expect(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Starting…" })).toHaveProperty("disabled", true);
    holdEstimate = true;
    await act(async () => finishSave!());
    await waitFor(() => expect(finishEstimate).toBeTypeOf("function"));
    expect(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Starting…" })).toHaveProperty("disabled", true);
    holdEstimate = false;
    await act(async () => finishEstimate!());
    await screen.findByText("Settings saved.");
    expect(overrides).toEqual({ extract: "second", draw: "artist" });
    expect(within(screen.getByRole("alertdialog")).getByLabelText("about 25 credits")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path]) => path.includes("/run"))).toBe(false);
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Retry stage" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/projects/demo/run?stage=extract", { method: "POST" }));
  });

  it("keeps retry disabled after a failed model save and permits recovery", async () => {
    saveError = true;
    setup(recovery);
    const select = await screen.findByRole("combobox", { name: "1. Extract" });
    fireEvent.change(select, { target: { value: "second" } });
    await screen.findByText("API 503: Settings could not be saved");
    expect(screen.getByRole("button", { name: "Retry stage" })).toHaveProperty("disabled", true);
    expect(select).toHaveProperty("value", "first");
    saveError = false;
    fireEvent.change(select, { target: { value: "second" } });
    await screen.findByText("Settings saved.");
    expect(screen.getByRole("button", { name: "Retry stage" })).toHaveProperty("disabled", false);
  });
});

describe("Missing project routing", () => {
  it.each(["story", "settings"])("redirects a deleted project's %s route even with fresh cached data", async (room) => {
    missing = true;
    setup(<p>Project content</p>, { guarded: true, cached: true, route: `/project/demo/${room}` });
    expect(await screen.findByText("Project library")).toBeTruthy();
    expect(screen.queryByText("Project content")).toBeNull();
  });

  it("revalidates on tab focus and leaves the deleted project", async () => {
    setup(<p>Project content</p>, { guarded: true });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/projects/demo/status"));
    await act(async () => focusManager.setFocused(false));
    missing = true;
    await act(async () => focusManager.setFocused(true));
    expect(await screen.findByText("Project library")).toBeTruthy();
    focusManager.setFocused(undefined);
  });

  it("shows a retry state without redirecting for a server error", async () => {
    fetchMock.mockRejectedValue(new ApiError(500, "Server unavailable"));
    const client = setup(<p>Project content</p>, { guarded: true });
    await waitFor(() => expect(client.getQueryState(["project", "demo", "status"])?.status).toBe("error"));
    expect(screen.getByText("Could not check station availability")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByText("Project content")).toBeNull();
    expect(screen.queryByText("Project library")).toBeNull();
  });
});
