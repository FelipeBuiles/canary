import { renderOverlay, resolvePage, transformedBounds, type LetteringStyle, type Measure, type PageLettering, type RoleName, type RoleStyle } from "@lettering-engine";

/** The real engine, laid out on a one-element page and cropped to it: a tile
 * shows exactly what the page would draw, never an approximation. */
function swatchSVG(role: RoleName, style: RoleStyle, text: string, measure: Measure, tail = true) {
  const placement = { x: .08, y: .08, width: .84, height: .5 };
  const roles = { caption: style, speech: style, thought: style, sfx: style };
  const book: LetteringStyle = { revision: 1, content_sha256: "swatch", label: "Swatch", source_direction: "", roles };
  const state: PageLettering = {
    revision: 1, content_sha256: "", page_number: 1, comic_page_sha256: "0".repeat(64), style_sha256: "swatch", locale: "source",
    canvas_aspect_ratio: 1, reviewed_against_render_revision: null, reviewed_against_image_sha256: null,
    elements: [{ id: "swatch", source_lettering_item_id: null, role, text_by_locale: { source: text }, suggested_placement: placement, placement, hidden: false, style_override: null, tail_target: null, suggested_tail_target: null, rotation: 0, scale: 1, z_index: 0, tight_box: true, resolved: null }],
  };
  try {
    const resolved = resolvePage(state, book, measure);
    const element = resolved.elements[0], box = transformedBounds(element, 1);
    const pointing = tail && (role === "speech" || role === "thought") && style.shape !== "none";
    if (pointing) element.tail_target = { x: box.x + box.width * .3, y: Math.min(.98, box.y + box.height + Math.max(.022, box.height * .45)) };
    // Room for everything drawn outside the body: tail, outlines and shadows.
    const reach = (style.halo_width + Math.max(style.stroke_width, style.text_stroke_width) + 4) / 1000 + (style.warp !== "none" || style.jitter > 0 ? .012 : 0);
    const left = box.x - reach + Math.min(0, style.shadow === "none" ? 0 : style.shadow_x / 1000);
    const top = box.y - reach + Math.min(0, style.shadow === "none" ? 0 : style.shadow_y / 1000);
    const right = box.x + box.width + reach + Math.max(0, style.shadow === "none" ? 0 : style.shadow_x / 1000);
    const bottom = (pointing ? element.tail_target!.y : box.y + box.height) + reach + Math.max(0, style.shadow === "none" ? 0 : style.shadow_y / 1000);
    const view = [left, top, right - left, bottom - top].map(n => Number((n * 1000).toFixed(2))).join(" ");
    // Tiles are artwork only: page hooks (data-*) belong to the real canvas.
    return renderOverlay(resolved, book).replace(/ data-[\w-]+(="[^"]*")?/g, "")
      .replace(/viewBox="[^"]*"/, `viewBox="${view}" preserveAspectRatio="xMidYMid meet"`);
  } catch {
    // A transient, half-typed value is not worth an error inside a tile.
    return "";
  }
}

// Inspector tiles re-render on every drag frame; their artwork only changes with style or words.
const swatches = new WeakMap<Measure, Map<string, string>>();
function cachedSwatch(role: RoleName, style: RoleStyle, text: string, measure: Measure, tail: boolean) {
  if (!swatches.has(measure)) swatches.set(measure, new Map());
  const cache = swatches.get(measure)!, key = JSON.stringify([role, style, text, tail]);
  if (!cache.has(key)) {
    if (cache.size > 400) cache.clear();
    cache.set(key, swatchSVG(role, style, text, measure, tail));
  }
  return cache.get(key)!;
}
export function LetteringSwatch({ role, style, text, measure, tail = true }: { role: RoleName; style: RoleStyle; text: string; measure: Measure; tail?: boolean }) {
  const svg = cachedSwatch(role, style, text, measure, tail);
  return <span className="lettering-swatch" aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />;
}

/** A book's whole voice at a glance: a caption, a speaking balloon and a sound
 * effect, each laid out by the engine and composed like a panel corner. */
function specimenSVG(book: LetteringStyle, words: { caption: string; speech: string; sfx: string }, measure: Measure) {
  const loose = { x: 0, y: 0, width: .34, height: .2 };
  const element = (id: string, role: RoleName, text: string) => ({ id, source_lettering_item_id: null, role, text_by_locale: { source: text }, suggested_placement: loose, placement: loose, hidden: false, style_override: null, tail_target: null, suggested_tail_target: null, rotation: 0, scale: 1, z_index: 0, tight_box: true, resolved: null });
  const state: PageLettering = {
    revision: 1, content_sha256: "", page_number: 1, comic_page_sha256: "0".repeat(64), style_sha256: book.content_sha256, locale: "source",
    canvas_aspect_ratio: 1, reviewed_against_render_revision: null, reviewed_against_image_sha256: null,
    elements: [element("specimen-caption", "caption", words.caption), element("specimen-speech", "speech", words.speech), element("specimen-sfx", "sfx", words.sfx)],
  };
  try {
    const resolved = resolvePage(state, book, measure);
    const [caption, speech, sfx] = resolved.elements;
    // Sizes are known now; positions never change a fit, so compose freely.
    const size = (e: typeof caption) => ({ width: e.resolved!.width ?? e.placement.width, height: e.resolved!.height });
    const c = size(caption), s = size(speech), f = size(sfx);
    caption.placement = { ...caption.placement, x: .02, y: .02 };
    speech.placement = { ...speech.placement, x: .02 + Math.max(.04, c.width * .45), y: .02 + c.height + .014 };
    speech.tail_target = { x: speech.placement.x + s.width * .25, y: speech.placement.y + s.height + .045 };
    sfx.placement = { ...sfx.placement, x: Math.min(.3, speech.placement.x + s.width * .62), y: speech.placement.y + s.height + .01 };
    sfx.rotation = -7;
    const boxes = [caption, speech, sfx].map(e => transformedBounds(e, 1));
    const left = Math.min(...boxes.map(b => b.x)) - .012, top = Math.min(...boxes.map(b => b.y)) - .012;
    const right = Math.max(...boxes.map(b => b.x + b.width), sfx.placement.x + f.width) + .02;
    const bottom = Math.max(...boxes.map(b => b.y + b.height), speech.tail_target.y) + .02;
    const view = [left, top, right - left, bottom - top].map(n => Number((n * 1000).toFixed(2))).join(" ");
    return renderOverlay(resolved, book).replace(/ data-[\w-]+(="[^"]*")?/g, "")
      .replace(/viewBox="[^"]*"/, `viewBox="${view}" preserveAspectRatio="xMidYMid meet"`);
  } catch {
    return "";
  }
}
export function LetteringSpecimen({ book, words, measure }: { book: LetteringStyle; words: { caption: string; speech: string; sfx: string }; measure: Measure }) {
  if (!swatches.has(measure)) swatches.set(measure, new Map());
  const cache = swatches.get(measure)!, key = JSON.stringify(["specimen", book.roles, words]);
  if (!cache.has(key)) cache.set(key, specimenSVG(book, words, measure));
  return <span className="lettering-swatch" aria-hidden="true" dangerouslySetInnerHTML={{ __html: cache.get(key)! }} />;
}
