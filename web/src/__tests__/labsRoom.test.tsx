import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LabsRunDetail } from "../api/labs";
import { I18nProvider } from "../i18n";

const state = vi.hoisted(() => ({
  options: {
    data: undefined as unknown, error: null as Error | null, isLoading: false, isFetching: false, refetch: vi.fn(),
  },
  projectOptions: undefined as unknown,
  stageOptions: undefined as unknown,
  stageEstimate: undefined as unknown,
  create: vi.fn(),
  run: undefined as unknown,
  retry: vi.fn(),
}));

const targets = [
  { id: "sunburst-openai", label: "GPT Image 2.5 Sunburst", provider: "OpenAI API", funding: "api", available: true },
  { id: "flare-openai", label: "GPT Image 2.5 Flare", provider: "OpenAI API", funding: "api", available: true },
  { id: "codex-dev/image/gpt-5.5", label: "GPT Image 2 via gpt-5.5", provider: "Codex subscription", funding: "codex_subscription", available: true },
];

vi.mock("../api/queries", () => ({
  useLabsProjects: () => ({ data: { projects: state.projectOptions ?? [{ id: "story", title: "Story", statuses: {}, words: 1200 }] }, isLoading: false }),
  useImageCompareOptions: () => state.options,
  useImageItems: () => ({ data: { items: [
    { id: "page:1", kind: "page", label: "Page 1 · 3 panels", preview: "pages/page_001.png" },
    { id: "asset:abc", kind: "asset", label: "Character sheet · refs/char_001/sheet.png", recorded_at: null, recorded_route: "fal-queue", references: 1 },
  ] }, isLoading: false }),
  useImageArmPreview: () => ({ data: undefined }),
  useImageCompareEstimate: () => ({ data: undefined }),
  useStageModelOptions: () => ({ data: state.stageOptions, isLoading: !state.stageOptions }),
  useStageModelEstimate: () => ({ data: state.stageEstimate }),
  useCreateLabsRun: () => ({ mutate: state.create, isPending: false, error: null }),
  useDeleteLabsRun: () => ({ mutate: vi.fn(), isPending: false }),
  useRetryLabsCells: () => ({ mutate: state.retry, isPending: false, error: null }),
  useLabsRuns: () => ({ data: { runs: [] } }),
  useLabsRun: () => ({ data: state.run, error: null }),
}));

import { LabsRoom } from "../pages/LabsRoom";

function renderAt(path: string) {
  return render(<I18nProvider><MemoryRouter initialEntries={[path]}><LabsRoom /></MemoryRouter></I18nProvider>);
}

const base = { status: "complete", created_at: "2026-09-29T00:00:00Z", finished_at: null, total_cost_usd: 0.1, error: null } as const;

describe("Labs", () => {
  beforeEach(() => {
    state.options.data = { targets, prompts: ["production", "restructured"] };
    state.options.error = null;
    state.options.refetch.mockClear();
    state.run = undefined;
    state.stageOptions = undefined;
    state.projectOptions = undefined;
    state.stageEstimate = undefined;
    state.create.mockClear();
    state.retry.mockReset();
  });

  it("loads source thumbnails through the Labs slug-based file route", () => {
    const { container } = renderAt("/labs");
    expect(container.querySelector("img")?.getAttribute("src"))
      .toBe("/api/labs/projects/story/files/pages/page_001.png");
  });

  it("offers a single retry when models fail to load", () => {
    state.options.error = new Error("Service unavailable");
    renderAt("/labs");

    expect(screen.getByRole("alert").textContent).toContain("Labs could not be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Retry Labs" }));
    expect(state.options.refetch).toHaveBeenCalledTimes(1);
  });

  it("builds arms from any model or route and counts images per selected item", () => {
    renderAt("/labs");

    expect(screen.getByRole("button", { name: /Arm 1 model and route/ }).textContent).toContain("OpenAI API");
    fireEvent.click(screen.getByRole("button", { name: "Add arm" }));
    expect(screen.getByText("Arm 3")).toBeTruthy();
    expect(screen.getByText("Each arm must differ in model, route, prompt or quality.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove arm 3" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Page 1/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Character sheet/ }));
    expect(screen.getByRole("button", { name: "Run 4 images" })).toBeTruthy();
  });

  it("defaults to Sunburst versus Flare on OpenAI with the same production prompt", () => {
    renderAt("/labs");

    expect(screen.getByRole("button", { name: "Arm 1 model and route" }).textContent)
      .toContain("GPT Image 2.5 Sunburst · OpenAI API");
    expect(screen.getByRole("button", { name: "Arm 2 model and route" }).textContent)
      .toContain("GPT Image 2.5 Flare · OpenAI API");
    fireEvent.click(screen.getByRole("checkbox", { name: /Page 1/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run 2 images" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      kind: "image_compare", project: "story", items: ["page:1"],
      arms: [{ target: "sunburst-openai", prompt: "production" }, { target: "flare-openai", prompt: "production" }],
    }), expect.anything());
  });

  it("lets GPT Image arms choose a quality and sends it with the arm", () => {
    state.options.data = {
      targets: [
        { ...targets[0], accepts_quality: true, page_quality: true },
        { id: "flare-2.6-openai", label: "GPT Image 2.6 Flare", provider: "OpenAI API", funding: "api", available: true,
          accepts_quality: true, page_quality: true },
        targets[2],
      ],
      prompts: ["production", "restructured"],
      qualities: ["low", "medium", "high"],
    };
    renderAt("/labs");

    fireEvent.click(screen.getByRole("button", { name: "Arm 2 model and route" }));
    fireEvent.click(screen.getByRole("option", { name: /GPT Image 2.6 Flare/ }));
    fireEvent.click(screen.getByRole("button", { name: "Arm 2 quality" }));
    fireEvent.click(screen.getByRole("option", { name: "Low quality" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Page 1/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run 2 images" }));

    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      arms: [{ target: "sunburst-openai", prompt: "production" },
        { target: "flare-2.6-openai", prompt: "production", quality: "low" }],
    }), expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Arm 2 model and route" }));
    fireEvent.click(screen.getByRole("option", { name: /via gpt-5.5/ }));
    expect(screen.queryByRole("button", { name: "Arm 2 quality" })).toBeNull();
  });

  it("hides which arm made each image until the reviewer reveals it", () => {
    const cell = (arm: number, funding: "api" | "codex_subscription") => ({
      cell_id: `page-1.arm${arm + 1}`, item: "page:1", arm, target: arm ? "codex-dev/image/gpt-5.5" : "sunburst-openai",
      prompt: "production" as const, funding, status: "ok" as const, image: `images/page-1.arm${arm + 1}.png`,
      prompt_file: `prompts/page-1.arm${arm + 1}.txt`, prompt_chars: 9000 + arm, latency_ms: 20000 + arm * 60000,
      cost_usd: arm ? 0 : 0.06, api_equivalent_usd: 0.03, requested_size: "1024x1536",
      output_size: arm ? "1027x1531" : "1024x1536",
    });
    state.run = {
      ...base, run_id: "r1", kind: "image_compare", label: "Sunburst vs Codex",
      spec: { items: ["page:1"], arms: [{ target: "sunburst-openai", prompt: "production" }, { target: "codex-dev/image/gpt-5.5", prompt: "production" }] },
      cells: [cell(0, "api"), cell(1, "codex_subscription")],
    } satisfies LabsRunDetail;
    const { container } = renderAt("/labs?run=r1");

    expect(screen.getByText("Image 1")).toBeTruthy();
    expect(screen.queryByText(/Arm 1 ·/)).toBeNull();
    // Nothing that differs by arm is visible while blind: timing, cost, size, prompt length or file names in links.
    expect(screen.queryByText(/\d+\.\ds|×|-char prompt/)).toBeNull();
    expect(container.querySelectorAll("a[href*='arm']").length).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Reveal arms" }));
    expect(screen.getAllByText(/Arm 2 · GPT Image 2 via gpt-5.5 · Codex subscription/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/subscription \(≈\$0\.030 at API rates\)/).length).toBeGreaterThan(0);
    expect(screen.getByText("$0.060")).toBeTruthy();
    expect(screen.getByText(/asked 1024×1536/)).toBeTruthy();
  });

  it("retries one failed image, or every failure, with the same request", () => {
    const failed = (arm: number) => ({
      cell_id: `page-1.arm${arm + 1}`, item: "page:1", arm, target: "codex-dev/image/gpt-5.5",
      prompt: (arm ? "restructured" : "production") as "production" | "restructured", funding: "codex_subscription" as const,
      status: "failed" as const, error: "runtime_timeout", requested_size: "1024x1536",
    });
    state.run = {
      ...base, run_id: "r1", kind: "image_compare", label: "Codex A/B",
      spec: { items: ["page:1"], arms: [{ target: "codex-dev/image/gpt-5.5", prompt: "production" }, { target: "codex-dev/image/gpt-5.5", prompt: "restructured" }] },
      cells: [failed(0), failed(1)],
    } satisfies LabsRunDetail;
    renderAt("/labs?run=r1");

    fireEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    expect(state.retry).toHaveBeenCalledWith([expect.stringMatching(/^page-1\.arm[12]$/)], expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Retry 2 failed" }));
    expect(state.retry).toHaveBeenLastCalledWith(["page-1.arm1", "page-1.arm2"], expect.anything());
  });

  it("retries one failed text arm, or every failure, and keeps earlier attempts' spend visible", () => {
    const stage = (model: string, error: string | null, cost: number) => ({
      stage: "extract", status: error ? "failed" : "complete", error, seconds: 50, calls: 3, input_tokens: 58000,
      cached_input_tokens: 0, output_tokens: 40000, cost_usd: cost, unpriced_calls: 0, models: [model], funding: ["api"],
    });
    state.run = {
      ...base, run_id: "r3", kind: "stage_models", label: "Haiku vs Flash",
      spec: { phases: ["extract_brief"] },
      cells: [
        { cell_id: "extract_brief.haiku", phase: "extract_brief", model: "haiku", funding: "api", status: "failed",
          workspace: "workspaces/extract_brief.haiku", stages: [stage("haiku", "malformed JSON", 0.026)], cost_usd: 0.026 },
        { cell_id: "extract_brief.flash", phase: "extract_brief", model: "flash", funding: "api", status: "ok",
          workspace: "workspaces/extract_brief.flash", stages: [stage("flash", null, 0.03)], cost_usd: 0.03,
          attempts: [{ workspace: "workspaces/extract_brief.flash.attempt1", cost_usd: 0.012, api_equivalent_usd: 0.012, error: "timeout" }] },
      ],
    } satisfies LabsRunDetail;
    renderAt("/labs?run=r3");

    expect(screen.getByText(/Succeeded on retry 1 · earlier spend \$0\.012/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.retry).toHaveBeenCalledWith(["extract_brief.haiku"], expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Retry 1 failed" }));
    expect(state.retry).toHaveBeenLastCalledWith(["extract_brief.haiku"], expect.anything());
  });

  it("keeps other failed arms retryable while one retry runs", () => {
    state.retry.mockImplementation((cells: string[], options: { onSuccess: (result: { cells: string[] }) => void }) =>
      options.onSuccess({ cells }));
    const failed = (id: string) => ({
      cell_id: id, phase: "full", model: id, funding: "api" as const, status: "failed" as const,
      workspace: `workspaces/${id}`, stages: [], error: "Adapt requires an approved adaptation brief",
    });
    state.run = {
      ...base, run_id: "r4", kind: "stage_models", label: "E2E", status: "running",
      spec: { phases: ["full"] }, cells: [failed("full.a"), failed("full.b")],
    } satisfies LabsRunDetail;
    renderAt("/labs?run=r4");

    const [first, second] = screen.getAllByRole("button", { name: "Retry" }) as HTMLButtonElement[];
    fireEvent.click(first);
    expect(state.retry).toHaveBeenCalledWith(["full.a"], expect.anything());
    expect(first.disabled).toBe(true);
    expect(second.disabled).toBe(false);
    expect(screen.getByRole("button", { name: "Retry 1 failed" })).toBeTruthy();
    fireEvent.click(second);
    expect(state.retry).toHaveBeenLastCalledWith(["full.b"], expect.anything());
    expect(screen.queryByRole("button", { name: /failed$/ })).toBeNull();
  });

  it("compares stages side by side and reports subscription runs as allowance, not dollars", () => {
    const arm = (model: string, funding: "api" | "claude_subscription", cost: number) => ({
      cell_id: `adapt_plan.${model}`, phase: "adapt_plan", model, funding, status: "ok" as const,
      workspace: `workspaces/adapt_plan.${model}`, seconds: 120, cost_usd: cost,
      stages: [{
        stage: "plan", status: "complete", error: null, seconds: 90, calls: 12, input_tokens: 345000,
        cached_input_tokens: 72000, output_tokens: 40000, cost_usd: cost, unpriced_calls: 0, models: [model], funding: [funding],
        counts: { pages: 24, panels: 64 }, validation: { attempts: 2, invariant_failures: 0, editorial_issues: 2, blocking_issues: 0 },
        artifact: "plan/book.json",
      }],
    });
    state.run = {
      ...base, run_id: "r2", kind: "stage_models", label: "Masque",
      spec: { phases: ["adapt_plan"], estimated_cost_usd: { opus: 3.16, "claude-dev": 0 } },
      cells: [arm("opus", "api", 2.9), arm("claude-dev", "claude_subscription", 0)],
    } satisfies LabsRunDetail;
    renderAt("/labs?run=r2");

    const table = screen.getByRole("table");
    expect(within(table).getByText("$2.900")).toBeTruthy();
    expect(within(table).getByText("subscription")).toBeTruthy();
    expect(within(table).getAllByText("2 (0 blocking)").length).toBe(2);
    expect(within(table).getAllByRole("link", { name: "Open book.json" })[0].getAttribute("href"))
      .toBe("/api/labs/runs/r2/files/workspaces/adapt_plan.opus/plan/book.json");
    expect(screen.getByText("Claude subscription")).toBeTruthy();
  });
  it("submits independent reasoning choices for each Labs model and stage", () => {
    state.stageOptions = {
      models: [
        { id: "opus", label: "Opus", provider: "Anthropic", funding: "api", available: true,
          reasoning_options: ["low", "medium", "high"], default_reasoning: "medium" },
        { id: "mimo", label: "MiMo", provider: "OpenRouter", funding: "api", available: true,
          reasoning_options: ["none", "enabled"], default_reasoning: "none" },
      ],
      default_models: ["opus", "mimo"], phases: { extract_brief: ["extract", "brief"] },
    };
    renderAt("/labs?new=stage_models");
    fireEvent.change(screen.getByRole("combobox", { name: "Opus arm-1 extract reasoning" }), { target: { value: "high" } });
    fireEvent.change(screen.getByRole("combobox", { name: "MiMo arm-2 brief reasoning" }), { target: { value: "enabled" } });
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      arms: [
        { id: "arm-1", model: "opus", stage_models: { extract: "opus", brief: "opus" }, reasoning_efforts: { extract: "high", brief: "medium" } },
        { id: "arm-2", model: "mimo", stage_models: { extract: "mimo", brief: "mimo" }, reasoning_efforts: { extract: "none", brief: "enabled" } },
      ],
    }), expect.anything());
  });

  it("gives one stage of an arm its own model and that model's reasoning choices", () => {
    state.stageOptions = {
      models: [
        { id: "argon", label: "Argon", provider: "Vertex", funding: "api", available: true,
          reasoning_options: ["low", "medium", "high"], default_reasoning: "low" },
        { id: "mimo", label: "MiMo", provider: "OpenRouter", funding: "api", available: true,
          reasoning_options: ["none", "enabled"], default_reasoning: "none" },
      ],
      default_models: ["argon", "mimo"], phases: { adapt_plan: ["adapt", "plan"] },
    };
    state.projectOptions = [{ id: "story", title: "Story", statuses: { brief: "complete", style: "complete", cast: "complete" }, words: 1200 }];
    renderAt("/labs?new=stage_models");
    fireEvent.change(screen.getByRole("combobox", { name: "Argon arm-1 adapt reasoning" }), { target: { value: "high" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Argon arm-1 adapt model" }), { target: { value: "mimo" } });
    const reasoning = screen.getByRole("combobox", { name: "Argon arm-1 adapt reasoning" }) as HTMLSelectElement;
    expect([...reasoning.options].map((option) => option.value)).toEqual(["none", "enabled"]);
    expect(reasoning.value).toBe("none");
    expect(screen.getByText("Argon · adapt: MiMo · arm-1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      label: expect.stringContaining("argon · adapt: mimo vs mimo"),
      arms: [
        { id: "arm-1", model: "argon", stage_models: { adapt: "mimo", plan: "argon" }, reasoning_efforts: { adapt: "none", plan: "low" } },
        { id: "arm-2", model: "mimo", stage_models: { adapt: "mimo", plan: "mimo" }, reasoning_efforts: { adapt: "none", plan: "none" } },
      ],
    }), expect.anything());
  });

  it("runs end to end alongside the controlled phases with one model per stage", () => {
    state.stageOptions = {
      models: [
        { id: "argon", label: "Argon", provider: "Vertex", funding: "api", available: true,
          reasoning_options: ["low", "medium", "high"], default_reasoning: "low" },
        { id: "flash", label: "Flash", provider: "Vertex", funding: "api", available: true,
          reasoning_options: ["low", "medium", "high"], default_reasoning: "low" },
      ],
      default_models: ["argon", "flash"],
      phases: { extract_brief: ["extract", "brief"], adapt_plan: ["adapt", "plan"], full: ["extract", "brief", "adapt", "plan"] },
    };
    state.projectOptions = [{ id: "story", title: "Story", statuses: { style: "complete", cast: "complete" }, words: 1200 }];
    renderAt("/labs?new=stage_models");
    expect((screen.getByRole("checkbox", { name: /Adapt \+ Plan/ }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("Needs an approved Brief, Style, Cast")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /End to end/ }));
    expect(screen.getAllByRole("combobox", { name: "Argon arm-1 adapt model" })).toHaveLength(1);
    fireEvent.change(screen.getByRole("combobox", { name: "Argon arm-1 adapt model" }), { target: { value: "flash" } });
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      phases: ["extract_brief", "full"],
      arms: [
        { id: "arm-1", model: "argon", stage_models: { extract: "argon", brief: "argon", adapt: "flash", plan: "argon" },
          reasoning_efforts: { extract: "low", brief: "low", adapt: "low", plan: "low" } },
        { id: "arm-2", model: "flash", stage_models: { extract: "flash", brief: "flash", adapt: "flash", plan: "flash" },
          reasoning_efforts: { extract: "low", brief: "low", adapt: "low", plan: "low" } },
      ],
    }), expect.anything());
  });

  it("allows six models and re-enables another choice after deselecting one", () => {
    state.stageOptions = {
      models: Array.from({ length: 7 }, (_, index) => ({
        id: `model-${index}`, label: `Model ${index}`, provider: "API", funding: "api", available: true,
        reasoning_options: ["low", "medium", "high"], default_reasoning: "medium",
      })),
      default_models: ["model-0", "model-1"], phases: { extract_brief: ["extract", "brief"] },
    };
    renderAt("/labs?new=stage_models");
    for (const index of [2, 3, 4, 5]) fireEvent.click(screen.getByRole("checkbox", { name: `Model ${index}` }));
    const seventh = screen.getByRole("checkbox", { name: "Model 6" }) as HTMLInputElement;
    expect(seventh.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      arms: Array.from({ length: 6 }, (_, index) => ({
        id: `arm-${index + 1}`, model: `model-${index}`, stage_models: { extract: `model-${index}`, brief: `model-${index}` },
        reasoning_efforts: { extract: "medium", brief: "medium" },
      })),
    }), expect.anything());
    fireEvent.click(screen.getByRole("checkbox", { name: "Model 5" }));
    expect(seventh.disabled).toBe(false);
  });

  it("duplicates one model with independent reasoning and counts both arm estimates", () => {
    state.stageOptions = {
      models: [{ id: "argon", label: "Argon", provider: "Vertex", funding: "api", available: true,
        reasoning_options: ["low", "medium", "high"], default_reasoning: "medium" }],
      default_models: ["argon"], phases: { extract_brief: ["extract", "brief"] },
    };
    state.stageEstimate = { estimated_cost_usd: { "arm-1": 1, "arm-2": 1 } };
    renderAt("/labs?new=stage_models");
    expect((screen.getByRole("button", { name: "Run comparison" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole("combobox", { name: "Argon arm-1 extract reasoning" }), { target: { value: "low" } });
    fireEvent.click(screen.getByRole("button", { name: "Duplicate Argon arm-1" }));
    expect((screen.getByRole("combobox", { name: "Argon arm-2 extract reasoning" }) as HTMLSelectElement).value).toBe("low");
    fireEvent.change(screen.getByRole("combobox", { name: "Argon arm-2 extract reasoning" }), { target: { value: "high" } });
    expect((screen.getByRole("combobox", { name: "Argon arm-1 extract reasoning" }) as HTMLSelectElement).value).toBe("low");
    expect(screen.getByText(/≈\$2.00 est. for API arms/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({ arms: [
      { id: "arm-1", model: "argon", stage_models: { extract: "argon", brief: "argon" }, reasoning_efforts: { extract: "low", brief: "medium" } },
      { id: "arm-2", model: "argon", stage_models: { extract: "argon", brief: "argon" }, reasoning_efforts: { extract: "high", brief: "medium" } },
    ] }), expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Remove Argon arm-1" }));
    expect(screen.queryByRole("combobox", { name: "Argon arm-1 extract reasoning" })).toBeNull();
    expect((screen.getByRole("combobox", { name: "Argon arm-2 extract reasoning" }) as HTMLSelectElement).value).toBe("high");
    expect((screen.getByRole("button", { name: "Run comparison" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps repeated models distinct in the results table and artifact links", () => {
    state.run = {
      ...base, label: "Repeated Argon", run_id: "repeat", kind: "stage_models", spec: { phases: ["extract_brief"] }, cells: ["low", "high"].map((effort) => ({
        cell_id: `extract_brief.argon.${effort}`, phase: "extract_brief", model: "argon", variant: effort,
        reasoning_efforts: { extract: effort }, funding: "api", status: "ok", workspace: `workspaces/argon.${effort}`,
        stages: [{ stage: "extract", status: "complete", error: null, seconds: 1, calls: 1, input_tokens: 100,
          cached_input_tokens: 0, output_tokens: 10, cost_usd: 0.1, unpriced_calls: 0, models: ["argon"], funding: ["api"],
          artifact: "extract/story_bible.json" }],
      })),
    } satisfies LabsRunDetail;
    renderAt("/labs?run=repeat");
    const table = screen.getByRole("table");
    expect(within(table).getByText("low reasoning")).toBeTruthy();
    expect(within(table).getByText("high reasoning")).toBeTruthy();
    expect(within(table).getAllByRole("link", { name: "Open story_bible.json" }).map((link) => link.getAttribute("href")))
      .toEqual(["/api/labs/runs/repeat/files/workspaces/argon.low/extract/story_bible.json",
        "/api/labs/runs/repeat/files/workspaces/argon.high/extract/story_bible.json"]);
  });

  it("enables Adapt + Plan for a completed part and pins that part in the Labs request", () => {
    state.projectOptions = [{ id: "the-monkey-s-paw", title: "The Monkey's Paw", part_id: "part_0001",
      statuses: { brief: "complete", style: "complete", cast: "complete" }, words: 3933 }];
    state.stageOptions = {
      models: ["argon", "flash"].map((id) => ({ id, label: id, provider: "Vertex", funding: "api", available: true,
        reasoning_options: ["low", "medium", "high"], default_reasoning: "medium" })),
      default_models: ["argon", "flash"], phases: { extract_brief: ["extract", "brief"], adapt_plan: ["adapt", "plan"] },
    };
    renderAt("/labs?new=stage_models");
    const phase = screen.getByRole("checkbox", { name: /Adapt.*Plan/ }) as HTMLInputElement;
    expect(phase.disabled).toBe(false);
    expect(phase.checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      project: "the-monkey-s-paw", part_id: "part_0001", phases: ["extract_brief", "adapt_plan"],
    }), expect.anything());
  });

});
