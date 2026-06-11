import { describe, it, expect } from "vitest";
import { detectIssues, contrastRatio } from "../lib/issueEngine";
import type { ComicPage, ImageStatus, PagePanel, Bubble } from "../types/api";

// ── Factories ────────────────────────────────────────────────────────────────

function makeBubble(overrides: Partial<Bubble> = {}): Bubble {
  return {
    id: "b1",
    type: "speech",
    text: "Hello",
    speaker_id: null,
    speaker_name: null,
    side: "left",
    full_width: null,
    x: null,
    y: null,
    width: null,
    tail_x: null,
    tail_y: null,
    tail_direction: "auto",
    font_family: null,
    font_size: null,
    font_color: null,
    fill_color: null,
    border_color: null,
    border_width: null,
    border_radius: null,
    ...overrides,
  };
}

function makePanel(overrides: Partial<PagePanel> = {}): PagePanel {
  return {
    id: "panel1",
    planned_panel_id: null,
    image_path: "/img.png",
    scene_id: "scene1",
    panel_number: 1,
    importance: null,
    generation_mode: null,
    bubbles: [],
    sfx: [],
    image_offset_x: null,
    image_offset_y: null,
    grid_column: null,
    grid_row: null,
    x: null,
    y: null,
    width: null,
    height: null,
    clip_path: null,
    z_index: null,
    shape_intent: null,
    ...overrides,
  };
}

function makePage(overrides: Partial<ComicPage> = {}): ComicPage {
  return {
    page_number: 1,
    source_page_id: null,
    theme: "default",
    layout: "2x2",
    layout_mode: "grid",
    style_vars: {},
    panels: [makePanel()],
    ...overrides,
  };
}

function makeImageStatus(overrides: Partial<ImageStatus> = {}): ImageStatus {
  return {
    scene_id: "scene1",
    panel_number: 1,
    status: "done",
    image_available: true,
    accepted: true,
    ...overrides,
  };
}

// ── contrastRatio ────────────────────────────────────────────────────────────

describe("contrastRatio", () => {
  it("white on black is 21:1", () => {
    expect(contrastRatio("#ffffff", "#000000")).toBeCloseTo(21, 0);
  });

  it("same color is 1:1", () => {
    expect(contrastRatio("#ff0000", "#ff0000")).toBeCloseTo(1, 5);
  });

  it("returns Infinity for invalid input", () => {
    expect(contrastRatio("red", "#000000")).toBe(Infinity);
    expect(contrastRatio("#000000", "rgba(0,0,0,1)")).toBe(Infinity);
    expect(contrastRatio("", "#fff")).toBe(Infinity);
  });

  it("supports #rgb shorthand", () => {
    expect(contrastRatio("#fff", "#000")).toBeCloseTo(21, 0);
  });
});

// ── unaccepted_panel ─────────────────────────────────────────────────────────

describe("unaccepted_panel", () => {
  it("flags panel when accepted=false and status=done", () => {
    const pages = [makePage()];
    const images = [makeImageStatus({ accepted: false })];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "unaccepted_panel")).toHaveLength(1);
  });

  it("does not flag when accepted=true", () => {
    const pages = [makePage()];
    const images = [makeImageStatus({ accepted: true })];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "unaccepted_panel")).toHaveLength(0);
  });

  it("does not flag when status is not done", () => {
    const pages = [makePage()];
    const images = [makeImageStatus({ accepted: false, status: "running" })];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "unaccepted_panel")).toHaveLength(0);
  });
});

// ── missing_image ────────────────────────────────────────────────────────────

describe("missing_image", () => {
  it("flags panel with no matching ImageStatus", () => {
    const pages = [makePage()];
    const issues = detectIssues(pages, []);
    expect(issues.filter((i) => i.type === "missing_image")).toHaveLength(1);
    expect(issues.find((i) => i.type === "missing_image")?.severity).toBe("error");
  });

  it("flags panel when image_available=false", () => {
    const pages = [makePage()];
    const images = [makeImageStatus({ image_available: false })];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "missing_image")).toHaveLength(1);
  });

  it("does not flag when image_available=true", () => {
    const pages = [makePage()];
    const images = [makeImageStatus({ image_available: true })];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "missing_image")).toHaveLength(0);
  });
});

// ── empty_bubble_text ────────────────────────────────────────────────────────

describe("empty_bubble_text", () => {
  it("flags bubble with empty text", () => {
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ text: "" })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "empty_bubble_text")).toHaveLength(1);
  });

  it("flags bubble with whitespace-only text", () => {
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ text: "   " })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "empty_bubble_text")).toHaveLength(1);
  });

  it("does not flag bubble with text", () => {
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ text: "Hello!" })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "empty_bubble_text")).toHaveLength(0);
  });
});

// ── bubble_outside_safe_area ─────────────────────────────────────────────────

describe("bubble_outside_safe_area", () => {
  // Bubble x/y are panel-relative; the check translates them into page space
  // using the panel's freeform geometry (panel.x/y).
  const freeformPanel = (bubbles: Bubble[]) =>
    makePanel({ x: 100, y: 100, width: 1000, height: 1000, bubbles });

  it("flags pinned bubble whose page position is below the safe margin", () => {
    // page x = 100 + 10 = 110 < SAFE_X (124)
    const pages = [makePage({ layout_mode: "freeform", panels: [freeformPanel([makeBubble({ x: 10, y: 500 })])] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "bubble_outside_safe_area")).toHaveLength(1);
  });

  it("does not flag auto-placed bubble (x=null)", () => {
    const pages = [makePage({ layout_mode: "freeform", panels: [freeformPanel([makeBubble({ x: null, y: null })])] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "bubble_outside_safe_area")).toHaveLength(0);
  });

  it("does not flag pinned bubble safely inside margins", () => {
    // page x = 100 + 200 = 300, well inside safe area
    const pages = [makePage({ layout_mode: "freeform", panels: [freeformPanel([makeBubble({ x: 200, y: 200 })])] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "bubble_outside_safe_area")).toHaveLength(0);
  });

  it("skips the check when panel geometry is unknown (grid mode)", () => {
    // Panel-relative x=50 would falsely flag if compared against page bounds.
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ x: 50, y: 500 })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "bubble_outside_safe_area")).toHaveLength(0);
  });
});

// ── text_too_long ────────────────────────────────────────────────────────────

describe("text_too_long", () => {
  it("flags bubble with 201-character text", () => {
    const longText = "a".repeat(201);
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ text: longText })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "text_too_long")).toHaveLength(1);
  });

  it("does not flag bubble with exactly 200-character text", () => {
    const longText = "a".repeat(200);
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ text: longText })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "text_too_long")).toHaveLength(0);
  });
});

// ── low_contrast ─────────────────────────────────────────────────────────────

describe("low_contrast", () => {
  it("flags black text on black fill", () => {
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ font_color: "#000000", fill_color: "#000000" })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "low_contrast")).toHaveLength(1);
  });

  it("does not flag black text on white fill", () => {
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ font_color: "#000000", fill_color: "#ffffff" })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "low_contrast")).toHaveLength(0);
  });

  it("does not flag when font_color is null", () => {
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ font_color: null, fill_color: "#000000" })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "low_contrast")).toHaveLength(0);
  });

  it("does not flag unparseable color strings (CSS named colors)", () => {
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ font_color: "black", fill_color: "black" })] })] })];
    const images = [makeImageStatus()];
    const issues = detectIssues(pages, images);
    expect(issues.filter((i) => i.type === "low_contrast")).toHaveLength(0);
  });
});

// ── detectIssues ─────────────────────────────────────────────────────────────

describe("detectIssues", () => {
  it("returns empty array for empty pages", () => {
    expect(detectIssues([], [])).toEqual([]);
  });

  it("returns errors before warnings", () => {
    // Panel with no image (error) and unaccepted panel (warning) — no image = error wins ordering
    const pages = [makePage({ panels: [makePanel(), makePanel({ id: "panel2", panel_number: 2 })] })];
    const images = [makeImageStatus({ panel_number: 2, accepted: false })];
    const issues = detectIssues(pages, images);
    expect(issues[0].severity).toBe("error");
  });

  it("issue id is stable for same location", () => {
    const pages = [makePage({ panels: [makePanel({ bubbles: [makeBubble({ text: "" })] })] })];
    const images = [makeImageStatus()];
    const a = detectIssues(pages, images);
    const b = detectIssues(pages, images);
    const aId = a.find((i) => i.type === "empty_bubble_text")?.id;
    const bId = b.find((i) => i.type === "empty_bubble_text")?.id;
    expect(aId).toBe(bId);
    expect(aId).toBeDefined();
  });
});
