import { describe, it, expect } from "vitest";
import { detectPromptWarnings, detectAllWarnings } from "../lib/promptWarnings";
import type { ImagePrompt } from "../types/api";

function makePrompt(overrides: Partial<ImagePrompt> = {}): ImagePrompt {
  return {
    scene_id: "scene_01",
    panel_number: 1,
    full_prompt: "A detailed scene with a character standing in a forest clearing.",
    style: "pulp noir",
    composition: "Medium shot of the hero standing tall in the clearing",
    setting: "Dense forest clearing at dawn",
    lighting: "Soft golden light",
    mood: "Tense",
    subjects: [],
    width: 1024,
    height: 1536,
    steps: 30,
    ...overrides,
  };
}

// ── thin_composition ─────────────────────────────────────────────────────────

describe("thin_composition", () => {
  it("warns when composition is null", () => {
    const prompt = makePrompt({ composition: null });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_composition")).toBe(true);
  });

  it("warns when composition is empty string", () => {
    const prompt = makePrompt({ composition: "" });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_composition")).toBe(true);
  });

  it("warns when composition is under 20 chars", () => {
    const prompt = makePrompt({ composition: "Short shot" });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_composition")).toBe(true);
  });

  it("does not warn when composition is 20+ chars", () => {
    const prompt = makePrompt({ composition: "Medium shot of the hero" });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_composition")).toBe(false);
  });

  it("trims whitespace before length check", () => {
    const prompt = makePrompt({ composition: "   tiny   " });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_composition")).toBe(true);
  });
});

// ── thin_setting ─────────────────────────────────────────────────────────────

describe("thin_setting", () => {
  it("warns when setting is null", () => {
    const prompt = makePrompt({ setting: null });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_setting")).toBe(true);
  });

  it("warns when setting is empty string", () => {
    const prompt = makePrompt({ setting: "" });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_setting")).toBe(true);
  });

  it("warns when setting is under 15 chars", () => {
    const prompt = makePrompt({ setting: "Dark alley" });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_setting")).toBe(true);
  });

  it("does not warn when setting is 15+ chars", () => {
    const prompt = makePrompt({ setting: "Rainy dark alley" });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "thin_setting")).toBe(false);
  });
});

// ── text_in_prompt ───────────────────────────────────────────────────────────

describe("text_in_prompt", () => {
  it("warns when full_prompt contains curly double quotes", () => {
    const prompt = makePrompt({ full_prompt: 'She said “Hello” to him' });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "text_in_prompt")).toBe(true);
  });

  it("warns when full_prompt contains straight double quotes", () => {
    const prompt = makePrompt({ full_prompt: 'He said "goodbye"' });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "text_in_prompt")).toBe(true);
  });

  it("warns when composition contains dialogue pattern", () => {
    const prompt = makePrompt({ composition: 'Hero said “I will find you” facing camera' });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "text_in_prompt")).toBe(true);
  });

  it("does not warn for clean prompt", () => {
    const prompt = makePrompt();
    expect(detectPromptWarnings(prompt).some((w) => w.code === "text_in_prompt")).toBe(false);
  });
});

// ── missing_style ────────────────────────────────────────────────────────────

describe("missing_style", () => {
  it("warns when style is null", () => {
    const prompt = makePrompt({ style: null });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "missing_style")).toBe(true);
  });

  it("does not warn when style is set", () => {
    const prompt = makePrompt({ style: "pulp noir" });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "missing_style")).toBe(false);
  });

});

// ── inconsistent_dimensions ──────────────────────────────────────────────────

describe("inconsistent_dimensions", () => {
  it("warns when width is 0", () => {
    const prompt = makePrompt({ width: 0 });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "inconsistent_dimensions")).toBe(true);
  });

  it("warns when height is 0", () => {
    const prompt = makePrompt({ height: 0 });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "inconsistent_dimensions")).toBe(true);
  });

  it("warns when steps is 0", () => {
    const prompt = makePrompt({ steps: 0 });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "inconsistent_dimensions")).toBe(true);
  });

  it("does not warn when all dimensions are set", () => {
    const prompt = makePrompt({ width: 1024, height: 1536, steps: 30 });
    expect(detectPromptWarnings(prompt).some((w) => w.code === "inconsistent_dimensions")).toBe(false);
  });
});

// ── detectAllWarnings ────────────────────────────────────────────────────────

describe("detectAllWarnings", () => {
  it("returns flattened warnings for mixed prompts", () => {
    const cleanPrompt = makePrompt({ panel_number: 1 });
    const dirtyPrompt = makePrompt({ panel_number: 2, composition: null, setting: null });
    const warnings = detectAllWarnings([cleanPrompt, dirtyPrompt]);
    expect(warnings.some((w) => w.panel_number === 2 && w.code === "thin_composition")).toBe(true);
    expect(warnings.some((w) => w.panel_number === 2 && w.code === "thin_setting")).toBe(true);
  });

  it("returns empty array for clean prompts", () => {
    const prompts = [makePrompt({ panel_number: 1 }), makePrompt({ panel_number: 2 })];
    expect(detectAllWarnings(prompts)).toHaveLength(0);
  });

  it("emits exactly one thin_composition warning per panel", () => {
    const prompt = makePrompt({ composition: null });
    const warnings = detectAllWarnings([prompt]);
    const thinComp = warnings.filter((w) => w.code === "thin_composition");
    expect(thinComp).toHaveLength(1);
  });
});
