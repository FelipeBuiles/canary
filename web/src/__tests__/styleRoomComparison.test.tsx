import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { GenerationJob } from "../types/api";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { StyleRoom } from "../pages/rooms/StyleRoom";
import { I18nProvider } from "../i18n";

const state = vi.hoisted(() => {
  const mutation = { mutate: vi.fn(), isPending: false };
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
  useApproveStage: () => state.mutation, useGenerateProjectCover: () => ({ mutate: state.generateCover }),
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

function proof(label: string) {
  const heading = screen.getByRole("heading", { name: label, level: 3 });
  return within(heading.closest("article")!);
}

describe("StyleRoom comparison", () => {
  it("guides the first addition, keeps three choices without eviction, and allows replacement after removal", async () => {
    const user = userEvent.setup();
    const room = () => <I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
      <Route path="/projects/:id/style" element={<StyleRoom />} />
    </Routes></MemoryRouter></I18nProvider>;
    const view = render(room());
    await user.click(proof("Ink").getByRole("button", { name: "COMPARE" }));
    expect(screen.getByText("One proof added. Choose another to start comparing.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "COMPARE PROOFS" })).toBeNull();
    await user.click(proof("Watercolor").getByRole("button", { name: "COMPARE" }));
    expect(screen.getByRole("region", { name: "COMPARE PROOFS" })).toBeTruthy();
    await user.click(proof("Noir").getByRole("button", { name: "COMPARE" }));
    const fourth = proof("Graphic").getByRole("button", { name: "COMPARE" });
    expect(fourth).toHaveProperty("disabled", true);
    await user.click(fourth);
    for (const label of ["Ink", "Watercolor", "Noir"]) {
      expect(screen.getByRole("button", { name: `Remove from comparison · ${label}` })).toBeTruthy();
    }
    expect(screen.getByText("Three proofs added. Remove one to compare another.")).toBeTruthy();
    await user.click(proof("Watercolor").getByRole("button", { name: "COMPARING" }));
    expect(screen.queryByRole("button", { name: "Remove from comparison · Watercolor" })).toBeNull();
    await user.click(proof("Graphic").getByRole("button", { name: "COMPARE" }));
    expect(screen.getByRole("button", { name: "Remove from comparison · Graphic" })).toBeTruthy();
    state.labels = ["Etching", "Pastel", "Woodcut"];
    view.rerender(room());
    await user.click(proof("Etching").getByRole("button", { name: "COMPARE" }));
    expect(screen.getByText("One proof added. Choose another to start comparing.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove from comparison · Etching" })).toBeTruthy();
    expect(state.mutation.mutate).not.toHaveBeenCalled();
  });
});

it("shows estimate failures with a retry instead of claiming generation is running", async () => {
    state.labels = [];
    state.estimateError = new Error("A job cannot mix API-funded and Codex-subscription operations");
    render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
      <Route path="/projects/:id/style" element={<StyleRoom />} />
    </Routes></MemoryRouter></I18nProvider>);
    expect(screen.getByRole("alert").textContent).toContain(state.estimateError.message);
    expect(screen.queryByText("PREPARING DIRECTIONS…")).toBeNull();
    expect(screen.getByRole("button", { name: "CREATE SIX DIRECTIONS" })).toHaveProperty("disabled", true);
    await userEvent.setup().click(screen.getByRole("button", { name: "TRY AGAIN" }));
    expect(state.retryEstimate).toHaveBeenCalledOnce();
    expect(state.mutation.mutate).not.toHaveBeenCalled();
 });

it("starts Cast with its bundled cover estimate without requesting a cover before references exist", async () => {
  state.castStatus = "pending";
  state.estimateError = null;
  render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
    <Route path="/project/:id/cast" element={<p>Cast room</p>} />
  </Routes></MemoryRouter></I18nProvider>);
  await userEvent.setup().click(screen.getByRole("button", { name: "Continue for 25" }));
  expect(state.handleRun).toHaveBeenCalledWith("book", "cast", { actionLabel: "Cast characters & places" });
  expect(state.generateCover).not.toHaveBeenCalled();
  expect(screen.getByText("Cast room")).toBeTruthy();
  state.castStatus = undefined;
});

it("renders all six base proofs with their selection actions", () => {
  state.labels = ["Ink", "Watercolor", "Noir", "Graphic", "Caricature", "Paper"];
  state.estimateError = null;
  state.castStatus = undefined;
  render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
  </Routes></MemoryRouter></I18nProvider>);
  const grid = screen.getByTestId("style-proof-grid");
  expect(within(grid).getAllByRole("heading", { level: 3 })).toHaveLength(6);
  expect(within(grid).getAllByRole("button", { name: "SELECT THIS STYLE" })).toHaveLength(6);
});

it("restores all six saved proofs when a model change replaces failed cached preview URLs", async () => {
  state.estimateError = null;
  state.suggestions = Array.from({ length: 6 }, (_, index) => ({
    id: `style-${index}`, index: index + 1, label: `Look ${index + 1}`, origin: "generated",
    template: "Ink", has_sample: true, sample_stale: false, is_active: false,
    sample_preview_url: `/api/projects/book/styles/style-${index}/proof/sample?style=current`,
  }));
  const room = () => <I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
  </Routes></MemoryRouter></I18nProvider>;
  const view = render(room());
  const grid = within(screen.getByTestId("style-proof-grid"));
  await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 0)); });
  grid.getAllByRole("img").forEach((image) => fireEvent.error(image));
  expect(grid.getAllByText("PROOF IMAGE UNAVAILABLE")).toHaveLength(6);

  state.suggestions = state.suggestions.map((item) => ({ ...item, sample_preview_url: null, sample_stale: true }));
  view.rerender(room());
  expect(grid.queryAllByText("PROOF IMAGE UNAVAILABLE")).toHaveLength(0);
  const images = grid.getAllByRole("img");
  expect(images).toHaveLength(6);
  images.forEach((image, index) => {
    expect(image.getAttribute("src")).toContain(`/files/samples/style_${index + 1}.png?t=`);
  });
  expect(grid.getAllByRole("button", { name: "SELECT THIS STYLE" }).every((button) => !button.hasAttribute("disabled"))).toBe(true);
  state.suggestions = undefined;
});

it("does not surface an unrelated historic cover failure as a style audition failure", async () => {
  state.labels = ["Ink", "Watercolor"];
  state.jobs = [{ id: "old-cover", kind: "project_cover", status: "failed", error: "Approve references before creating this cover.", payload: {}, queued_at: "2026-09-01" } as GenerationJob];
  render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
  </Routes></MemoryRouter></I18nProvider>);
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
  render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
  </Routes></MemoryRouter></I18nProvider>);
  const grid = screen.getByTestId("style-proof-grid");
  expect(within(grid).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent))
    .toEqual(["Midnight ink", "Claymation snowfall", "Moth-wing pastel"]);
  expect(proof("Claymation snowfall").getByText("“claymation, falling snow”")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Yours · 2" }));
  expect(within(grid).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent))
    .toEqual(["Moth-wing pastel", "Claymation snowfall"]);
  await user.click(proof("Moth-wing pastel").getByRole("button", { name: "COMPARE" }));
  expect(screen.getByRole("button", { name: "Remove from comparison · Yours · Moth-wing pastel" })).toBeTruthy();
  const hidden = screen.getByTestId("style-proof-hidden-grid");
  expect(within(hidden).getByRole("heading", { name: "Noir" })).toBeTruthy();
  await user.click(within(hidden).getByRole("button", { name: "Show · Noir" }));
  expect(state.presentation.mutate).toHaveBeenCalledWith(
    { project: "book", id: "noir", changes: { hidden: false } }, expect.any(Object),
  );
  await user.click(proof("Claymation snowfall").getByRole("button", { name: "Rename · Claymation snowfall" }));
  const input = screen.getByRole("textbox", { name: "Proof name" });
  await user.clear(input);
  await user.type(input, "Snow globe{Enter}");
  expect(state.presentation.mutate).toHaveBeenLastCalledWith(
    { project: "book", id: "clay", changes: { display_label: "Snow globe" } }, expect.any(Object),
  );
  expect(state.mutation.mutate).not.toHaveBeenCalled();
  state.suggestions = undefined;
});

it("flips through thirty proofs by keyboard, opens the wall, and selects from the flipbook", async () => {
  state.estimateError = null;
  state.mutation.mutate.mockReset();
  state.suggestions = Array.from({ length: 30 }, (_, index) => ({
    id: `style-${index}`, index: index + 1, label: `Look ${index + 1}`, origin: "generated",
    template: "t", has_sample: true, is_active: false,
  }));
  const user = userEvent.setup();
  render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
  </Routes></MemoryRouter></I18nProvider>);
  await user.click(screen.getByRole("button", { name: "Flip" }));
  const book = screen.getByRole("group", { name: "Look 1, 1 / 30" });
  expect(document.activeElement).toBe(book);
  for (let press = 0; press < 29; press++) fireEvent.keyDown(document.activeElement!, { key: "ArrowRight", repeat: press > 0 });
  expect(screen.getByRole("group", { name: "Look 30, 30 / 30" })).toBeTruthy();
  expect(screen.getByRole("img", { name: "Look 30" })).toBeTruthy();
  fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
  expect(screen.getByRole("group", { name: "Look 1, 1 / 30" })).toBeTruthy();

  await user.click(screen.getByRole("button", { name: "Wall" }));
  expect(within(screen.getByRole("list", { name: "Proof wall" })).getAllByRole("button")).toHaveLength(30);
  await user.click(screen.getByRole("button", { name: "Flip to Look 12" }));
  expect(screen.getByRole("group", { name: "Look 12, 12 / 30" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "SELECT THIS STYLE" }));
  expect(state.mutation.mutate).toHaveBeenCalledWith({ project: "book", id: "style-11" }, expect.any(Object));
  state.suggestions = undefined;
});

it("keeps author directions open while single proofs draw and during a suggestion batch", () => {
  state.estimateError = null;
  state.labels = ["Ink", "Watercolor"];
  state.stylesMeta = { is_generating: true, is_suggesting: false };
  const room = () => <I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
  </Routes></MemoryRouter></I18nProvider>;
  const view = render(room());
  expect(screen.getByRole("button", { name: "ADD A DIRECTION" })).toHaveProperty("disabled", false);
  state.stylesMeta = { is_generating: true, is_suggesting: true };
  view.rerender(room());
  // Authors can submit a proof to the queue during the batch.
  expect(screen.getByRole("button", { name: "ADD A DIRECTION" })).toHaveProperty("disabled", false);
  expect(proof("Ink").getByRole("button", { name: "TEST IN ACTION", hidden: true })).toHaveProperty("disabled", false);
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
  render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
  </Routes></MemoryRouter></I18nProvider>);
  expect(screen.getByText("2 PROOFS DIDN'T FINISH")).toBeTruthy();
  expect(proof("Noir").getByRole("button", { name: "TRY SAMPLE AGAIN" })).toHaveProperty("disabled", false);
  await user.click(screen.getByRole("button", { name: "RETRY ALL (2)" }));
  const drawer = screen.getByRole("dialog", { name: "Retry the missing proofs?" });
  await user.click(within(drawer).getByRole("button", { name: "RETRY ALL (2)" }));
  expect(state.mutation.mutate).toHaveBeenCalledWith({ project: "book", ids: ["noir", "pastel"] }, expect.any(Object));
  state.suggestions = undefined;
  state.stylesMeta = {};
});

it.each(["queued", "running"] as const)("hides the approval footer while style suggestions are %s", (status) => {
  const previousMeta = state.stylesMeta;
  state.stylesMeta = { is_suggesting: true };
  state.jobs = [{ id: "style-batch", project_name: "book", kind: "style_suggest", label: "Style suggestions", payload: {}, status, queue_position: null, queued_at: new Date().toISOString(), started_at: null, finished_at: null, error: null }];
  try {
    render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
      <Route path="/projects/:id/style" element={<StyleRoom />} />
    </Routes></MemoryRouter></I18nProvider>);
    expect(screen.queryByRole("button", { name: /Continue for/ })).toBeNull();
  } finally {
    state.stylesMeta = previousMeta;
    state.jobs = [];
  }
});
