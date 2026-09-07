import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  const actual = await importOriginal<typeof ApiClient>();
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
    characters: [{
      id: "char_1",
      name: "Elena",
      visual_anchor: "Silver-streaked dark hair",
      age_range: "40–50",
      gender: "female",
      distinguishing_features: ["Silver streak in dark hair"],
      baseline_affect: "Resolute",
      default_outfit: "Dark wool coat",
      relationships: [],
      first_appearance_scene: "scene_1",
      appearance_states: [],
    }],
    locations: [{
      id: "loc_1",
      name: "The Archive",
      visual_anchor: "Salt-stained stone stacks",
      time_of_day: "Night",
      mood: "Foreboding",
      appearance_states: [],
    }],
    scenes: [{
      id: "scene_1",
      chapter: 1,
      title: "The Locked Shelf",
      location_id: "loc_1",
      character_ids: ["char_1"],
      summary: "Elena finds the forbidden ledger.",
      scene_type: "discovery",
      narrative_beat: "The forbidden ledger reveals the investigation's next lead.",
      source_start_quote: "Elena opened the locked shelf.",
    }],
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
let statusError: ApiError | null;

function renderRoom() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    // Keep retryOnMount enabled: nested observers must not remount endlessly
    // between the room's loading and error states.
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
    statusError = null;
    mockedApiFetch.mockReset();
    mockedApiFetch.mockImplementation(
      (async (path: string) => {
        if (path === "/projects/demo/story") {
          if ("error" in storyResult) throw storyResult.error;
          return storyResult.data;
        }
        if (path === "/projects/demo/status") {
          if (statusError) throw statusError;
          return statusResult;
        }
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
      expect(screen.getByRole("button", { name: "Start Story analysis" })).toBeTruthy();
      expect(screen.queryByText("API 404: story not found")).toBeNull();
    });

    // Extract running: artifact still 404 — still progress, not a load error.
    // Transitions ride the status query (poll/cache) only — the story query
    // recovers through its readiness gate, never a manual invalidation.
    statusResult = projectStatus("running", "pending");
    await client.invalidateQueries({ queryKey: ["project", "demo", "status"] });

    await waitFor(() => {
      expect(screen.getByRole("progressbar")).toBeTruthy();
      expect(screen.queryByText("API 404: story not found")).toBeNull();
    });

    // Extract done, Brief running: artifact still 404 — still progress.
    statusResult = projectStatus("complete", "running");
    await client.invalidateQueries({ queryKey: ["project", "demo", "status"] });

    await waitFor(() => {
      expect(screen.getByRole("progressbar")).toBeTruthy();
      expect(screen.queryByText("API 404: story not found")).toBeNull();
    });

    // Brief ready and the artifact written: the editor appears on the same mount.
    storyResult = { data: storyFixture };
    statusResult = { ...projectStatus("complete", "awaiting_review"), is_running: false };
    await client.invalidateQueries({ queryKey: ["project", "demo", "status"] });

    expect(await screen.findByText("The Last Incantation")).toBeTruthy();
    expect(screen.getByText("The investigation closes its causal loop")).toBeTruthy();
  });

  it("keeps a genuine ready-stage 404 visible as COULD NOT LOAD", async () => {
    storyResult = { error: new ApiError(404, "story not found") };
    statusResult = { ...projectStatus("complete", "complete"), is_running: false };
    renderRoom();

    const error = await screen.findByText("API 404: story not found");
    const details = error.closest("details")!;
    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
  });

  it("exposes a status failure and recovers through the real status query without remounting", async () => {
    storyResult = { error: new ApiError(404, "story not found") };
    statusError = new ApiError(500, "status boom");
    const client = renderRoom();

    const error = await screen.findByText("API 500: status boom");
    const details = error.closest("details")!;
    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
    expect(screen.queryByRole("button", { name: "Start Story analysis" })).toBeNull();
    expect(screen.queryByText("API 404: story not found")).toBeNull();

    // A successful status refresh unlocks the artifact query on the same
    // mount, without a hook mock or manual story invalidation.
    statusError = null;
    statusResult = { ...projectStatus("complete", "awaiting_review"), is_running: false };
    storyResult = { data: storyFixture };
    await client.invalidateQueries({ queryKey: ["project", "demo", "status"] });

    expect(await screen.findByText("The Last Incantation")).toBeTruthy();
    expect(screen.getByText("The investigation closes its causal loop")).toBeTruthy();
    expect(screen.queryByText("API 500: status boom")).toBeNull();
  });

  it("surfaces the failed Brief error instead of a missing-artifact error", async () => {
    storyResult = { error: new ApiError(404, "story not found") };
    statusResult = projectStatus("complete", "failed", {
      error: "Brief run failed",
      error_detail: "traceback: boom",
    });
    renderRoom();

    expect(await screen.findByText("Brief run failed")).toBeTruthy();
    const details = screen.getByText("traceback: boom").closest("details")!;
    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
    expect(screen.getByRole("button", { name: "Retry stage" })).toBeTruthy();
    expect(screen.queryByText("API 404: story not found")).toBeNull();
  });

  it("keeps a real API failure actionable once the stage is ready", async () => {
    // The story query only runs once Brief is ready, so a non-404 failure
    // there must stay a load error — gating must not swallow it.
    storyResult = { error: new ApiError(500, "boom") };
    statusResult = { ...projectStatus("complete", "awaiting_review"), is_running: false };
    renderRoom();

    const error = await screen.findByText("API 500: boom");
    const details = error.closest("details")!;
    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
  });
});
