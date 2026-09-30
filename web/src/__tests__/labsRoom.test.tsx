import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LabsRunDetail } from "../api/labs";
import { I18nProvider } from "../i18n";

const state = vi.hoisted(() => ({
  options: {
    data: undefined as unknown, error: null as Error | null, isLoading: false, isFetching: false, refetch: vi.fn(),
  },
  stageOptions: undefined as unknown,
  create: vi.fn(),
  run: undefined as unknown,
  retry: vi.fn(),
}));

const targets = [
  { id: "sunburst-openai", label: "GPT Image 2.5 Sunburst", provider: "OpenAI API", funding: "api", available: true },
  { id: "codex-dev/image/gpt-5.5", label: "GPT Image 2 via gpt-5.5", provider: "Codex subscription", funding: "codex_subscription", available: true },
];

vi.mock("../api/queries", () => ({
  useLabsProjects: () => ({ data: { projects: [{ id: "story", title: "Story", statuses: {}, words: 1200 }] }, isLoading: false }),
  useImageCompareOptions: () => state.options,
  useImageItems: () => ({ data: { items: [
    { id: "page:1", kind: "page", label: "Page 1 · 3 panels", preview: "pages/page_001.png" },
    { id: "asset:abc", kind: "asset", label: "Character sheet · refs/char_001/sheet.png", recorded_at: null, recorded_route: "fal-queue", references: 1 },
  ] }, isLoading: false }),
  useImageArmPreview: () => ({ data: undefined }),
  useImageCompareEstimate: () => ({ data: undefined }),
  useStageModelOptions: () => ({ data: state.stageOptions, isLoading: !state.stageOptions }),
  useStageModelEstimate: () => ({ data: undefined }),
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
    state.create.mockClear();
    state.retry.mockClear();
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
    expect(screen.getByText("Each arm must differ in model, route or prompt.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove arm 3" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Page 1/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Character sheet/ }));
    expect(screen.getByRole("button", { name: "Run 4 images" })).toBeTruthy();
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
    expect(state.retry).toHaveBeenCalledWith([expect.stringMatching(/^page-1\.arm[12]$/)]);
    fireEvent.click(screen.getByRole("button", { name: "Retry 2 failed" }));
    expect(state.retry).toHaveBeenLastCalledWith(undefined);
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
    fireEvent.change(screen.getByRole("combobox", { name: "Opus extract reasoning" }), { target: { value: "high" } });
    fireEvent.change(screen.getByRole("combobox", { name: "MiMo brief reasoning" }), { target: { value: "enabled" } });
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({
      reasoning_efforts: { opus: { extract: "high", brief: "medium" }, mimo: { extract: "none", brief: "enabled" } },
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
      models: ["model-0", "model-1", "model-2", "model-3", "model-4", "model-5"],
    }), expect.anything());
    fireEvent.click(screen.getByRole("checkbox", { name: "Model 5" }));
    expect(seventh.disabled).toBe(false);
  });

});
