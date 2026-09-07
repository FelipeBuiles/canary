import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "../api/client";
import type * as ApiClient from "../api/client";
import { I18nProvider } from "../i18n";
import type { ProjectStatus, StageInfo, StageStatus, StoryDecision } from "../types/api";

// Network seam only: the real useStory / useProjectStatus hooks (and the real
// StoryRoom) run against controlled apiFetch responses. Nothing here echoes a
// mocked hook — a 404 below is the genuine pre-stage artifact state.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<ApiClient>();
  return { ...actual, apiFetch: vi.fn() };
});

const mockedApiFetch = vi.mocked(apiFetch);

import { StoryRoom } from "../pages/rooms/StoryRoom";

function stageInfo(status: StageStatus, overrides: Partial<StageInfo> = {}): StageInfo {
  return {
    status,
    items_done: 0,
    items_total: 0,
    items_failed: [],
    approved: null,
    cost_credits: 0,
    estimated_cost_credits: 0,
    error: null,
    error_detail: null,
    error_code: null,
    balance_credits: null,
    required_credits: null,
    shortfall_credits: null,
    started_at: null,
    finished_at: null,
    last_progress_at: null,
    stale: false,
    in_flight: [],
    ...overrides,
  };
}

function projectStatus(
  extract: StageStatus,
  brief: StageStatus,
  briefOverrides: Partial<StageInfo> = {},
): ProjectStatus {
  return {
    id: "demo",
    project_name: "demo",
    created_at: "2026-05-02T00:00:00Z",
    total_cost_credits: 0,
    misc_cost_credits: 0,
    total_estimated_cost_credits: 0,
    is_running: true,
    has_cover: false,
    style_selected: true,
    is_public: false,
    share_token: null,
    stages: {
      extract: stageInfo(extract),
      brief: stageInfo(brief, briefOverrides),
    },
  };
}

const storyFixture: StoryDecision = {
  story_bible: {
    title: "The Last Incantation",
    author: "H. P. Lovecraft",
    total_scenes: 1,
    characters: [{ id: "char_1", name: "Elena", visual_anchor: "Silver-streaked dark hair" }],
    locations: [{ id: "loc_1", name: "The Archive", visual_anchor: "Salt-stained stone stacks" }],
    scenes: [{ id: "scene_1", chapter: 1, title: "The Locked Shelf", summary: "Elena finds the forbidden ledger." }],
    narrative_arcs: [],
    style_notes: null,
    props: [],
  },
  brief: {
    revision: 3,
    content_sha256: "a".repeat(64),
    status: "draft",
    story_promises: ["The investigation closes its causal loop"],
    themes: ["Forbidden knowledge"],
    point_of_view: "Close third person",
    narrator_treatment: "Sparse captions",
    tone: "Mounting dread",
    ambiguities: [],
    motifs: ["Salt air"],
    protected_language: [],
    essential_events: ["The final discovery"],
    character_turns: ["Defiance becomes terror"],
    transformation_level: "medium_specific",
    desired_emphasis: ["The aftermath"],
    target_page_min: 22,
    target_page_max: 28,
  },
};

let storyResult: { data: StoryDecision } | { error: unknown };
let statusResult: ProjectStatus;

function renderRoom() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/project/demo/story"]}>
        <I18nProvider>
          <Routes>
            <Route path="/project/:id/story" element={<StoryRoom />} />
          </Routes>
        </I18nProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

describe("StoryRoom Extract background loading (regression)", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedApiFetch.mockImplementation(
      (async (path: string) => {
        if (path === "/projects/demo/story") {
          if ("error" in storyResult) throw storyResult.error;
          return storyResult.data;
        }
        if (path === "/projects/demo/status") return statusResult;
        if (path === "/credits/balance") return { balance_credits: 1000 };
        if (path.startsWith("/projects/demo/estimate")) {
          return {
            stage: "brief",
            estimate_credits: 0,
            reserved_credits: 0,
            reservation_multiplier: 1,
            confidence: "low_variance",
          };
        }
        throw new Error(`unexpected apiFetch path in test: ${path}`);
      }) as unknown as typeof apiFetch,
    );
  });
  it("shows stage progress — not COULD NOT LOAD — while Extract/Brief run, then shows the story without a refresh", async () => {
    // Genuine backend state for a new project: no story artifact yet (404 is
    // correct until the final write) while the stages are still working.
    storyResult = { error: new ApiError(404, "story not found") };
    statusResult = projectStatus("pending", "pending");
    const client = renderRoom();

    // Nothing has run yet — pending docket, not a load error.
    await waitFor(() => {
      expect(screen.getByText("WAITING IN THE PRODUCTION LINE")).toBeTruthy();
      expect(screen.queryByText("COULD NOT LOAD")).toBeNull();
    });

    // Extract running: artifact still 404 — still progress, not a load error.
    // Transitions ride the status query (poll/cache) only — the story query
    // recovers through its readiness gate, never a manual invalidation.
    statusResult = projectStatus("running", "pending");
    await client.invalidateQueries({ queryKey: ["project", "demo", "status"] });

    await waitFor(() => {
      expect(screen.getByText("RUNNING")).toBeTruthy();
      expect(screen.queryByText("COULD NOT LOAD")).toBeNull();
    });

    // Extract done, Brief running: artifact still 404 — still progress.
    statusResult = projectStatus("complete", "running");
    await client.invalidateQueries({ queryKey: ["project", "demo", "status"] });

    await waitFor(() => {
      expect(screen.getByText("RUNNING")).toBeTruthy();
      expect(screen.queryByText("COULD NOT LOAD")).toBeNull();
    });

    // Brief ready and the artifact written: the editor appears on the same mount.
    storyResult = { data: storyFixture };
    statusResult = { ...projectStatus("complete", "awaiting_review"), is_running: false };
    await client.invalidateQueries({ queryKey: ["project", "demo", "status"] });

    expect(await screen.findByText("CONFIRM THE STORY & BRIEF")).toBeTruthy();
    expect(screen.getByText("The Last Incantation")).toBeTruthy();
    expect(screen.getByText("The investigation closes its causal loop")).toBeTruthy();
    expect(screen.queryByText("COULD NOT LOAD")).toBeNull();
  });

  it("keeps a genuine ready-stage 404 visible as COULD NOT LOAD", async () => {
    storyResult = { error: new ApiError(404, "story not found") };
    statusResult = { ...projectStatus("complete", "complete"), is_running: false };
    renderRoom();

    expect(await screen.findByText("COULD NOT LOAD")).toBeTruthy();
    expect(screen.getByText("ERROR DETAILS")).toBeTruthy();
    expect(screen.getByText("API 404: story not found")).toBeTruthy();
  });

  it("surfaces a genuine status failure instead of hiding it behind the gate", async () => {
    storyResult = { error: new ApiError(404, "story not found") };
    mockedApiFetch.mockImplementation(
      (async (path: string) => {
        if (path === "/projects/demo/status") throw new ApiError(500, "status boom");
        if (path === "/credits/balance") return { balance_credits: 1000 };
        throw new Error(`unexpected apiFetch path in test: ${path}`);
      }) as unknown as typeof apiFetch,
    );
    const client = renderRoom();
    await waitFor(() => {
      const s = client.getQueryState(["project", "demo", "status"]);
      console.log(
        "PROBE status=",
        s?.status,
        "fetch=",
        s?.fetchStatus,
        "failures=",
        s?.failureCount,
        "fetchFailures=",
        s?.fetchFailureCount,
        "err=",
        s?.error ? String(s.error) : null,
        "ncalls=",
        mockedApiFetch.mock.calls.length,
      );
      expect(s?.status).not.toBe("pending");
    });

    expect(await screen.findByText("COULD NOT LOAD")).toBeTruthy();
    expect(screen.getByText("ERROR DETAILS")).toBeTruthy();
    expect(screen.getByText("API 500: status boom")).toBeTruthy();
  });

  it("surfaces the failed Brief error instead of a missing-artifact error", async () => {
    storyResult = { error: new ApiError(404, "story not found") };
    statusResult = projectStatus("complete", "failed", {
      error: "Brief run failed",
      error_detail: "traceback: boom",
    });
    renderRoom();

    expect(await screen.findByText("PRESS STOPPED")).toBeTruthy();
    expect(screen.getByText("Brief run failed")).toBeTruthy();
    expect(screen.getByText("TECHNICAL DETAILS")).toBeTruthy();
    expect(screen.getByText("traceback: boom")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry stage" })).toBeTruthy();
    expect(screen.queryByText("COULD NOT LOAD")).toBeNull();
  });

  it("keeps a real API failure actionable once the stage is ready", async () => {
    // The story query only runs once Brief is ready, so a non-404 failure
    // there must stay a load error — gating must not swallow it.
    storyResult = { error: new ApiError(500, "boom") };
    statusResult = { ...projectStatus("complete", "awaiting_review"), is_running: false };
    renderRoom();

    expect(await screen.findByText("COULD NOT LOAD")).toBeTruthy();
    expect(screen.getByText("ERROR DETAILS")).toBeTruthy();
    expect(screen.getByText("API 500: boom")).toBeTruthy();
  });
});
