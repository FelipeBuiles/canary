import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StyleGenerationProgress } from "../components/style/StyleGenerationProgress";
import type { GenerationJob } from "../types/api";
import { I18nProvider } from "../i18n";

function job(overrides: Partial<GenerationJob> = {}, payload: Record<string, unknown> = {}): GenerationJob {
  return {
    id: "job-1", project_name: "story", kind: "style_suggest", label: "Style suggestions",
    payload, status: "running", queue_position: null, queued_at: "2026-10-03T10:00:00Z",
    started_at: new Date(Date.now() - 65_000).toISOString(), finished_at: null, error: null,
    ...overrides,
  };
}

function view(input: GenerationJob | undefined, fallbackPhase: "directions" | "proofs" = "directions") {
  render(
    <I18nProvider>
      <StyleGenerationProgress job={input} fallbackPhase={fallbackPhase} title="GENERATING STYLE OPTIONS" />
    </I18nProvider>,
  );
}

function currentStep() {
  const steps = within(screen.getByRole("list", { name: "Style generation steps" })).getAllByRole("listitem");
  return steps.find((step) => step.getAttribute("aria-current") === "step");
}

describe("StyleGenerationProgress", () => {
  it("explains the direction step and shows elapsed time", () => {
    view(job({}, { style_phase: "directions" }));
    expect(currentStep()?.textContent).toContain("Choose directions");
    expect(screen.getByRole("status")?.textContent).toContain("weighing a dozen visual directions");
    expect(screen.getByLabelText(/Elapsed 1:0\d/)).toBeTruthy();
  });

  it("lists the chosen directions while their lettering is designed", () => {
    view(job({}, {
      style_phase: "production",
      style_shortlist: [
        { label: "Midnight ink", medium: "ink wash", role: "story_fit_primary", story_fit: "Keeps danger close." },
        { label: "Paper puppets", medium: "cut paper", role: "wildcard" },
      ],
    }));
    expect(currentStep()?.textContent).toContain("Design lettering");
    const chosen = screen.getByRole("list", { name: "Chosen directions" });
    expect(within(chosen).getAllByRole("listitem")).toHaveLength(2);
    expect(chosen?.textContent).toContain("Midnight ink");
    expect(chosen?.textContent).toContain("Keeps danger close.");
  });

  it("counts finished proofs", () => {
    view(job({}, {
      style_phase: "proofs",
      proofs: { 1: { status: "complete" }, 2: { status: "running" }, 3: { status: "queued" } },
    }));
    expect(currentStep()?.textContent).toContain("Paint proofs 1/3");
    expect(screen.queryByRole("list", { name: "Chosen directions" })).toBeNull();
  });

  it("explains a queued batch with its position", () => {
    view(job({ status: "queued", started_at: null, queue_position: 2 }));
    expect(currentStep()).toBeUndefined();
    expect(screen.getByRole("status")?.textContent).toContain("Position 2 in line.");
  });

  it("falls back when no batch job carries a phase", () => {
    view(undefined, "proofs");
    expect(currentStep()?.textContent).toContain("Paint proofs");
  });
});
