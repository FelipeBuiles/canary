import { describe, expect, it } from "vitest";
import { ROLE_DEFAULTS, renderOverlay, resolvePage, styleFor, type LetteringElement, type LetteringStyle, type Measure, type PageLettering, type RoleStyle } from "@lettering-engine";
import fixture from "./fixtures/lettering.json";
const EM = "\uE000";
const measure: Measure = (text, _font, size, spacing = 0, _weight, italic) => text.length * size * (italic ? .47 : .43) + Math.max(0, text.length - 1) * spacing;
measure.metrics = (text, font, size, spacing, weight, italic) => ({ width: measure(text, font, size, spacing, weight, italic), ascent: size * .7, descent: size * .2 });
const style = fixture.style as LetteringStyle;
function page(role: LetteringElement["role"], text: string, patch: Partial<RoleStyle> = {}, element: Partial<LetteringElement> = {}): PageLettering {
  const draft = structuredClone(fixture.state) as PageLettering;
  const base = draft.elements[0];
  const placement = { x: .2, y: .2, width: .5, height: .25 };
  draft.elements = [{ ...base, id: "voice", role, text_by_locale: { source: text }, placement, suggested_placement: placement, tail_target: null, style_override: { ...style.roles[role], ...patch }, ...element }];
  return draft;
}
const lay = (draft: PageLettering) => resolvePage(draft, style, measure);
const draw = (draft: PageLettering) => renderOverlay(lay(draft), style);
describe("comic lettering voices", () => {
  it("letters *emphasis* in bold italic without splitting or reordering the words", () => {
    const resolved = lay(page("speech", "You *really* think so?")).elements[0].resolved!;
    expect(resolved.text).toBe("You *really* think so?");
    expect(resolved.lines.join(" ")).toBe(`You ${EM}really${EM} think so?`);
    const svg = draw(page("speech", "You *really* think so?"));
    expect(svg).toContain('<tspan font-style="italic" font-weight="700">really</tspan>');
    expect(svg).not.toContain("*");
  });
  it("marks every word of a multi-word emphasis so each wrapped line stands alone", () => {
    const resolved = lay(page("speech", "I said *get out of here right now* and meant it", {}, { tight_box: false, placement: { x: .1, y: .1, width: .16, height: .5 } })).elements[0].resolved!;
    expect(resolved.lines.length).toBeGreaterThan(2);
    for (const line of resolved.lines) expect((line.match(new RegExp(EM, "g")) ?? []).length % 2).toBe(0);
  });
  it.each([
    ["a literal \\*star", "a literal *star"],
    ["an unpaired * mark", "an unpaired * mark"],
    ["spaced * asterisks * stay", "spaced * asterisks * stay"],
    ["**double** reads as one", `${EM}double${EM} reads as one`],
  ])("keeps %s legible", (text, line) => {
    expect(lay(page("caption", text)).elements[0].resolved!.lines.join(" ")).toBe(line);
  });
  it("measures emphasis as drawn, in the italic face", () => {
    const plain = lay(page("caption", "stress this")).elements[0].resolved!.line_metrics![0].width;
    const stressed = lay(page("caption", "*stress* this")).elements[0].resolved!.line_metrics![0].width;
    expect(stressed).toBeGreaterThan(plain);
  });
  it("capitalizes the lettering, never the canonical copy", () => {
    const resolved = lay(page("speech", "straße, *now*", { text_case: "upper" })).elements[0].resolved!;
    expect(resolved.text).toBe("straße, *now*");
    expect(resolved.lines.join(" ")).toBe(`STRASSE, ${EM}NOW${EM}`);
  });
  it("reserves room for leaning letters and draws the lean", () => {
    const upright = lay(page("sfx", "WHAM")).elements[0].resolved!.line_metrics![0].width;
    const leaning = lay(page("sfx", "WHAM", { skew: 15 })).elements[0].resolved!.line_metrics![0].width;
    expect(leaning).toBeGreaterThan(upright);
    expect(draw(page("sfx", "WHAM", { skew: 15 }))).toContain("skewX(-15)");
  });
  it.each([{ warp: "arc" as const }, { warp: "wave" as const }, { jitter: .5 }])("places letters one by one for %j, deterministically", patch => {
    const draft = page("sfx", "KRAK!", patch);
    const metric = lay(draft).elements[0].resolved!.line_metrics![0];
    expect(metric.glyph_x).toHaveLength(6);
    const svg = draw(draft);
    expect((svg.match(/<text /g) ?? []).length).toBe(5);
    expect(svg).toBe(draw(draft));
    expect(svg).not.toMatch(/NaN|Infinity/);
  });
  it("bounces each element's letters differently", () => {
    const a = draw(page("sfx", "BOOM", { jitter: .6 }));
    const b = draw(page("sfx", "BOOM", { jitter: .6 }, { id: "another" }));
    expect(a.replace(/voice/g, "")).not.toBe(b.replace(/another/g, ""));
  });
  it("fills letters with a content-addressed vertical gradient", () => {
    const svg = draw(page("sfx", "POW", { color: "#ffdd00", gradient_color: "#ff5500" }));
    const id = svg.match(/linearGradient id="([^"]+)"/)![1];
    expect(svg).toContain(`fill="url(#${id})"`);
    expect(svg).toContain('stop-color="#ffdd00"');
    expect(draw(page("sfx", "POW", { color: "#ffdd00", gradient_color: "#00aaff" }))).not.toContain(id);
  });
  it("extrudes in page space with stepped copies, and drops a single shadow", () => {
    const extruded = draw(page("sfx", "ZAP", { shadow: "extrude", shadow_x: 5, shadow_y: 5 }));
    expect((extruded.match(/<g transform="translate\(/g) ?? []).length).toBe(6 + 1);
    const dropped = draw(page("caption", "Later.", { shadow: "drop", shadow_x: 4, shadow_y: 6 }));
    expect(dropped).toContain('<g transform="translate(4 6) translate(');
    expect((dropped.match(/data-balloon-body/g) ?? []).length).toBe(1);
  });
  it("puts the knockout outline behind the balloon, or the letters when there is none", () => {
    const balloon = draw(page("speech", "Hey!", { halo_color: "#ffffff", halo_width: 3 }));
    expect(balloon.indexOf('stroke="#ffffff" stroke-width="7.6"')).toBeLessThan(balloon.indexOf("data-balloon-body"));
    const letters = draw(page("sfx", "Hey!", { halo_color: "#ffffff", halo_width: 3 }));
    expect(letters).toContain('fill="#ffffff" stroke="#ffffff" stroke-width="8.5"');
  });
  it.each(["wavy", "electric", "burst"] as const)("draws %s as one closed body with a tail", shape => {
    const svg = draw(page("speech", "Can you hear me?", { shape }, { tail_target: { x: .3, y: .9 }, tail_bend: .5 }));
    expect((svg.match(/data-balloon-body/g) ?? []).length).toBe(1);
    expect(svg).toContain("100,1050");
  });
  it("bends the tail spine and thought trail without moving the tip", () => {
    const straight = draw(page("thought", "Hmm.", {}, { tail_target: { x: .3, y: .9 } }));
    const bent = draw(page("thought", "Hmm.", {}, { tail_target: { x: .3, y: .9 }, tail_bend: .8 }));
    expect(bent).not.toBe(straight);
    expect((bent.match(/data-thought-puff/g) ?? []).length).toBe(3);
  });
  it("joins linked balloons into one silhouette and drops the link when it cannot merge", () => {
    const draft = page("speech", "Wait.");
    draft.elements.push({ ...draft.elements[0], id: "next", link_to: "voice", placement: { x: .3, y: .5, width: .4, height: .2 }, suggested_placement: { x: .3, y: .5, width: .4, height: .2 } });
    const svg = draw(draft);
    expect(svg).toContain('data-lettering-link="voice"');
    expect(svg).toContain("data-balloon-bridge");
    expect((svg.match(/data-lettering-id=/g) ?? []).length).toBe(2);
    draft.elements[1].style_override = { ...draft.elements[1].style_override!, fill: "transparent" };
    expect(draw(draft)).not.toContain("data-balloon-bridge");
  });
  it.each([["self", "voice"], ["missing", "ghost"]])("rejects a %s link", (_name, target) => {
    expect(() => lay(page("speech", "Hi", {}, { link_to: target }))).toThrow("Invalid balloon link");
  });
  it("rejects linked loops", () => {
    const draft = page("speech", "Hi", {}, { link_to: "b" });
    draft.elements.push({ ...draft.elements[0], id: "b", link_to: "voice" });
    expect(() => lay(draft)).toThrow("Invalid balloon link");
  });
  it("fills tokens missing from an older saved style and never leaks layout seeds into saves", () => {
    const legacy = structuredClone(style);
    for (const key of Object.keys(ROLE_DEFAULTS)) delete (legacy.roles.thought as unknown as Record<string, unknown>)[key];
    const draft = page("thought", "Old style.");
    draft.elements[0].style_override = null;
    expect(() => resolvePage(draft, legacy, measure)).not.toThrow();
    expect(styleFor(draft.elements[0], legacy)).not.toHaveProperty("seed");
    expect(styleFor(draft.elements[0], legacy).text_case).toBe("as_written");
  });
  it("fits a snug rounded caption instead of overflowing into its whole frame", () => {
    const resolved = lay(page("caption", "Later that night", { shape: "round", corner_radius: 14, padding: 8, align: "left" })).elements[0].resolved!;
    expect(resolved.overflow).toBe(false);
    expect(resolved.width!).toBeLessThan(.5);
  });
  it("rejects out-of-range effects before they reach SVG", () => {
    expect(() => lay(page("sfx", "X", { skew: 80 }))).toThrow("Invalid lettering effects");
    expect(() => lay(page("sfx", "X", { gradient_color: "red" }))).toThrow("Invalid lettering ink");
  });
});
