import { describe, it, expect } from "vitest";
import { balancedLines, resolvePage, renderOverlay, transformedBounds, type PageLettering, type LetteringStyle } from "@lettering-engine";
import fixture from "./fixtures/lettering.json";
const style = fixture.style as LetteringStyle;
const measure = (text: string, _font: unknown, size: number, spacing = 0) => text.length * size * .5 + Math.max(0, text.length - 1) * spacing;
const state = () => structuredClone(fixture.state) as PageLettering;
describe("shared deterministic lettering engine", () => {
  it("balances word breaks and preserves hard breaks without splitting words", () => {
    const result = balancedLines("One two three four five", 13, text => text.length);
    expect(result.lines.join(" ")).toBe("One two three four five");
    expect(result.lines.at(-1)?.split(" ").length).toBeGreaterThan(1);
    expect(balancedLines("First line\nSecond line", 40, text => text.length).lines).toEqual(["First line", "Second line"]);
    expect(balancedLines("unbreakableword", 3, text => text.length)).toEqual({ lines: ["unbreakableword"], overflow: true });
  });
  it("uses the same stable resolved lines in SVG without mutating source state", () => {
    const original = state(), before = structuredClone(original);
    const a = resolvePage(original, style, measure), b = resolvePage(original, style, measure);
    expect(a).toEqual(b);
    expect(original).toEqual(before);
    expect(a.elements[0].resolved?.height).toBeLessThan(original.elements[0].placement.height);
    const svg = renderOverlay(a, style);
    expect(svg).toContain(a.elements[0].resolved!.lines[0]);
    expect(svg).toContain("EB Garamond");
  });
  it("never shrinks below the configured readable floor", () => {
    const original = state();
    original.elements[0].text_by_locale.source = "Long word. ".repeat(300);
    const element = resolvePage(original, style, measure).elements[0];
    expect(element.resolved?.overflow).toBe(true);
    expect(element.resolved?.font_size).toBe(style.roles.caption.min_font_size);
  });
  it("makes missing translations and unsupported fonts explicit", () => {
    const original = state();
    original.locale = "es";
    expect(resolvePage(original, style, measure).elements[0].resolved?.warnings).toContain("missing_translation");
    original.elements[0].text_by_locale.es = "La puerta se abrió.";
    expect(resolvePage(original, style, measure).elements[0].resolved?.warnings).toEqual([]);
    original.elements[0].text_by_locale.es = "新しい物語";
    expect(resolvePage(original, style, measure).elements[0].resolved?.warnings).toContain("font_script_mismatch");
  });
  it("escapes malicious display text rather than creating markup", () => {
    const original = state();
    original.elements[0].text_by_locale.source = '<script>alert("x")</script>';
    const svg = renderOverlay(resolvePage(original, style, measure), style);
    expect(svg).not.toContain("<script>");
    expect(svg).toContain("&lt;script&gt;");
  });
  it.each([NaN, Infinity, -Infinity])("rejects nonfinite draft geometry (%s)", number => {
    const original = state();
    original.elements[0].placement.x = number;
    expect(() => resolvePage(original, style, measure)).toThrow("placement");
  });
  it("rejects unsafe style values recovered from local storage", () => {
    const original = state();
    original.elements[0].style_override = { ...style.roles.caption, fill: 'url(https://invalid.example)' };
    expect(() => renderOverlay(original, style)).toThrow("ink");
  });
  it("checks rotation/scale in normalized page space", () => {
    const original = state();
    original.elements[0].placement = { x: .8, y: .4, width: .19, height: .2 };
    original.elements[0].rotation = 60;
    original.elements[0].scale = 3;
    const result = resolvePage(original, style, measure);
    expect(result.elements[0].resolved?.warnings).toContain("outside_page");
    const bounds = transformedBounds(result.elements[0], original.canvas_aspect_ratio);
    expect(bounds.x + bounds.width).toBeGreaterThan(1);
  });
});

describe("exact bundled font coverage", () => {
  it.each([
    ["EB Garamond", "Hello 🙂", true],
    ["Comic Neue", "Ж", true],
    ["EB Garamond", "Ж", false],
    ["M PLUS 1p", "こんにちは世界", false],
    ["M PLUS 1p", "你", true],
    ["M PLUS 1p", "한", true],
    ["EB Garamond", "Café — “yes…”\nNext\tline", false],
  ])("validates %s / %s without accepting OS fallback", (font, text, missing) => {
    const input = state(), theme = structuredClone(style);
    theme.roles.caption.font = font as typeof theme.roles.caption.font;
    input.elements[0].text_by_locale.source = text;
    const resolved = resolvePage(input, theme, measure);
    expect(resolved.elements[0].resolved!.warnings.includes("missing_glyphs")).toBe(missing);
  });
});
