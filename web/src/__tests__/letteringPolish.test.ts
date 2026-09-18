import { describe, expect, it } from "vitest";
import { defaultTailTarget, resolvePage, renderOverlay, type LetteringStyle, type PageLettering } from "@lettering-engine";
import fixture from "./fixtures/lettering.json";
const measure = (text: string, _font: string, size: number) => text.length * size * .5;

describe("expressive lettering shapes and provisional pointers", () => {
  it.each([
    { x: .2, y: .2, width: .4, height: .2 },
    { x: .2, y: .9, width: .4, height: .08 },
    { x: .01, y: .01, width: .7, height: .98 },
    { x: .29, y: .01, width: .7, height: .98 },
  ])("places an initial pointer outside a body without leaving the page: %j", rect => {
    const point = defaultTailTarget(rect)!;
    expect(point.x).toBeGreaterThanOrEqual(0);
    expect(point.x).toBeLessThanOrEqual(1);
    expect(point.y).toBeGreaterThanOrEqual(0);
    expect(point.y).toBeLessThanOrEqual(1);
    expect(point.x >= rect.x && point.x <= rect.x + rect.width && point.y >= rect.y && point.y <= rect.y + rect.height).toBe(false);
  });
  it("does not invent an external pointer for a body covering the entire page", () => {
    expect(defaultTailTarget({ x: 0, y: 0, width: 1, height: 1 })).toBeNull();
  });
  it.each(["whisper", "burst", "cloud"] as const)("fits and renders %s deterministically with its own visual treatment", shape => {
    const style = structuredClone(fixture.style) as LetteringStyle;
    const state = structuredClone(fixture.state) as PageLettering;
    const element = state.elements[0];
    const role = shape === "cloud" ? "thought" : "speech";
    element.role = role;
    element.text_by_locale.source = "Come with me!";
    element.placement = { x: .15, y: .15, width: .55, height: .35 };
    element.suggested_placement = { ...element.placement };
    element.tail_target = defaultTailTarget(element.placement);
    style.roles[role].shape = shape;
    const resolved = resolvePage(state, style, measure);
    expect(resolved.elements[0].resolved!.overflow).toBe(false);
    const svg = renderOverlay(resolved, style);
    expect(svg).toBe(renderOverlay(resolvePage(state, style, measure), style));
    expect(svg).not.toMatch(/NaN|Infinity/);
    if (shape === "whisper") expect(svg).toContain("stroke-dasharray");
    else expect(svg).not.toContain("stroke-dasharray");
    expect((svg.match(/data-thought-puff=/g) ?? []).length).toBe(shape === "cloud" ? 3 : 0);
  });
  it("does not reinterpret an existing intentionally tail-free element", () => {
    const style = structuredClone(fixture.style) as LetteringStyle;
    const state = structuredClone(fixture.state) as PageLettering;
    state.elements[0].role = "thought";
    state.elements[0].tail_target = null;
    const resolved = resolvePage(state, style, measure);
    expect(resolved.elements[0].tail_target).toBeNull();
    expect(renderOverlay(resolved, style)).not.toContain("data-thought-puff");
  });
});
