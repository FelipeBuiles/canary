import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render as renderWithoutQueries, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { GenerationJob } from "../types/api";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { StyleRoom } from "../pages/rooms/StyleRoom";
import { I18nProvider } from "../i18n";

const state = vi.hoisted(() => {
  const mutate = vi.fn();
  const mutation = { mutate, mutateAsync: (variables: unknown) => new Promise((resolve, reject) => mutate(variables, { onSuccess: resolve, onError: reject })), isPending: false };
  const emptyQuery = () => ({ data: undefined });
  return { mutation, emptyQuery, estimateError: null as Error | null, retryEstimate: vi.fn(), labels: ["Ink", "Watercolor", "Noir", "Graphic"],
    jobs: [] as GenerationJob[], castStatus: undefined as string | undefined, handleRun: vi.fn(), generateCover: vi.fn(),
    presentation: { mutate: vi.fn(), isPending: false }, suggestions: undefined as Array<Record<string, unknown>> | undefined,
    stylesMeta: {} as Record<string, boolean> };
});
vi.mock("../api/queries", () => ({
  useStyles: () => ({ data: { ...state.stylesMeta, suggestions: state.suggestions ?? state.labels.map((label, index) => ({
    id: label, index, label, origin: "generated", template: `Full ${label} direction`, has_sample: true, is_active: false,
  })) }, refetch: vi.fn(), isLoading: false, isError: false }),
  useProjectConfig: state.emptyQuery, useStoryBible: state.emptyQuery,
  useProjectStatus: () => ({ data: state.castStatus ? { style_selected: true, has_cover: false,
    stages: { style: { status: "complete" }, cast: { status: state.castStatus } } } : undefined }), useGenerationJobs: () => ({ data: { jobs: state.jobs } }),
  useSuggestStylesEstimate: () => ({ error: state.estimateError, refetch: state.retryEstimate }), useStyleDirectionEstimate: () => ({ refetch: vi.fn() }),
  useStyleSampleEstimate: state.emptyQuery, useStageEstimate: () => ({ data: { estimate_credits: 25 } }),
  useProjectCoverEstimate: state.emptyQuery, useProjects: state.emptyQuery,
  useImageGenerationMeta: state.emptyQuery,
  useSuggestStyles: () => state.mutation, useCreateStyleDirection: () => state.mutation,
  useGenerateStyleSamples: () => state.mutation, useGenerateStyleValidation: () => state.mutation,
  useApproveStage: () => state.mutation, useGenerateProjectCover: () => ({ mutate: state.generateCover, mutateAsync: (variables: unknown) => { state.generateCover(variables); return Promise.resolve({}); } }),
  useSetActiveStyle: () => state.mutation, useUpdateStylePresentation: () => state.presentation,
}));
vi.mock("../hooks/useRunAction", () => ({ useRunAction: () => ({ handleRun: state.handleRun, isPending: false }) }));
vi.mock("../components/composites", async (importOriginal) => ({
  ...await importOriginal<object>(),
  RoomShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
  RoomHeader: ({ actions }: { actions: ReactNode }) => <header>{actions}</header>,
  ApprovalBar: ({ onPrimary, primaryDisabled, estimateCredits }: { onPrimary: () => void; primaryDisabled: boolean; estimateCredits: number }) =>
    <button disabled={primaryDisabled} onClick={onPrimary}>Continue for {estimateCredits}</button>,
  ConfirmDrawer: ({ open, title, confirmLabel, onConfirm }: { open: boolean; title: string; confirmLabel: string; onConfirm: () => void }) =>
    open ? <div role="dialog" aria-label={title}><button onClick={onConfirm}>{confirmLabel}</button></div> : null,
  RerunStageAction: () => null,
}));

function render(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return renderWithoutQueries(ui, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

const room = () => <I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
  <Route path="/projects/:id/style" element={<StyleRoom />} />
  <Route path="/project/:id/cast" element={<p>Cast room</p>} />
</Routes></MemoryRouter></I18nProvider>;

function strip() {
  return within(screen.getByRole("list", { name: "All proofs" }));
}

async function open(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.click(strip().getByRole("button", { name: label }));
}

describe("StyleRoom comparison", () => {
  it("guides the first addition, keeps three choices without eviction, and allows replacement after removal", async () => {
    const user = userEvent.setup();
    const view = render(room());
    await user.click(screen.getByRole("button", { name: "Compare · Ink" }));
    expect(screen.getByRole("button", { name: "Compare · add one more" })).toHaveProperty("disabled", true);
    expect(screen.queryByRole("region", { name: "Compare proofs" })).toBeNull();
    await open(user, "Watercolor");
    await user.click(screen.getByRole("button", { name: "Compare · Watercolor" }));
    await open(user, "Noir");
    await user.click(screen.getByRole("button", { name: "Compare · Noir" }));
    await open(user, "Graphic");
    const fourth = screen.getByRole("button", { name: "Compare · Graphic" });
    expect(fourth).toHaveProperty("disabled", true);
    await user.click(fourth);
    await user.click(screen.getByRole("button", { name: "Compare 3" }));
    const comparison = within(screen.getByRole("region", { name: "Compare proofs" }));
    for (const label of ["Ink", "Watercolor", "Noir"]) {
      expect(comparison.getByRole("button", { name: `Remove from comparison · ${label}` })).toBeTruthy();
    }
    await user.click(comparison.getByRole("button", { name: "Remove from comparison · Watercolor" }));
    expect(screen.queryByRole("button", { name: "Remove from comparison · Watercolor" })).toBeNull();
    await open(user, "Graphic");
    await user.click(screen.getByRole("button", { name: "Compare · Graphic" }));
    await user.click(screen.getByRole("button", { name: "Compare 3" }));
    expect(screen.getByRole("button", { name: "Remove from comparison · Graphic" })).toBeTruthy();
    state.labels = ["Etching", "Pastel", "Woodcut"];
    view.rerender(room());
    expect(screen.queryByRole("region", { name: "Compare proofs" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Compare · Etching" }));
    expect(screen.getByRole("button", { name: "Compare · add one more" })).toBeTruthy();
    expect(state.mutation.mutate).not.toHaveBeenCalled();
  });
});

it("shows estimate failures with a retry instead of claiming generation is running", async () => {
  state.labels = [];
  state.estimateError = new Error("A job cannot mix API-funded and Codex-subscription operations");
  render(room());
  expect(screen.getByRole("alert").textContent).toContain(state.estimateError.message);
  expect(screen.queryByText("Preparing directions…")).toBeNull();
  expect(screen.getByRole("button", { name: "Create six directions" })).toHaveProperty("disabled", true);
  await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
  expect(state.retryEstimate).toHaveBeenCalledOnce();
  expect(state.mutation.mutate).not.toHaveBeenCalled();
});

it("starts Cast with its bundled cover estimate without requesting a cover before references exist", async () => {
  state.castStatus = "pending";
  state.estimateError = null;
  render(room());
  await userEvent.setup().click(screen.getByRole("button", { name: "Continue for 25" }));
  expect(state.handleRun).toHaveBeenCalledWith("book", "cast", { actionLabel: "Cast characters & places" });
  expect(state.generateCover).not.toHaveBeenCalled();
  expect(screen.getByText("Cast room")).toBeTruthy();
  state.castStatus = undefined;
});

it("shows every proof in the strip and the sheet, with one selection action for the proof on the stage", async () => {
  state.labels = ["Ink", "Watercolor", "Noir", "Graphic", "Caricature", "Paper"];
  state.estimateError = null;
  state.castStatus = undefined;
  const user = userEvent.setup();
  render(room());
  expect(strip().getAllByRole("button", { name: /Ink|Watercolor|Noir|Graphic|Caricature|Paper/ })).toHaveLength(6);
  expect(screen.getAllByRole("button", { name: "Use this style" })).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Sheet" }));
  const sheet = screen.getByTestId("style-proof-grid");
  expect(within(sheet).getAllByRole("heading", { level: 3 })).toHaveLength(6);
  await user.click(within(sheet).getByRole("button", { name: "Open Noir" }));
  expect(screen.getByRole("group", { name: "Noir, 3 / 6" })).toBeTruthy();
});

it("restores a saved proof when a model change replaces a failed cached preview URL", async () => {
  state.estimateError = null;
  state.suggestions = Array.from({ length: 6 }, (_, index) => ({
    id: `style-${index}`, index: index + 1, label: `Look ${index + 1}`, origin: "generated",
    template: "Ink", has_sample: true, sample_stale: false, is_active: false,
    sample_preview_url: `/api/projects/book/styles/style-${index}/proof/sample?style=current`,
  }));
  const view = render(room());
  await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 0)); });
  fireEvent.error(screen.getByRole("img", { name: "Look 1" }));
  expect(screen.getByText("Proof image unavailable")).toBeTruthy();

  state.suggestions = state.suggestions.map((item) => ({ ...item, sample_preview_url: null, sample_stale: true }));
  view.rerender(room());
  expect(screen.queryByText("Proof image unavailable")).toBeNull();
  expect(screen.getByRole("img", { name: "Look 1" }).getAttribute("src")).toContain("/files/samples/style_1.png?t=");
  expect(screen.getByRole("button", { name: "Use this style" })).toHaveProperty("disabled", false);
  expect(screen.getByRole("button", { name: "Refresh all (6)" })).toBeTruthy();
  state.suggestions = undefined;
});

it("does not surface an unrelated historic cover failure as a style audition failure", async () => {
  state.labels = ["Ink", "Watercolor"];
  state.jobs = [{ id: "old-cover", kind: "project_cover", status: "failed", error: "Approve references before creating this cover.", payload: {}, queued_at: "2026-09-01" } as GenerationJob];
  render(room());
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(screen.queryByText("Approve references before creating this cover.")).toBeNull();
  expect(screen.getByRole("heading", { name: "Ink" })).toBeTruthy();
  state.jobs = [];
});

it("names author directions, filters yours newest first, and tucks hidden proofs away", async () => {
  state.estimateError = null;
  state.suggestions = [
    { id: "ink", index: 1, label: "Midnight ink", origin: "generated", template: "Ink", has_sample: true, is_active: false },
    { id: "clay", index: 2, label: "Your direction", display_label: "Claymation snowfall", origin: "user_text", template: "claymation, falling snow", has_sample: true, is_active: false },
    { id: "moth", index: 3, label: "Your direction", display_label: "Moth-wing pastel", origin: "user_text", template: "soft pastel moths", has_sample: true, is_active: false },
    { id: "noir", index: 4, label: "Noir", origin: "generated", template: "Noir", has_sample: true, is_active: false, hidden: true },
  ];
  const user = userEvent.setup();
  render(room());
  const names = () => strip().getAllByRole("button").map((button) => button.getAttribute("aria-label")).filter(Boolean);
  expect(names()).toEqual(["Midnight ink", "Claymation snowfall", "Moth-wing pastel"]);
  await open(user, "Claymation snowfall");
  expect(screen.getByText("“claymation, falling snow”")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Yours 2" }));
  expect(names()).toEqual(["Moth-wing pastel", "Claymation snowfall"]);
  await open(user, "Moth-wing pastel");
  await user.click(screen.getByRole("button", { name: "Compare · Moth-wing pastel" }));
  await open(user, "Claymation snowfall");
  await user.click(screen.getByRole("button", { name: "Compare · Claymation snowfall" }));
  await user.click(screen.getByRole("button", { name: "Compare 2" }));
  expect(screen.getByRole("button", { name: "Remove from comparison · Yours · Moth-wing pastel" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "All 3" }));
  await user.click(screen.getByRole("button", { name: /Hidden/ }));
  await open(user, "Noir");
  await user.click(screen.getByRole("button", { name: "Show · Noir" }));
  expect(state.presentation.mutate).toHaveBeenCalledWith(
    { project: "book", id: "noir", changes: { hidden: false } }, expect.any(Object),
  );
  await open(user, "Claymation snowfall");
  await user.click(screen.getByRole("button", { name: "Rename · Claymation snowfall" }));
  const input = screen.getByRole("textbox", { name: "Proof name" });
  await user.clear(input);
  await user.type(input, "Snow globe{Enter}");
  expect(state.presentation.mutate).toHaveBeenLastCalledWith(
    { project: "book", id: "clay", changes: { display_label: "Snow globe" } }, expect.any(Object),
  );
  expect(state.mutation.mutate).not.toHaveBeenCalled();
  state.suggestions = undefined;
});

it("flips through thirty proofs by keyboard, opens the sheet, and selects only from the explicit action", async () => {
  state.estimateError = null;
  state.mutation.mutate.mockReset();
  state.suggestions = Array.from({ length: 30 }, (_, index) => ({
    id: `style-${index}`, index: index + 1, label: `Look ${index + 1}`, origin: "generated",
    template: "t", has_sample: true, is_active: false,
  }));
  const user = userEvent.setup();
  render(room());
  for (let press = 0; press < 29; press++) {
    fireEvent.keyDown(screen.getByRole("group", { name: new RegExp(`, ${press + 1} / 30$`) }), { key: "ArrowRight", repeat: press > 0 });
  }
  expect(screen.getByRole("group", { name: "Look 30, 30 / 30" })).toBeTruthy();
  expect(screen.getByRole("img", { name: "Look 30" })).toBeTruthy();
  fireEvent.keyDown(screen.getByRole("group", { name: "Look 30, 30 / 30" }), { key: "ArrowRight" });
  expect(screen.getByRole("group", { name: "Look 1, 1 / 30" })).toBeTruthy();

  await user.click(screen.getByRole("button", { name: "Sheet" }));
  expect(within(screen.getByRole("list", { name: "Proof sheet" })).getAllByRole("button")).toHaveLength(30);
  await user.click(screen.getByRole("button", { name: "Open Look 12" }));
  expect(screen.getByRole("group", { name: "Look 12, 12 / 30" })).toBeTruthy();
  expect(state.mutation.mutate).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Use this style" }));
  expect(state.mutation.mutate).toHaveBeenCalledWith({ project: "book", id: "style-11" }, expect.any(Object));
  state.suggestions = undefined;
});

it("keeps author directions open while single proofs draw and during a suggestion batch", () => {
  state.estimateError = null;
  state.labels = ["Ink", "Watercolor"];
  state.stylesMeta = { is_generating: true, is_suggesting: false };
  const view = render(room());
  expect(screen.getAllByRole("button", { name: "New direction" }).every((button) => !button.hasAttribute("disabled"))).toBe(true);
  state.stylesMeta = { is_generating: true, is_suggesting: true };
  view.rerender(room());
  // Authors can submit a proof to the queue during the batch.
  expect(screen.getAllByRole("button", { name: "New direction" }).every((button) => !button.hasAttribute("disabled"))).toBe(true);
  expect(screen.getByRole("button", { name: "Test" })).toHaveProperty("disabled", false);
  state.stylesMeta = {};
});

it("queues every missing proof at once, even while another proof is drawing", async () => {
  state.estimateError = null;
  state.mutation.mutate.mockReset();
  state.stylesMeta = { is_generating: true, is_suggesting: false };
  state.suggestions = [
    { id: "ink", index: 1, label: "Ink", origin: "generated", template: "Ink", has_sample: true, is_active: false },
    { id: "noir", index: 2, label: "Noir", origin: "generated", template: "Noir", has_sample: false, generation_status: "failed", is_active: false },
    { id: "pastel", index: 3, label: "Pastel", origin: "generated", template: "Pastel", has_sample: false, generation_status: "not_requested", is_active: false },
    { id: "clay", index: 4, label: "Clay", origin: "generated", template: "Clay", has_sample: false, generation_status: "running", is_active: false },
    { id: "moth", index: 5, label: "Moth", origin: "generated", template: "Moth", has_sample: false, generation_status: "failed", is_active: false, hidden: true },
  ];
  const user = userEvent.setup();
  render(room());
  expect(screen.getByText("2 proofs didn't finish")).toBeTruthy();
  await open(user, "Noir");
  expect(screen.getByText("This proof didn't finish")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Try this proof again" })).toHaveProperty("disabled", false);
  await user.click(screen.getByRole("button", { name: "Retry all (2)" }));
  const drawer = screen.getByRole("dialog", { name: "Retry the missing proofs?" });
  await user.click(within(drawer).getByRole("button", { name: "Retry all (2)" }));
  expect(state.mutation.mutate).toHaveBeenCalledWith({ project: "book", ids: ["noir", "pastel"] }, expect.any(Object));
  state.suggestions = undefined;
  state.stylesMeta = {};
});

it.each(["queued", "running"] as const)("hides the approval footer while style suggestions are %s", (status) => {
  const previousMeta = state.stylesMeta;
  state.stylesMeta = { is_suggesting: true };
  state.jobs = [{ id: "style-batch", project_name: "book", kind: "style_suggest", label: "Style suggestions", payload: {}, status, queue_position: null, queued_at: new Date().toISOString(), started_at: null, finished_at: null, error: null }];
  try {
    render(room());
    expect(screen.queryByRole("button", { name: /Continue for/ })).toBeNull();
  } finally {
    state.stylesMeta = previousMeta;
    state.jobs = [];
  }
});

it("starts additional styles at directions until the new batch supplies its own progress", () => {
  state.stylesMeta = { is_suggesting: true };
  state.labels = ["Ink", "Watercolor"];
  const previousBatch: GenerationJob = {
    id: "previous-batch", project_name: "book", kind: "style_suggest", label: "Style suggestions",
    payload: { style_phase: "proofs", proofs: { 1: { status: "complete" }, 2: { status: "complete" } } },
    status: "complete", queue_position: null, queued_at: "2026-10-03T10:00:00Z",
    started_at: "2026-10-03T10:00:01Z", finished_at: "2026-10-03T10:02:00Z", error: null,
  };
  state.jobs = [previousBatch];
  const expectStep = (label: string) => {
    const progress = screen.getByRole("region", { name: "Style generation progress" });
    expect(within(progress).getByText("GENERATING ADDITIONAL STYLES")).toBeTruthy();
    const steps = within(progress).getByRole("list", { name: "Style generation steps" });
    const current = within(steps).getAllByRole("listitem").find((step) => step.getAttribute("aria-current") === "step");
    expect(current?.textContent).toContain(label);
  };
  try {
    const view = render(room());
    expectStep("Choose directions");
    // The job poll can also arrive before its first durable phase update.
    const newBatch = { ...previousBatch, id: "new-batch", status: "running" as const,
      queued_at: "2026-10-03T11:00:00Z", finished_at: null, payload: {} };
    state.jobs = [previousBatch, newBatch];
    view.rerender(room());
    expectStep("Choose directions");
    for (const [phase, label] of [["directions", "Choose directions"], ["production", "Design lettering"], ["proofs", "Paint proofs"]]) {
      state.jobs = [previousBatch, { ...newBatch, payload: { style_phase: phase } }];
      view.rerender(room());
      expectStep(label);
    }
  } finally {
    state.stylesMeta = {};
    state.jobs = [];
  }
});
