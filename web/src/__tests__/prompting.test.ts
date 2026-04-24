import { describe, it, expect } from "vitest";
import { renderPanelPromptBody } from "../lib/prompting";
import type { ImagePrompt, PromptSubject } from "../types/api";

const makePrompt = (
  overrides: Partial<ImagePrompt> = {}
): Pick<ImagePrompt, "subjects" | "composition" | "setting" | "lighting" | "mood" | "props" | "constraints"> => ({
  subjects: [],
  composition: null,
  setting: null,
  lighting: null,
  mood: null,
  props: null,
  constraints: null,
  ...overrides,
});

const makeSubject = (
  overrides: Partial<PromptSubject> = {}
): PromptSubject => ({
  character_id: null,
  name: "Alice",
  identity: "a young woman",
  action: "walking down a street",
  expression: "contemplative",
  position: "center frame",
  ...overrides,
});

describe("renderPanelPromptBody", () => {
  it("returns empty string for minimal prompt", () => {
    expect(renderPanelPromptBody(makePrompt())).toBe("");
  });

  it("renders subject with all fields", () => {
    const prompt = makePrompt({
      subjects: [
        makeSubject({
          name: "Alice",
          identity: "a young woman",
          action: "walking down a street",
          expression: "contemplative",
          position: "center frame",
        }),
      ],
    });
    const body = renderPanelPromptBody(prompt);
    expect(body).toContain("Alice");
    expect(body).toContain("a young woman");
    expect(body).toContain("walking down a street");
    expect(body).toContain("contemplative");
    expect(body).toContain("center frame");
  });

  it("filters out null/undefined subject fields", () => {
    const prompt = makePrompt({
      subjects: [
        makeSubject({
          expression: null,
          position: null,
        }),
      ],
    });
    const body = renderPanelPromptBody(prompt);
    expect(body).not.toContain("null");
    expect(body).not.toContain("undefined");
  });

  it("renders multiple subjects joined by semicolon", () => {
    const prompt = makePrompt({
      subjects: [
        makeSubject({ name: "Alice" }),
        makeSubject({ name: "Bob" }),
      ],
    });
    const body = renderPanelPromptBody(prompt);
    expect(body).toContain("Alice");
    expect(body).toContain("Bob");
  });

  it("renders composition", () => {
    const prompt = makePrompt({ composition: "wide shot" });
    expect(renderPanelPromptBody(prompt)).toContain("wide shot");
  });

  it("renders setting", () => {
    const prompt = makePrompt({ setting: "city street at dusk" });
    expect(renderPanelPromptBody(prompt)).toContain("city street at dusk");
  });

  it("renders lighting", () => {
    const prompt = makePrompt({ lighting: "golden hour" });
    expect(renderPanelPromptBody(prompt)).toContain("golden hour");
  });

  it("renders mood", () => {
    const prompt = makePrompt({ mood: "melancholic" });
    expect(renderPanelPromptBody(prompt)).toContain("melancholic");
  });

  it("renders props", () => {
    const prompt = makePrompt({ props: ["sword", "shield"] });
    const body = renderPanelPromptBody(prompt);
    expect(body).toContain("sword");
    expect(body).toContain("shield");
  });

  it("renders constraints", () => {
    const prompt = makePrompt({ constraints: "no text on image" });
    expect(renderPanelPromptBody(prompt)).toContain("no text on image");
  });

  it("renders all fields together", () => {
    const prompt = makePrompt({
      subjects: [makeSubject({ name: "Alice" })],
      composition: "over-the-shoulder",
      setting: "dark forest",
      lighting: "moody",
      mood: "tense",
      props: ["sword"],
      constraints: "high contrast",
    });
    const body = renderPanelPromptBody(prompt);
    expect(body).toContain("Alice");
    expect(body).toContain("over-the-shoulder");
    expect(body).toContain("dark forest");
    expect(body).toContain("moody");
    expect(body).toContain("tense");
    expect(body).toContain("sword");
    expect(body).toContain("high contrast");
  });

  it("strips newlines from all fields", () => {
    const prompt = makePrompt({ setting: "city\nstreet\novernight" });
    const body = renderPanelPromptBody(prompt);
    expect(body).not.toContain("\n");
    expect(body).toContain("city street overnight");
  });

  it("collapses multiple spaces", () => {
    const prompt = makePrompt({ mood: "very     spooky" });
    const body = renderPanelPromptBody(prompt);
    expect(body).not.toContain("  ");
  });

  it("adds trailing period", () => {
    const prompt = makePrompt({ mood: "tense" });
    expect(renderPanelPromptBody(prompt)).toMatch(/^.*\.$/);
  });

  it("returns empty string when all fields are null/empty", () => {
    const prompt = makePrompt({
      subjects: [],
      composition: null,
      setting: null,
      lighting: null,
      mood: null,
      props: null,
      constraints: null,
    });
    expect(renderPanelPromptBody(prompt)).toBe("");
  });
});
