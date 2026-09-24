import { describe, expect, it } from "vitest";
import { clearOfHeads, placementChecks, tailTowardHead, type LetteringElement, type PageLettering, type PlacementEvidence, type Rect } from "@lettering-engine";

// Placement is the visible box here (no snug box), so geometry is exact.
function balloon(id: string, placement: Rect, patch: Partial<LetteringElement> = {}): LetteringElement {
  return {
    id, source_lettering_item_id: id, role: "speech", text_by_locale: { source: "Words." },
    suggested_placement: placement, placement, hidden: false, style_override: null,
    tail_target: null, suggested_tail_target: null, rotation: 0, scale: 1, z_index: 0,
    tight_box: false, resolved: { engine_version: "x", locale: "source", text: "Words.", lines: ["Words."], font_size: 20, line_height: 24, height: placement.height, overflow: false, warnings: [] },
    ...patch,
  };
}
function page(...elements: LetteringElement[]): PageLettering {
  return { revision: 1, content_sha256: "", page_number: 1, comic_page_sha256: "a".repeat(64), style_sha256: "", locale: "source", canvas_aspect_ratio: 2 / 3, elements, reviewed_against_render_revision: null, reviewed_against_image_sha256: null };
}
const TOP = { x: .01, y: .01, width: .98, height: .48 }, BOTTOM = { x: .01, y: .51, width: .98, height: .48 };
const HERO = { id: "figure_001", entity_id: "hero", x: .2, y: .2, width: .1, height: .12 };
const VILLAIN = { id: "figure_002", entity_id: "villain", x: .7, y: .2, width: .1, height: .12 };
function evidence(patch: Partial<PlacementEvidence> = {}): PlacementEvidence {
  return { panels: [TOP, BOTTOM], heads: [HERO, VILLAIN], stray_lettering: [], in_world_text: [], speakers: { a: "hero", b: "villain" }, ...patch };
}
const codes = (checks: ReturnType<typeof placementChecks>) => checks.map(check => `${check.element_id}:${check.code}`);

describe("placement checks from a page read", () => {
  it("is quiet when balloons sit clear of faces with tails at their speakers", () => {
    const a = balloon("a", { x: .05, y: .03, width: .2, height: .08 }, { tail_target: { x: .25, y: .2 } });
    const b = balloon("b", { x: .72, y: .03, width: .2, height: .08 }, { tail_target: { x: .75, y: .2 } });
    expect(placementChecks(page(a, b), evidence())).toEqual([]);
  });

  it("flags a balloon crossing a gutter and offers to fit it inside its panel", () => {
    const checks = placementChecks(page(balloon("a", { x: .1, y: .44, width: .2, height: .1 })), evidence({ heads: null }));
    expect(codes(checks)).toEqual(["a:crosses_panel"]);
    const fixed = checks[0].fix!.placement!;
    expect(fixed.y + fixed.height).toBeLessThanOrEqual(TOP.y + TOP.height);
    expect(fixed.x).toBeCloseTo(.1);
  });

  it("without a page read only gutter checks run", () => {
    const covering = balloon("a", { x: .18, y: .2, width: .2, height: .1 });
    expect(placementChecks(page(covering), evidence({ heads: null }))).toEqual([]);
    expect(codes(placementChecks(page(covering), evidence()))).toContain("a:covers_face");
  });

  it("still reports drawn-in text when a read predates faces", () => {
    const mark = { text: "BANG", x: .5, y: .6, width: .1, height: .05 };
    const a = balloon("a", { x: .6, y: .03, width: .2, height: .08 }, { tail_target: { x: .75, y: .2 } });
    expect(codes(placementChecks(page(a), evidence({ heads: null, stray_lettering: [mark] })))).toEqual(["null:stray_lettering"]);
  });

  it("moves a balloon off a face by the smallest step inside the panel", () => {
    const checks = placementChecks(page(balloon("a", { x: .18, y: .2, width: .2, height: .1 }, { tail_target: { x: .25, y: .2 } })), evidence());
    const fix = checks.find(check => check.code === "covers_face")!.fix!.placement!;
    const moved = { ...fix, width: .2, height: .1 };
    expect(moved.x + moved.width <= HERO.x || moved.x >= HERO.x + HERO.width || moved.y + moved.height <= HERO.y || moved.y >= HERO.y + HERO.height).toBe(true);
    expect(fix.y).toBeGreaterThanOrEqual(TOP.y);
  });

  it("aims tails at the labelled speaker, not at whoever is nearest", () => {
    const a = balloon("a", { x: .6, y: .03, width: .2, height: .08 }, { tail_target: { x: .75, y: .2 } });
    const checks = placementChecks(page(a), evidence());
    expect(codes(checks)).toEqual(["a:tail_misses_speaker"]);
    expect(checks[0].fix!.tail_target).toEqual(tailTowardHead(a.placement, HERO));
    const missing = placementChecks(page(balloon("a", { x: .05, y: .03, width: .2, height: .08 })), evidence());
    expect(missing.map(check => [check.code, check.severity])).toEqual([["tail_missing", "consider"]]);
  });

  it("uses a lone unlabelled head only for the panel's only speaker", () => {
    const stranger = { ...HERO, entity_id: null };
    const a = balloon("a", { x: .05, y: .03, width: .2, height: .08 }, { tail_target: { x: .9, y: .45 } });
    expect(codes(placementChecks(page(a), evidence({ heads: [stranger] })))).toEqual(["a:tail_misses_speaker"]);
    const b = balloon("b", { x: .6, y: .03, width: .2, height: .08 }, { tail_target: { x: .9, y: .45 } });
    expect(placementChecks(page(a, b), evidence({ heads: [stranger] }))).toEqual([]);
  });

  it("reports exposed lettering in the art, but not marks the author already covered", () => {
    const mark = { text: "BANG", x: .5, y: .6, width: .1, height: .05 };
    expect(codes(placementChecks(page(), evidence({ stray_lettering: [mark] })))).toEqual(["null:stray_lettering"]);
    const cover = balloon("c", { x: .48, y: .58, width: .16, height: .1 }, { role: "caption" });
    expect(placementChecks(page(cover), evidence({ stray_lettering: [mark] })).filter(check => check.code === "stray_lettering")).toEqual([]);
  });

  it("suggests not hiding in-world writing such as signs", () => {
    const sign = { text: "EXIT", x: .45, y: .05, width: .1, height: .05 };
    const checks = placementChecks(page(balloon("c", { x: .42, y: .03, width: .2, height: .08 }, { role: "caption" })), evidence({ in_world_text: [sign] }));
    expect(checks.map(check => [check.code, check.severity, check.text])).toEqual([["covers_in_world_text", "consider", "EXIT"]]);
  });

  it("keeps parity with the seeding rules in placement.py", () => {
    // The same literals are asserted in test_lettering_placement.py.
    expect(tailTowardHead({ x: .05, y: .03, width: .2, height: .08 }, { x: .2, y: .2, width: .1, height: .12 })).toEqual({ x: .2, y: .2 });
    expect(tailTowardHead({ x: .15, y: .15, width: .3, height: .3 }, { x: .2, y: .2, width: .1, height: .12 })).toEqual({ x: .25, y: .26 });
    const cleared = clearOfHeads({ x: .18, y: .2, width: .2, height: .1 }, [{ x: .2, y: .2, width: .1, height: .12 }], { x: .03, y: .024, width: .94, height: .452 })!;
    expect(cleared.x).toBeCloseTo(.18);
    expect(cleared.y).toBeCloseTo(.088);  // Above the face beats the longer step to its right.
  });
});
