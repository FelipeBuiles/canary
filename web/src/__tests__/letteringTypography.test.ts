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
  it("fits a single-word ellipse near the minimum padded area instead of flattening it", () => {
    const draft = speech("Extraordinary");
    const role = { ...style.roles.speech, shape: "ellipse" as const };
    draft.elements[0].style_override = role;
    const result = resolvePage(draft, style, measure), resolved = result.elements[0].resolved!;
    const padding = role.padding + role.stroke_width / 2 + role.text_stroke_width / 2;
    const ink = resolved.line_metrics![0];
    const minimumArea = 2 * (ink.width + 2 * padding) * (ink.ascent + ink.descent + 2 * padding);
    const area = resolved.width! * 1000 * resolved.height * 1000 / result.canvas_aspect_ratio;
    expect(resolved.overflow).toBe(false);
    expect(resolved.font_size).toBe(role.max_font_size);
    expect(area).toBeLessThan(minimumArea * 1.05);
  });
  it.each(["ellipse", "cloud"] as const)("fits %s by its chosen shape and preserves manual dimensions", shape => {
    const draft = speech("First line\nSecond line");
    const element = draft.elements[0];
    element.style_override = { ...style.roles.speech, shape };
    const speechLayout = resolvePage(draft, style, measure).elements[0].resolved!;
    element.role = "caption";
    element.tail_target = null;
    expect(resolvePage(draft, style, measure).elements[0].resolved).toEqual(speechLayout);
    element.tight_box = false;
    const resolved = resolvePage(draft, style, measure).elements[0].resolved!;
    expect(resolved.overflow).toBe(false);
    expect(resolved.lines.join(" ")).toBe("First line Second line");
    expect(resolved.lines.map((_, index) => resolved.lines.slice(0, index + 1).join(" "))).toContain("First line");
    expect(resolved.font_size).toBe(element.style_override.max_font_size);
    expect(resolved.width).toBe(element.placement.width);
    expect(resolved.height).toBe(element.placement.height);
  });
  it("varies cloud lobes and inward bends while keeping a closed contour", () => {
    const draft = speech();
    draft.elements[0].style_override = { ...style.roles.speech, shape: "cloud" };
    draft.elements[0].tail_target = null;
    const svg = renderOverlay(resolvePage(draft, style, measure), style);
    const path = new DOMParser().parseFromString(svg, "image/svg+xml").querySelector("path")!;
    const values = path.getAttribute("d")!.match(/-?\d+(?:\.\d+)?/g)!.map(Number);
    const curves: number[][] = [];
    let start = values.slice(0, 2);
    for (let i = 2; i < values.length; i += 6) {
      curves.push([...start, ...values.slice(i, i + 6)]);
      start = values.slice(i + 4, i + 6);
    }
    const spans = curves.map(c => Math.hypot(c[6] - c[0], c[7] - c[1]));
    expect(Math.max(...spans) / Math.min(...spans)).toBeGreaterThan(2);
    const bends: number[] = [];
    for (let i = 0; i < curves.length; i++) {
      const a = curves[i], b = curves[(i + 1) % curves.length];
      const incoming = [a[6] - a[4], a[7] - a[5]], outgoing = [b[2] - b[0], b[3] - b[1]];
      expect(a.slice(6)).toEqual(b.slice(0, 2));
      const cosine = (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / (Math.hypot(...incoming) * Math.hypot(...outgoing));
      // Unequal lobes meet at inward bends without gaps or degenerate tangents.
      expect(Number.isFinite(cosine)).toBe(true);
      expect(cosine).toBeGreaterThan(-1);
      expect(cosine).toBeLessThan(.9999);
      const cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0];
      bends.push(cross);
      // Sample curvature inside each cubic as well as its concave joins.
      for (const t of [.25, .5, .75]) {
        const u = 1 - t;
        const dx = 3*u*u*(a[2]-a[0])+6*u*t*(a[4]-a[2])+3*t*t*(a[6]-a[4]);
        const dy = 3*u*u*(a[3]-a[1])+6*u*t*(a[5]-a[3])+3*t*t*(a[7]-a[5]);
        const ddx = 6*u*(a[4]-2*a[2]+a[0])+6*t*(a[6]-2*a[4]+a[2]);
        const ddy = 6*u*(a[5]-2*a[3]+a[1])+6*t*(a[7]-2*a[5]+a[3]);
        bends.push(dx*ddy-dy*ddx);
      }
    }
    expect(bends.some(cross => cross < 0)).toBe(true);
    expect(bends.some(cross => cross > 0)).toBe(true);
  });
  it("gives clouds stable individual silhouettes with scallops on every side", () => {
    const draft = speech();
    const element = draft.elements[0];
    element.style_override = { ...style.roles.speech, shape: "cloud" };
    element.tail_target = null;
    const outline = () => {
      const svg = renderOverlay(resolvePage(draft, style, measure), style);
      return new DOMParser().parseFromString(svg, "image/svg+xml")
        .querySelector("[data-balloon-body]")!.getAttribute("d")!;
    };
    const first = outline();
    expect(outline()).toBe(first);
    element.placement.x += .1;
    expect(outline()).toBe(first);
    element.id += "-other";
    expect(outline()).not.toBe(first);
    const values = first.match(/-?\d+(?:\.\d+)?/g)!.map(Number);
    const endpoints = [values.slice(0, 2)];
    for (let i = 2; i < values.length; i += 6) endpoints.push(values.slice(i + 4, i + 6));
    const center = [0, 1].map(axis =>
      (Math.min(...endpoints.map(p => p[axis])) + Math.max(...endpoints.map(p => p[axis]))) / 2);
    // Multiple scallop joins in all four quadrants, not just decorated corners.
    for (const x of [-1, 1]) for (const y of [-1, 1])
      expect(endpoints.filter(p => (p[0]-center[0])*x>0 && (p[1]-center[1])*y>0).length).toBeGreaterThanOrEqual(2);
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
