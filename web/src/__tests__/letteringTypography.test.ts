import { describe, expect, it, vi } from "vitest";
import { elementRect, ENGINE_VERSION, renderOverlay, resolvePage, type LetteringStyle, type Measure, type PageLettering } from "@lettering-engine";
import fixture from "./fixtures/lettering.json";
const style = fixture.style as LetteringStyle;
const measure: Measure = (text, _font, size, spacing = 0) => text.length * size * .43 + Math.max(0, text.length - 1) * spacing;
measure.metrics = (text, font, size, spacing, weight) => ({ width: measure(text, font, size, spacing, weight), ascent: size * .7, descent: size * .2 });
function speech(text = "Yes? What is your business, sir?") {
  const draft = structuredClone(fixture.state) as PageLettering;
  const element = draft.elements[0];
  element.role = "speech";
  element.text_by_locale.source = text;
  element.placement = { x: .3, y: .3, width: .33, height: .16 };
  element.tail_target = { x: .65, y: .32 };
  return draft;
}
describe("contour-aware comic typography", () => {
  it("fits both dimensions without destroying the editable reservation", () => {
    const draft = speech(), result = resolvePage(draft, style, measure);
    const element = result.elements[0], rect = elementRect(element);
    expect(element.placement).toEqual(draft.elements[0].placement);
    expect(rect.width).toBeLessThan(element.placement.width);
    expect(rect.height).toBeLessThan(element.placement.height);
    expect(element.resolved?.lines).toHaveLength(2);
    expect(element.resolved?.lines.join(" ")).toBe(draft.elements[0].text_by_locale.source);
    expect(element.resolved?.overflow).toBe(false);
  });
  it("records measured, optically centered baselines and renders them verbatim", () => {
    const result = resolvePage(speech(), style, measure), element = result.elements[0];
    const resolved = element.resolved!, metrics = resolved.line_metrics!;
    const bodyHeight = resolved.height * 1000 / result.canvas_aspect_ratio;
    expect(metrics[0].baseline - metrics[0].ascent).toBeCloseTo(bodyHeight - metrics.at(-1)!.baseline - metrics.at(-1)!.descent, 3);
    expect(metrics[1].baseline - metrics[0].baseline).toBeCloseTo(resolved.line_height, 3);
    const svg = renderOverlay(result, style);
    expect(svg).toContain(`y="${Number((element.placement.y * 1000 / result.canvas_aspect_ratio + metrics[0].baseline).toFixed(4))}"`);
    expect(svg).not.toContain("textLength=");
    expect(svg).not.toContain("lengthAdjust=");
  });
  it.each(["#ffffff", "#ffe7bc", "transparent"])("uses one continuous body-and-tail contour for %s fill", fill => {
    const draft = speech();
    draft.elements[0].style_override = { ...style.roles.speech, fill };
    const svg = renderOverlay(resolvePage(draft, style, measure), style);
    expect((svg.match(/<path /g) || []).length).toBe(1);
    expect(svg).not.toContain("<rect");
    expect(svg).not.toContain("<line");
    expect(svg).toContain(`fill="${fill}"`);
  });
  it("preserves deliberate line breaks and rejects corrupt stored baselines", () => {
    const result = resolvePage(speech("First line\nSecond line"), style, measure);
    expect(result.elements[0].resolved?.lines).toEqual(["First line", "Second line"]);
    result.elements[0].resolved!.line_metrics![0].baseline = NaN;
    expect(() => renderOverlay(result, style)).toThrow("measured line positions");
  });
  it("honors a non-half-unit minimum rather than crossing its readable floor", () => {
    const draft = speech("unbreakable".repeat(20));
    draft.elements[0].style_override = { ...style.roles.speech, min_font_size: 16.3, max_font_size: 17 };
    const resolved = resolvePage(draft, style, measure).elements[0].resolved!;
    expect(resolved.font_size).toBe(16.3);
    expect(resolved.overflow).toBe(true);
  });
  it("reuses layout during drags, but invalidates it for text, locale, size or style edits", () => {
    const counted = vi.fn(measure), draft = speech();
    const first = resolvePage(draft, style, counted);
    counted.mockClear();
    draft.elements[0].placement.x += .01;
    draft.elements[0].tail_target!.x += .01;
    const moved = resolvePage(draft, style, counted);
    expect(counted).not.toHaveBeenCalled();
    expect(moved.elements[0].resolved).toEqual(first.elements[0].resolved);
    // Caller mutation must not poison the cached line arrays/metrics.
    moved.elements[0].resolved!.lines[0] = "tampered";
    expect(resolvePage(draft, style, counted).elements[0].resolved!.lines).toEqual(first.elements[0].resolved!.lines);
    draft.elements[0].text_by_locale.source += " Please.";
    resolvePage(draft, style, counted);
    expect(counted).toHaveBeenCalled();
    counted.mockClear(); draft.elements[0].placement.width -= .01;
    resolvePage(draft, style, counted);
    expect(counted).toHaveBeenCalled();
    counted.mockClear(); draft.locale = "es";
    resolvePage(draft, style, counted);
    expect(counted).toHaveBeenCalled();
    counted.mockClear(); draft.elements[0].style_override = { ...style.roles.speech, padding: 14 };
    resolvePage(draft, style, counted);
    expect(counted).toHaveBeenCalled();
  });
  it("requires an explicit reflow for previous renderer records", () => {
    const result = resolvePage(speech(), style, measure);
    expect(result.elements[0].resolved?.engine_version).toBe(ENGINE_VERSION);
    result.elements[0].resolved!.engine_version = "lettering-svg-v1";
    expect(() => renderOverlay(result, style)).toThrow("laid out");
  });
});
