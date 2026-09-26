/**
 * Canary's sole lettering geometry/layout renderer. Imported by the Pages editor
 * and executed unchanged in Chromium by the server. No network or model calls.
 * Geometry is normalized; typography uses a 1000-unit vector page width.
 */
import { FONT_COVERAGE } from "./font-coverage.mjs";

export const ENGINE_VERSION = "lettering-svg-v12";
export const FONT_FILES = Object.freeze({
  "Comic Neue": "ComicNeue-Bold.ttf",
  "EB Garamond": "EBGaramond-SemiBold.ttf",
  "Bangers": "Bangers-Regular.ttf",
  "Special Elite": "SpecialElite-Regular.ttf",
  "M PLUS 1p": "MPLUS1p-Bold.ttf",
  "Fredoka": "Fredoka-SemiBold.ttf",
  "Orbitron": "Orbitron-Bold.ttf",
  "Bungee": "Bungee-Regular.ttf",
  "Baloo 2": "Baloo2-SemiBold.ttf",
  "Exo 2": "Exo2-SemiBold.ttf",
  "Shrikhand": "Shrikhand-Regular.ttf",
  "Creepster": "Creepster-Regular.ttf",
});
// A font being loaded does not mean it owns the requested glyph. Browser
// fallback is machine-dependent, so validate against the exact bundled cmaps.
const coverage = new Map();
function hasMissingGlyphs(font, text) {
  if (!coverage.has(font)) {
    let previous = -1;
    const ranges = FONT_COVERAGE[font].split(",").map(pair => {
      const [gap, length = "0"] = pair.split(".");
      const start = previous + 1 + parseInt(gap, 36);
      previous = start + parseInt(length, 36);
      return [start, previous];
    });
    coverage.set(font, ranges);
  }
  const ranges = coverage.get(font);
  return [...text].some(character => {
    if (/^[\r\n\t]$/.test(character)) return false;
    const cp = character.codePointAt(0);
    let low = 0, high = ranges.length - 1;
    while (low <= high) {
      const mid = (low + high) >>> 1, [start, end] = ranges[mid];
      if (cp < start) high = mid - 1;
      else if (cp > end) low = mid + 1;
      else return false;
    }
    return true;
  });
}
const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[c]);
const number = (value) => Number(value.toFixed(4));
const safeLocale = (locale) => {
  try { return locale === "source" ? "en" : Intl.getCanonicalLocales(locale)[0]; }
  catch { return "en"; }
};
export function fontCSS(base = "/static/fonts") {
  return Object.entries(FONT_FILES).map(([family, file]) =>
    `@font-face{font-family:"${family}";src:url("${base}/${file}") format("truetype");font-weight:normal;font-style:normal;font-display:block;}`,
  ).join("\n");
}
export async function loadFonts() {
  await Promise.all(Object.keys(FONT_FILES).map((font) => document.fonts.load(`24px "${font}"`)));
  await document.fonts.ready;
  if (Object.keys(FONT_FILES).some((font) => !document.fonts.check(`24px "${font}"`))) {
    throw new Error("Comic fonts did not load. Retry before saving or exporting.");
  }
}
export function canvasMeasure() {
  const context = document.createElement("canvas").getContext("2d");
  if (!context) throw new Error("Text measurement is unavailable in this browser.");
  const cache = new Map();
  // Emphasis is the bundled face's synthesized oblique, measured as drawn.
  const metrics = (text, font, size, spacing = 0, weight = 400, italic = false) => {
    const key = `${font}\0${size}\0${spacing}\0${weight}\0${italic ? 1 : 0}\0${text}`;
    if (cache.has(key)) return cache.get(key);
    context.font = `${italic ? "italic " : ""}${weight} ${size}px "${font}"`;
    const measured = context.measureText(text);
    const value = {
      width: measured.width + Math.max(0, [...text].length - 1) * spacing,
      ascent: Math.max(0, measured.actualBoundingBoxAscent),
      descent: Math.max(0, measured.actualBoundingBoxDescent),
    };
    if (cache.size > 12000) cache.clear();
    cache.set(key, value);
    return value;
  };
  const measure = (...args) => metrics(...args).width;
  measure.metrics = metrics;
  return measure;
}

/** Word units preserve unbreakable words; CJK can break at grapheme boundaries.
 * Explicit newlines are hard breaks. Words are NEVER split to fake a fit.
 * *Emphasis* is marked inside each unit, so any run of units is a valid line.
 */
function unitsFor(paragraph, locale) {
  const { clean: text, mask } = parseEmphasis(paragraph.trim().replace(/[\t ]+/g, " "));
  if (!text) return [];
  if (/\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}/u.test(text)) {
    // Intl word segmentation keeps Latin words intact in mixed-script copy.
    const combined = [];
    for (const part of new Intl.Segmenter(safeLocale(locale), { granularity: "word" }).segment(text)) {
      const unit = marked(part.segment, mask, part.index);
      if (/^[\s、。，．！？!?：:；;）)」』】]+$/u.test(part.segment) && combined.length) {
        combined[combined.length - 1] += unit;
      } else combined.push(unit);
    }
    return { units: combined, separator: "" };
  }
  let index = 0;
  return { units: text.split(" ").map(word => { const unit = marked(word, mask, index); index += word.length + 1; return unit; }), separator: " " };
}

/** Balanced DP line breaking. Minimize line count first, then raggedness and
 * short orphan endings. Deterministic tie-breaking always takes the earlier cut.
 */
export function balancedLines(text, width, measure, locale = "source") {
  const output = [];
  let overflow = false;
  for (const paragraph of text.replace(/\r\n?/g, "\n").split("\n")) {
    const tokenized = unitsFor(paragraph, locale);
    if (!tokenized.units?.length) { output.push(""); continue; }
    const { units, separator } = tokenized;
    if (units.length > 600) return { lines: [text], overflow: true };
    const n = units.length;
    const cost = Array(n + 1).fill(Infinity), next = Array(n).fill(0);
    cost[n] = 0;
    for (let start = n - 1; start >= 0; start--) {
      for (let end = start + 1; end <= n; end++) {
        const candidate = units.slice(start, end).join(separator).trim();
        const used = measure(candidate);
        if (used > width && end > start + 1) break;
        const excess = Math.max(0, used - width) / Math.max(1, width);
        const ragged = Math.max(0, width - used) / Math.max(1, width);
        const loneEnding = end === n && end - start === 1 && start > 0 ? 0.8 : 0;
        const score = 5 + excess * excess * 1000 + ragged * ragged + loneEnding + cost[end];
        if (score < cost[start]) { cost[start] = score; next[start] = end; }
      }
    }
    for (let start = 0; start < n;) {
      const end = next[start] || start + 1;
      const line = units.slice(start, end).join(separator).trim();
      output.push(line);
      if (measure(line) > width + 0.01) overflow = true;
      start = end;
    }
  }
  return { lines: output, overflow };
}
/** Tokens a saved style may predate (drafts, older fixtures). The server's
 * Pydantic model fills the same defaults. */
export const ROLE_DEFAULTS = Object.freeze({
  text_case: "as_written", tail_width: 1, halo_color: "transparent", halo_width: 0,
  shadow: "none", shadow_color: "#181818", shadow_x: 4, shadow_y: 4,
  gradient_color: "transparent", warp: "none", warp_amount: .5, jitter: 0, skew: 0,
});
/** The element's effective, saveable style tokens. */
export function styleFor(element, style) {
  return { ...ROLE_DEFAULTS, ...(element.style_override || style.roles[element.role]) };
}
export function roleFor(element, style) {
  const role = styleFor(element, style);
  // Stable per bubble/style, independent of movement, edits and render order.
  return ["cloud", "burst", "electric"].includes(role.shape) || role.jitter > 0
    ? {...role, seed: element.id + ":" + style.content_sha256} : role;
}
export function translationStatus(element, locale) {
  if (!Object.hasOwn(element.text_by_locale, locale)) return "missing";
  if (locale === "source" || element.translation_sources?.[locale] === element.text_by_locale.source) return "current";
  return "stale";
}
export function textFor(element, locale) {
  return element.text_by_locale[locale] ?? element.text_by_locale.source;
}
export function elementRect(element) {
  return { ...element.placement,
    width: element.tight_box && element.resolved?.width ? element.resolved.width : element.placement.width,
    height: element.tight_box && element.resolved ? element.resolved.height : element.placement.height };
}
/** Provisional pointer, outside the allocated body and inside the page.
 * This is an editing affordance, NOT image-based speaker detection. */
export function defaultTailTarget(rect) {
  const {x,y,width:w,height:h}=rect;
  if (1-y-h>.025) return {x:x+w*.28,y:y+h+Math.min(.06,(1-y-h)*.7)};
  if (y>.025) return {x:x+w*.28,y:y-Math.min(.06,y*.7)};
  if (1-x-w>.025) return {x:x+w+Math.min(.06,(1-x-w)*.7),y:y+h*.6};
  if (x>.025) return {x:x-Math.min(.06,x*.7),y:y+h*.6};
  return null;
}

/* Placement hints from a page read (one vision look at the base art).
 * Evidence for the author, never visual acceptance: nothing here marks
 * placement reviewed. Heads come from the text check's same call. */
const PLACEMENT_GAP=.012, PANEL_MARGIN_X=.02, PANEL_MARGIN_Y=.014;
const overlapArea=(a,b)=>Math.max(0,Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y));
const intersects=(a,b)=>a.x<b.x+b.width && b.x<a.x+a.width && a.y<b.y+b.height && b.y<a.y+a.height;
const inside=(r,p)=>p.x>=r.x && p.x<=r.x+r.width && p.y>=r.y && p.y<=r.y+r.height;
const centreOf=r=>({x:r.x+r.width/2,y:r.y+r.height/2});
function panelIndex(panels, point) {
  const hit=panels.findIndex(p=>inside(p,point));
  if (hit>=0 || !panels.length) return hit;
  const gap=p=>Math.max(p.x-point.x,0,point.x-p.x-p.width)**2+Math.max(p.y-point.y,0,point.y-p.y-p.height)**2;
  return panels.reduce((best,p,i)=>gap(p)<gap(panels[best])?i:best,0);
}
function innerBounds(panel) {
  const b={x:panel.x+PANEL_MARGIN_X,y:panel.y+PANEL_MARGIN_Y,width:panel.width-2*PANEL_MARGIN_X,height:panel.height-2*PANEL_MARGIN_Y};
  return b.width<.02 || b.height<.02 ? panel : b;
}
/** Tail tip on the edge of the speaker's head nearest the balloon.
 * Keep in parity with placement.py toward_head. */
export function tailTowardHead(body, head) {
  const c=centreOf(body);
  let x=Math.min(Math.max(c.x,head.x),head.x+head.width), y=Math.min(Math.max(c.y,head.y),head.y+head.height);
  if (inside(body,{x,y})) ({x,y}=centreOf(head));
  return {x:Math.min(1,Math.max(0,x)),y:Math.min(1,Math.max(0,y))};
}
/** Nearest top-left for ``rect`` that covers none of ``obstacles`` inside
 * ``bounds``, or null. Keep in parity with placement.py clear_of. */
export function clearOfHeads(rect, obstacles, bounds, vertical=true) {
  if (!obstacles.some(o=>intersects(rect,o))) return {x:rect.x,y:rect.y};
  const candidates=obstacles.flatMap(o=>[
    {x:o.x-rect.width-PLACEMENT_GAP,y:rect.y},{x:o.x+o.width+PLACEMENT_GAP,y:rect.y},
    ...(vertical?[{x:rect.x,y:o.y-rect.height-PLACEMENT_GAP},{x:rect.x,y:o.y+o.height+PLACEMENT_GAP}]:[])]);
  const fits=candidates.filter(c=>c.x>=bounds.x-1e-9 && c.y>=bounds.y-1e-9 && c.x+rect.width<=bounds.x+bounds.width+1e-9 &&
    c.y+rect.height<=bounds.y+bounds.height+1e-9 && !obstacles.some(o=>intersects({...rect,...c},o)));
  if (!fits.length) return null;
  return fits.reduce((best,c)=>(c.x-rect.x)**2+(c.y-rect.y)**2<(best.x-rect.x)**2+(best.y-rect.y)**2?c:best);
}
const moved=(element,from,to)=>({placement:{...element.placement,
  x:Math.min(1-element.placement.width,Math.max(0,element.placement.x+to.x-from.x)),
  y:Math.min(1-element.placement.height,Math.max(0,element.placement.y+to.y-from.y))}});
/** Same rule as placement.py speaker_heads: a labelled head wins; a lone
 * unlabelled head counts only for the panel's only speaker. */
function speakerHead(element, local, speakers, voices) {
  const speaker=speakers[element.source_lettering_item_id ?? element.id];
  if (!speaker) return null;
  let own=local.filter(h=>h.entity_id===speaker);
  if (!own.length && local.length===1 && local[0].entity_id===null && voices.size===1 && voices.has(speaker)) own=local;
  return own.length ? own.reduce((a,b)=>b.width*b.height>a.width*a.height?b:a) : null;
}
/** Live placement hints for a laid-out page. ``evidence.heads`` is null when
 * the art has no page read yet; panel checks still run from gutters. */
export function placementChecks(state, evidence) {
  const aspect=state.canvas_aspect_ratio, panels=evidence.panels ?? [], heads=evidence.heads ?? [];
  const speakers=evidence.speakers ?? {}, checks=[];
  const visible=state.elements.filter(e=>!e.hidden && e.resolved).map(e=>{
    const box=transformedBounds(e,aspect);
    return {element:e,box,panel:panelIndex(panels,centreOf(box))};
  });
  const voices=new Map();
  for (const v of visible) {
    const who=speakers[v.element.source_lettering_item_id ?? v.element.id];
    if (who) voices.set(v.panel,(voices.get(v.panel) ?? new Set()).add(who));
  }
  for (const {element,box,panel:index} of visible) {
    const panel=panels[index];
    if (panel && !(box.x>=panel.x-.004 && box.y>=panel.y-.004 && box.x+box.width<=panel.x+panel.width+.004 && box.y+box.height<=panel.y+panel.height+.004)) {
      const inner=innerBounds(panel), to={x:Math.min(Math.max(box.x,inner.x),inner.x+inner.width-box.width),y:Math.min(Math.max(box.y,inner.y),inner.y+inner.height-box.height)};
      checks.push({code:"crosses_panel",severity:"fix",element_id:element.id,mark:panel,
        fix:box.width<=inner.width && box.height<=inner.height ? moved(element,box,to) : null});
    }
    if (!panel) continue;
    // Heads are unknown (null) before a page read, or on a read that predates them.
    const inner=innerBounds(panel), local=heads.filter(h=>panelIndex(panels,centreOf(h))===index);
    const covered=local.filter(h=>overlapArea(box,h)>=.2*h.width*h.height);
    if (covered.length) {
      const to=clearOfHeads(box,local,inner);
      checks.push({code:"covers_face",severity:"fix",element_id:element.id,mark:covered[0],fix:to?moved(element,box,to):null});
    }
    // A joined balloon speaks through its lead's tail.
    if (evidence.heads!==null && ["speech","thought"].includes(element.role) && !element.link_to) {
      const head=speakerHead(element,local,speakers,voices.get(index) ?? new Set());
      if (head) {
        const tail=tailTowardHead(box,head), reach={x:head.x-head.width*.35,y:head.y-head.height*.35,width:head.width*1.7,height:head.height*1.7};
        if (!element.tail_target) checks.push({code:"tail_missing",severity:"consider",element_id:element.id,mark:head,fix:{tail_target:tail}});
        else if (!inside(reach,element.tail_target)) checks.push({code:"tail_misses_speaker",severity:"fix",element_id:element.id,mark:head,fix:{tail_target:tail}});
      }
    }
    for (const text of evidence.in_world_text ?? []) {
      if (overlapArea(box,text)>=.3*text.width*text.height) {
        const to=clearOfHeads(box,[...local,text],inner);
        checks.push({code:"covers_in_world_text",severity:"consider",element_id:element.id,mark:text,text:text.text,fix:to?moved(element,box,to):null});
      }
    }
  }
  for (const mark of evidence.stray_lettering ?? []) {
    // Lettering the author already laid over the mark hides it; only exposed marks count.
    if (!visible.some(v=>overlapArea(v.box,mark)>=.6*mark.width*mark.height))
      checks.push({code:"stray_lettering",severity:"fix",element_id:null,mark,text:mark.text,fix:null});
  }
  return checks;
}
export function transformedBounds(element, aspect) {
  const r = elementRect(element), h = 1000 / aspect;
  const width = r.width * 1000 * element.scale, height = r.height * h * element.scale;
  const radians = element.rotation * Math.PI / 180;
  const spanX = (Math.abs(Math.cos(radians)) * width + Math.abs(Math.sin(radians)) * height) / 1000;
  const spanY = (Math.abs(Math.sin(radians)) * width + Math.abs(Math.cos(radians)) * height) / h;
  return { x: r.x + r.width / 2 - spanX / 2, y: r.y + r.height / 2 - spanY / 2, width: spanX, height: spanY };
}
/** Reject corrupt recovery drafts before putting any attributes into SVG. The
 * authenticated server independently validates the same state with Pydantic. */
const SHAPES=["box","round","balloon","ellipse","cloud","whisper","burst","wavy","electric","none"];
const INK=/^(#[0-9a-fA-F]{6}|transparent)$/;
function validateEditableState(state, style) {
  const finite=(n)=>typeof n === "number" && Number.isFinite(n);
  const within=(n,lo,hi)=>finite(n) && n>=lo && n<=hi;
  const rect=(r)=>r && [r.x,r.y,r.width,r.height].every(finite) && r.x>=0 && r.y>=0 && r.width>0 && r.height>0 && r.x+r.width<=1.000001 && r.y+r.height<=1.000001;
  if (!finite(state.canvas_aspect_ratio) || state.canvas_aspect_ratio<=.1 || state.canvas_aspect_ratio>=10 || !Array.isArray(state.elements) || state.elements.length>200) throw new Error("Invalid lettering draft geometry.");
  if (typeof state.locale!=="string" || !/^(source|[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)$/.test(state.locale)) throw new Error("Invalid lettering language.");
  const byId=new Map(state.elements.map(e=>[e.id,e]));
  for (const element of state.elements) {
    const role=roleFor(element,style);
    if (!rect(element.placement) || !rect(element.suggested_placement) || ![element.rotation,element.scale,element.z_index].every(finite) || element.scale<.25 || element.scale>3 || Math.abs(element.rotation)>180) throw new Error("Invalid lettering placement.");
    if (!element.text_by_locale || typeof element.text_by_locale.source!=="string" || Object.values(element.text_by_locale).some(text=>typeof text!=="string"||text.length>10000)) throw new Error("Invalid lettering copy.");
    if (element.tail_target && (![element.tail_target.x,element.tail_target.y].every(finite) || element.tail_target.x<0 || element.tail_target.x>1 || element.tail_target.y<0 || element.tail_target.y>1)) throw new Error("Invalid lettering tail.");
    if (element.tail_bend!=null && !within(element.tail_bend,-1,1)) throw new Error("Invalid lettering tail.");
    if (element.link_to!=null && (typeof element.link_to!=="string" || element.link_to===element.id || !byId.has(element.link_to))) throw new Error("Invalid balloon link.");
    if (!role || !Object.hasOwn(FONT_FILES,role.font) || !SHAPES.includes(role.shape) || !["left","center","right"].includes(role.align)) throw new Error("Invalid lettering style.");
    if ([role.color,role.fill,role.stroke,role.text_stroke,role.halo_color,role.shadow_color,role.gradient_color].some(color=>typeof color!=="string"||!INK.test(color))) throw new Error("Invalid lettering ink.");
    if (![role.min_font_size,role.max_font_size,role.line_height,role.stroke_width,role.padding,role.corner_radius,role.letter_spacing,role.text_stroke_width].every(finite) || role.min_font_size<12 || role.max_font_size>180 || role.min_font_size>role.max_font_size || role.line_height<=0 || ![400,700].includes(role.font_weight??400)) throw new Error("Invalid typography settings.");
    if (!["as_written","upper"].includes(role.text_case) || !["none","drop","extrude"].includes(role.shadow) || !["none","arc","wave"].includes(role.warp)
      || !within(role.tail_width,.4,2.5) || !within(role.halo_width,0,16) || !within(role.shadow_x,-40,40) || !within(role.shadow_y,-40,40)
      || !within(role.warp_amount,-1,1) || !within(role.jitter,0,1) || !within(role.skew,-30,30)) throw new Error("Invalid lettering effects.");
  }
  // Linked balloons form chains or fans toward earlier balloons, never loops.
  for (const element of state.elements) {
    const seen=new Set();
    for (let cursor=element; cursor?.link_to; cursor=byId.get(cursor.link_to)) {
      if (seen.has(cursor.id)) throw new Error("Invalid balloon link.");
      seen.add(cursor.id);
    }
  }
}

/* Comic copy conventions. *Words in asterisks* are lettered in bold italic,
 * the letterer's stress. Each word unit carries its own private-use markers, so
 * every candidate line stays self-contained. "\*" and unpaired asterisks are
 * literal. Measurement and rendering read the same runs. */
const EM="\uE000";
function parseEmphasis(text) {
  const chars=[];
  for (let i=0;i<text.length;i++) {
    if (text[i]==="\\" && text[i+1]==="*") { chars.push({c:"*"}); i++; }
    else if (text[i]==="*" && chars.at(-1)?.marker && text[i-1]==="*") continue; // **bold** reads as *bold*
    else chars.push({c:text[i],marker:text[i]==="*"});
  }
  let clean="", emphasis=false;
  const mask=[];
  for (let i=0;i<chars.length;i++) {
    const ch=chars[i];
    if (ch.marker && !emphasis && chars[i+1] && !/\s/.test(chars[i+1].c)) {
      let close=-1;
      for (let j=i+2;j<chars.length && chars[j].c!=="\n";j++)
        if (chars[j].marker && !/\s/.test(chars[j-1].c)) { close=j; break; }
      if (close>0) { emphasis=true; chars[close].closes=true; continue; }
    } else if (ch.closes) { emphasis=false; continue; }
    clean+=ch.c; mask.push(emphasis);
  }
  return {clean,mask};
}
function marked(text, mask, start) {
  let out="", on=false;
  for (let i=0;i<text.length;i++) {
    if (!!mask[start+i]!==on) { out+=EM; on=!on; }
    out+=text[i];
  }
  return on ? out+EM : out;
}
function runsOf(line) {
  return line.split(EM).map((text,i)=>({text,em:i%2===1})).filter(run=>run.text);
}
const segmenter=typeof Intl!=="undefined" && Intl.Segmenter ? new Intl.Segmenter("en",{granularity:"grapheme"}) : null;
const graphemes=text=>segmenter ? [...segmenter.segment(text)].map(part=>part.segment) : [...text];
function glyphsOf(line) {
  return runsOf(line).flatMap(run=>graphemes(run.text).map(text=>({text,em:run.em})));
}
// Lean (skew) and bouncing letters need a little horizontal room. Nominal cap
// proportions keep this identical during fitting and rendering.
const NOMINAL_ASCENT=.76, NOMINAL_DESCENT=.22;
function lineSlack(role, size) {
  const lean=Math.tan((role.skew||0)*Math.PI/180), bounce=(role.jitter||0)*size*.08;
  return {
    total:Math.abs(lean)*size*(NOMINAL_ASCENT+NOMINAL_DESCENT)+2*bounce,
    left:(lean>0 ? NOMINAL_DESCENT*size*lean : -NOMINAL_ASCENT*size*lean)+bounce,
  };
}
// Warped and bouncing letters travel above and below their baseline.
function textReach(role, size) {
  const warp=role.warp==="arc" ? .5 : role.warp==="wave" ? .45 : 0;
  return warp*Math.abs(role.warp_amount??0)*size+(role.jitter||0)*size*.16;
}
function rawWidth(line, role, size, measure) {
  const runs=runsOf(line);
  let width=0;
  for (const run of runs) width+=measure(run.text, role.font, size, role.letter_spacing, run.em ? 700 : role.font_weight ?? 400, run.em);
  return width+Math.max(0,runs.length-1)*role.letter_spacing;
}
function lineWidth(line, role, size, measure) {
  const width=rawWidth(line,role,size,measure);
  return width ? width+lineSlack(role,size).total : 0;
}
// Optical text extents, not em-box guesses. Tests can inject a width-only
// measurer; production records Chromium's actual glyph ascent and descent.
function inkMetrics(text, role, size, measure) {
  const runs=runsOf(text);
  let ascent=0, descent=0, measured=false;
  for (const run of runs.length ? runs : [{text:"",em:false}]) {
    const ink=measure.metrics?.(run.text, role.font, size, role.letter_spacing, run.em ? 700 : role.font_weight ?? 400, run.em);
    if (ink) { measured=true; ascent=Math.max(ascent,ink.ascent); descent=Math.max(descent,ink.descent); }
  }
  return { width:lineWidth(text,role,size,measure), ascent:measured ? ascent : size*.74, descent:measured ? descent : size*.2 };
}
/** Start offset of every glyph plus the line's end, for letters placed one by
 * one (warp, bounce). Prefix measurement keeps kerning. */
function glyphStops(line, role, size, measure) {
  const glyphs=glyphsOf(line);
  if (!glyphs.length || glyphs.length>400) return undefined;
  const prefix=count=>{
    let text="", on=false;
    for (const glyph of glyphs.slice(0,count)) {
      if (glyph.em!==on) { text+=EM; on=glyph.em; }
      text+=glyph.text;
    }
    return rawWidth(on ? text+EM : text,role,size,measure);
  };
  return [0,...glyphs.slice(1).map((_,i)=>number(prefix(i+1)+role.letter_spacing)),number(prefix(glyphs.length))];
}

const curved = (shape) => ["balloon", "ellipse", "cloud", "whisper", "burst", "wavy", "electric"].includes(shape);
// Toothed and rippled balloons fit their copy inside this share of the plain
// balloon contour, the innermost reach of their valleys.
const INNER = { wavy:.9, electric:.85 };
const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
const mix = (a, b, t) => [a[0] + (b[0]-a[0])*t, a[1] + (b[1]-a[1])*t];
function splitCurve(c, t) {
  const a=mix(c[0],c[1],t), b=mix(c[1],c[2],t), d=mix(c[2],c[3],t);
  const e=mix(a,b,t), f=mix(b,d,t), p=mix(e,f,t);
  return [[c[0],a,e,p],[p,f,d,c[3]]];
}
function curvePoint(c, t) {
  const u=1-t, a=u*u*u, b=3*u*u*t, d=3*u*t*t, e=t*t*t;
  return [a*c[0][0]+b*c[1][0]+d*c[2][0]+e*c[3][0],
    a*c[0][1]+b*c[1][1]+d*c[2][1]+e*c[3][1]];
}
function curvePart(c, start, end) {
  const left = end < 1 ? splitCurve(c,end)[0] : c;
  return start > 0 ? splitCurve(left,start/end)[1] : left;
}
function seededRandom(seed) {
  let hash=2166136261;
  for (const char of seed) hash=Math.imul(hash^char.charCodeAt(0),16777619);
  return ()=>{
    hash+=0x6D2B79F5;
    let n=Math.imul(hash^(hash>>>15),hash|1);
    n^=n+Math.imul(n^(n>>>7),n|61);
    return ((n^(n>>>14))>>>0)/4294967296;
  };
}
// Normalize actual extrema, so selection bounds and export stay exact.
function normalizeCurves(raw) {
  const limits=[0,1].map(axis=>{
    const values=raw.flatMap(c=>[0,1,...curveExtrema(c,axis)].map(t=>curvePoint(c,t)[axis]));
    return [Math.min(...values),Math.max(...values)];
  });
  return raw.map(c=>c.map(p=>p.map((v,axis)=>{
    const [min,max]=limits[axis]; return 2*(v-min)/(max-min)-1;
  })));
}
// Seeded unequal scallops around the entire perimeter. Each bubble keeps its
// silhouette across redraws; fitting and SVG rendering share the exact curves.
const shapeCache=new Map();
function cached(key, build) {
  if (shapeCache.has(key)) return shapeCache.get(key);
  const value=build();
  if (shapeCache.size>=256) shapeCache.clear();
  shapeCache.set(key,value);
  return value;
}
function cloudGeometry(seed="cloud") {
  return cached("cloud\0"+seed,()=>{
    const random=seededRandom(seed);
    const count=13+Math.floor(random()*3), phase=random()*Math.PI*2;
    const steps=Array.from({length:count},()=>.7+random()*.6);
    const total=steps.reduce((a,b)=>a+b,0);
    let angle=phase;
    const points=steps.map(step=>{
      const p=[Math.cos(angle),Math.sin(angle)]
        .map(v=>Math.sign(v)*Math.pow(Math.abs(v),.65));
      angle+=step/total*Math.PI*2;
      return p;
    });
    const raw=points.map((p,i)=>{
      const q=points[(i+1)%count], mid=mix(p,q,.5);
      const length=Math.hypot(...mid), bulge=.11+random()*.10;
      const normal=mid.map(v=>v/length*bulge);
      const first=.23+random()*.14, second=.63+random()*.14;
      return [p,mix(p,q,first).map((v,j)=>v+normal[j]),
        mix(p,q,second).map((v,j)=>v+normal[j]),q];
    });
    const curves=normalizeCurves(raw);
    const bands=curves.flatMap(c=>{
      const cuts=[0,...curveExtrema(c,0),...curveExtrema(c,1),1].sort((a,b)=>a-b);
      return cuts.slice(1).flatMap((end,i)=>end-cuts[i]>1e-10 ? [curvePart(c,cuts[i],end)] : []);
    });
    return {curves,bands};
  });
}
const straight=(p,q)=>[p,mix(p,q,1/3),mix(p,q,2/3),q];
// The plain balloon's quarter curve, turned through each quadrant clockwise.
const BALLOON_K=.68;
function balloonPoint(fraction) {
  const f=((fraction%1)+1)%1, quadrant=Math.floor(f*4), t=f*4-quadrant;
  let [x,y]=curvePoint([[0,-1],[BALLOON_K,-1],[1,-BALLOON_K],[1,0]],t);
  for (let i=0;i<quadrant;i++) [x,y]=[-y,x];
  return [x,y];
}
/** Shout: irregular straight spikes. Every valley stays outside the 0.78
 * ellipse that burst rows are fitted into; tests sample this invariant. */
function burstGeometry(seed="burst") {
  return cached("burst\0"+seed,()=>{
    const random=seededRandom(seed);
    const tips=12+Math.floor(random()*5), phase=random()*Math.PI*2;
    const steps=Array.from({length:tips},()=>.8+random()*.4), total=steps.reduce((a,b)=>a+b,0);
    const polar=(angle,radius)=>[Math.cos(angle)*radius,Math.sin(angle)*radius];
    let angle=phase;
    const points=steps.flatMap(step=>{
      const span=step/total*Math.PI*2;
      const pair=[polar(angle,.92+random()*.08),polar(angle+span*(.4+random()*.2),.8+random()*.05)];
      angle+=span;
      return pair;
    });
    return {curves:normalizeCurves(points.map((p,i)=>straight(p,points[(i+1)%points.length])))};
  });
}
/** Rippled and toothed balloons are laid out by real arc length, so the
 * pattern stays even on wide or tall bodies. Depth is a share of the shorter
 * radius: never deeper than the INNER share the copy was fitted into. */
function edgePattern(shape, w, h, seed="") {
  return cached(`${shape}\0${seed}\0${number(w)}\0${number(h)}`,()=>{
    const rx=w/2, ry=h/2, samples=480, random=seededRandom(seed || shape);
    const outline=Array.from({length:samples},(_,i)=>{const [x,y]=balloonPoint(i/samples); return [x*rx,y*ry];});
    const lengths=[0];
    for (let i=1;i<=samples;i++) lengths.push(lengths[i-1]+Math.hypot(...outline[i%samples].map((v,j)=>v-outline[i-1][j])));
    const total=lengths[samples], short=Math.min(rx,ry);
    const along=distance=>{
      let i=lengths.findIndex(l=>l>=distance); if (i<=0) i=1;
      const t=(distance-lengths[i-1])/Math.max(1e-9,lengths[i]-lengths[i-1]);
      const a=outline[i-1], b=outline[i%samples], point=mix(a,b,t);
      const tangent=[b[0]-a[0],b[1]-a[1]], size=Math.hypot(...tangent)||1;
      return {point,normal:[tangent[1]/size,-tangent[0]/size]};
    };
    const inward=({point,normal},depth)=>[(point[0]-normal[0]*depth)/rx,(point[1]-normal[1]*depth)/ry];
    if (shape==="electric") {
      const count=2*Math.max(12,Math.round(total/(short*.34)));
      const points=Array.from({length:count},(_,i)=>inward(along(i/count*total),i%2 ? short*(.1+random()*.04) : 0));
      return {curves:normalizeCurves(points.map((p,i)=>straight(p,points[(i+1)%count])))};
    }
    const waves=Math.max(8,Math.round(total/(short*.9))), count=waves*8;
    const points=Array.from({length:count},(_,i)=>inward(along(i/count*total),short*.08*(1-Math.cos(2*Math.PI*i/8))/2));
    // Uniform Catmull-Rom: smooth, and exactly through each sample.
    return {curves:normalizeCurves(points.map((p,i)=>{
      const a=points[(i-1+count)%count], q=points[(i+1)%count], b=points[(i+2)%count];
      return [p,[p[0]+(q[0]-a[0])/6,p[1]+(q[1]-a[1])/6],[q[0]-(b[0]-p[0])/6,q[1]-(b[1]-p[1])/6],q];
    }))};
  });
}
function silhouette(role, w, h) {
  if (role.shape==="cloud") return cloudGeometry(role.seed);
  if (role.shape==="burst") return burstGeometry(role.seed);
  return edgePattern(role.shape,w,h,role.seed);
}
function curveExtrema(c, axis) {
  const [p,q,r,s]=c.map(point=>point[axis]);
  const a=-p+3*q-3*r+s, b=2*(p-2*q+r), d=q-p;
  if (Math.abs(a)<1e-12) return Math.abs(b)<1e-12 ? [] : [-d/b].filter(t=>t>0 && t<1);
  const discriminant=b*b-4*a*d;
  return discriminant<0 ? [] : [(-b-Math.sqrt(discriminant))/(2*a),(-b+Math.sqrt(discriminant))/(2*a)].filter(t=>t>0 && t<1);
}
function cloudFactor(top,bottom,seed) {
  if (top<=-1 || bottom>=1) return 0;
  let factor=1;
  for (const c of cloudGeometry(seed).bands) {
    const low=Math.max(top,Math.min(c[0][1],c[3][1])), high=Math.min(bottom,Math.max(c[0][1],c[3][1]));
    if (low>high) continue;
    for (const y of [low,high]) {
      let lo=0,hi=1;
      const ascending=c[3][1]>=c[0][1];
      for (let i=0;i<20;i++) {
        const t=(lo+hi)/2;
        if ((curvePoint(c,t)[1]<y)===ascending) lo=t; else hi=t;
      }
      // The cloud is asymmetric: reserve the narrower side of each row band
      // so centered, left- and right-aligned copy all clear the inward joins.
      factor=Math.min(factor,Math.abs(curvePoint(c,(lo+hi)/2)[0]));
    }
  }
  return Math.max(0,factor-1e-6);
}
// The rounded oval uses four smooth cubics. Layout queries this SAME curve,
// rather than reserving an arbitrary rectangular 30% inset for all lines.
function ovalFactor(distance, shape) {
  if (distance >= 1) return 0;
  const k=shape === "ellipse" ? .5522847498 : BALLOON_K;
  const c=[[0,-1],[k,-1],[1,-k],[1,0]];
  let lo=0, hi=1;
  for (let i=0;i<18;i++) {
    const t=(lo+hi)/2;
    if (-curvePoint(c,t)[1]>distance) lo=t; else hi=t;
  }
  return curvePoint(c,(lo+hi)/2)[0];
}
function rowSpace(role, height, top, bottom) {
  if (role.shape==="burst") {
    // A conservative ellipse inside every spike valley, including the full
    // padded row height. Never fit against the outer tips of a shout balloon.
    const distance=Math.max(Math.abs(top-height/2),Math.abs(bottom-height/2));
    return {factor:.78*ovalFactor(distance/(height*.39),"ellipse"),inset:0};
  }
  if (role.shape==="cloud") return {factor:cloudFactor(top/(height/2)-1,bottom/(height/2)-1,role.seed),inset:0};
  const distance=Math.max(Math.abs(top-height/2),Math.abs(bottom-height/2));
  if (INNER[role.shape]) {
    const inner=INNER[role.shape];
    return { factor: inner*ovalFactor(distance/(height/2*inner),"balloon"), inset: 0 };
  }
  if (curved(role.shape)) return { factor: ovalFactor(distance/(height/2),role.shape), inset: 0 };
  const radius=Math.min(role.corner_radius,height/2);
  const edge=Math.min(top,height-bottom);
  const inset=role.shape !== "none" && radius>0 && edge<radius
    ? radius-Math.sqrt(Math.max(0,radius*radius-(radius-edge)**2)) : 0;
  return { factor: 1, inset };
}
function rowGeometry(role, height, count, ascent, descent, leading, reach=0) {
  const baseline=(height-(ascent+descent+(count-1)*leading))/2+ascent;
  const padding=["ellipse","cloud","burst"].includes(role.shape) ? role.padding+role.stroke_width/2+role.text_stroke_width/2 : 0;
  return Array.from({length:count},(_,i)=>{
    const y=baseline+i*leading;
    return { baseline:y, ...rowSpace(role,height,y-ascent-padding-reach,y+descent+padding+reach) };
  });
}
/** Exact-count word partitioning: minimize the body width needed to contain
 * every row in its curved band. The first/last lines naturally shorten while
 * the middle can open out. No character stretching, word splitting or case changes.
 */
function contourLines(tokens, separator, rows, padding, measure, size, locale) {
  const n=tokens.length, count=rows.length;
  let costs=Array(n+1).fill(Infinity), penalties=Array(n+1).fill(0); costs[0]=0;
  const cuts=[];
  for (let row=0;row<count;row++) {
    const next=Array(n+1).fill(Infinity), quality=Array(n+1).fill(0), prev=Array(n+1).fill(-1);
    const {factor,inset}=rows[row];
    if (factor<=0) return null;
    for (let start=row;start<n;start++) {
      if (!Number.isFinite(costs[start])) continue;
      for (let end=start+1;end<=n-(count-row-1);end++) {
        const width=(measure(tokens.slice(start,end).join(separator).trim())+2*(padding+inset))/factor;
        const needed=Math.max(costs[start],width);
        const weakEnd=end<n && safeLocale(locale).startsWith("en")
          && /^(a|an|the|my|your|his|her|our|their|of|to|and|or|with)$/i.test(tokens[end-1]);
        const penalty=penalties[start]+(weakEnd ? size*.6 : 0);
        if (needed+penalty < next[end]+quality[end]-1e-7) {
          next[end]=needed; quality[end]=penalty; prev[end]=start;
        }
      }
    }
    costs=next; penalties=quality; cuts.push(prev);
  }
  if (!Number.isFinite(costs[n])) return null;
  const lines=[];
  for (let row=count-1,end=n;row>=0;row--) {
    const start=cuts[row][end];
    if (start<0) return null;
    lines.unshift(tokens.slice(start,end).join(separator).trim()); end=start;
  }
  return {lines,width:costs[n]};
}
function composeLayout(lines, role, size, width, height, measure) {
  const ink=lines.map(line=>inkMetrics(line,role,size,measure));
  const ascent=Math.max(...ink.map(m=>m.ascent)), descent=Math.max(...ink.map(m=>m.descent));
  const leading=size*role.line_height, reach=textReach(role,size);
  const rows=rowGeometry(role,height,lines.length,ascent,descent,leading,reach);
  const padding=role.padding+role.stroke_width/2+role.text_stroke_width/2;
  const line_metrics=ink.map((m,i)=>{
    const row=rows[i], inset=width*(1-row.factor)/2+padding+row.inset;
    const x=role.align==="left" ? inset : role.align==="right" ? width-inset-m.width : (width-m.width)/2;
    return { x:number(x), baseline:number(row.baseline), width:number(m.width), ascent:number(m.ascent), descent:number(m.descent) };
  });
  const overflow=ink.some((m,i)=>m.width+2*(padding+rows[i].inset)>width*rows[i].factor+.05)
    || ascent+descent+(lines.length-1)*leading+2*(padding+reach)>height+.05;
  return {lines,width,height,line_metrics,overflow};
}
function fitBalloon(text, role, size, maxWidth, maxHeight, measure, locale, tight) {
  const padding=role.padding+role.stroke_width/2+role.text_stroke_width/2, reach=textReach(role,size);
  const all=inkMetrics(text.replace(/\n/g," "),role,size,measure), leading=size*role.line_height;
  const optimizeOval=["ellipse","cloud","burst"].includes(role.shape);
  const clearance=curved(role.shape) && !optimizeOval ? size*.55 : 0;
  const naturalHeight=count=>(all.ascent+all.descent+(count-1)*leading+2*(padding+reach)+clearance)/(INNER[role.shape] ?? 1);
  const heightsFor=count=>{
    if (!tight) return [maxHeight];
    const natural=naturalHeight(count);
    if (!optimizeOval) return [natural];
    if (natural>=maxHeight) return [];
    // The area optimum of an ellipse around a rectangular ink block is at
    // sqrt(2) times its height. Nearby bounded candidates allow different
    // wraps and cloud valleys to compete without forcing a wide, flat oval.
    return [...new Set([1.12,1.25,Math.SQRT2,1.6,1.85,2.2].map(factor=>Math.min(maxHeight,natural*factor))),maxHeight]
      .filter((height,index,heights)=>heights.indexOf(height)===index);
  };
  const tokenized=unitsFor(text,locale);
  const widths=new Map();
  const widthOf=line=>{
    if (!widths.has(line)) widths.set(line,lineWidth(line,role,size,measure));
    return widths.get(line);
  };
  const candidates=[];
  // Hard breaks are editorial decisions. Keep them, including blank lines.
  if (/[\r\n]/.test(text) || (tokenized.units?.length ?? 0)>100) {
    for (let step=5;step<=16;step++) {
      const result=balancedLines(text,Math.max(1,maxWidth*step/16-2*padding),widthOf,locale);
      if (result.overflow) continue;
      for (const height of heightsFor(result.lines.length)) {
        const rows=rowGeometry(role,height,result.lines.length,all.ascent,all.descent,leading,reach);
        if (rows.some(row=>row.factor<=0)) continue;
        const width=Math.max(...result.lines.map((line,i)=>(widthOf(line)+2*(padding+rows[i].inset))/rows[i].factor));
        candidates.push({lines:result.lines,width,height});
      }
    }
  } else {
    const {units=[],separator=" "}=tokenized;
    const maxLines=Math.min(24,units.length,Math.max(1,Math.floor((maxHeight-naturalHeight(1))/leading)+1));
    for (let count=1;count<=maxLines;count++) {
      for (const height of heightsFor(count)) {
        const rows=rowGeometry(role,height,count,all.ascent,all.descent,leading,reach);
        const candidate=contourLines(units,separator,rows,padding,widthOf,size,locale);
        if (candidate) candidates.push({...candidate,height});
      }
    }
  }
  let best=null, bestScore=Infinity;
  for (const candidate of candidates) {
    // A tiny tolerance avoids changing wraps because of floating-point rounding.
    const width=tight ? Math.min(maxWidth,candidate.width+.08) : maxWidth;
    if (candidate.width>maxWidth || candidate.height>maxHeight) continue;
    const layout=composeLayout(candidate.lines,role,size,width,candidate.height,measure);
    if (layout.overflow) continue;
    const natural=optimizeOval ? candidate.height : naturalHeight(candidate.lines.length), ratio=candidate.width/natural;
    const loneEnding=candidate.lines.length>1 && text.trim().split(/\s+/).length>4
      && candidate.lines.at(-1).trim().split(/\s+/).length===1 ? .45 : 0;
    const aspectPenalty=optimizeOval
      ? Math.max(0,ratio-3)**2*.2+Math.max(0,(role.shape==="cloud" ? 1.45 : 1.3)-ratio)**2*(role.shape==="cloud" ? 1.1 : .5)
      : Math.max(0,ratio-3.7)**2*.25+Math.max(0,2.3-ratio)**2*2;
    // Do not gain a few square units by turning a short thought into a tower
    // of isolated words. Author-supplied hard breaks remain authoritative.
    const cloudOrphans=role.shape==="cloud" && !/[\r\n]/.test(text) && text.trim().split(/\s+/).length>=4
      ? candidate.lines.filter(line=>line.trim().split(/\s+/).length===1).length*.5 : 0;
    const cloudSideSpace=role.shape==="cloud"
      ? Math.max(0,candidate.width/(Math.max(...candidate.lines.map(widthOf))+2*padding)-1.12)**2*3 : 0;
    const score=candidate.width*natural*(1+loneEnding+aspectPenalty+cloudOrphans+cloudSideSpace);
    if (score<bestScore) { bestScore=score; best=layout; }
  }
  return best;
}
function fitText(element, role, text, size, pageHeight, measure, locale) {
  const w=element.placement.width*1000,h=element.placement.height*pageHeight;
  if ((["speech","thought"].includes(element.role) || curved(role.shape)) && text.trim()) {
    const result=fitBalloon(text,role,size,w,h,measure,locale,element.tight_box);
    if (result) return result;
    return null;
  }
  const padding=role.padding+role.stroke_width/2+role.text_stroke_width/2;
  const result=balancedLines(text,w-2*padding,line=>lineWidth(line,role,size,measure),locale);
  const ink=result.lines.map(line=>inkMetrics(line,role,size,measure));
  const ascent=Math.max(...ink.map(m=>m.ascent)), descent=Math.max(...ink.map(m=>m.descent)), leading=size*role.line_height;
  const height=ascent+descent+(result.lines.length-1)*leading+2*(padding+textReach(role,size));
  // Rounded corners pinch the first and last rows: a snug box reserves that inset too.
  const rows=rowGeometry(role,element.tight_box?Math.max(1,height):h,result.lines.length,ascent,descent,leading,textReach(role,size));
  const width=Math.max(.1,...ink.map((m,i)=>m.width+2*rows[i].inset))+2*padding;
  if (result.overflow || height>h+.01 || width>w+.01) return null;
  const layout=composeLayout(result.lines,role,size,element.tight_box?width:w,element.tight_box?Math.max(1,height):h,measure);
  return layout.overflow ? null : layout;
}
const lettersOneByOne=role=>role.warp!=="none" || role.jitter>0;
// Move/tail/selection changes must not rerun word partitioning on every frame.
// Per-measurer caches cannot outlive an editor session or cross font-load contexts.
const layoutCaches = new WeakMap();
export function resolvePage(state, style, measure) {
  validateEditableState(state,style);
  const pageHeight = 1000 / state.canvas_aspect_ratio;
  if (!layoutCaches.has(measure)) layoutCaches.set(measure, new Map());
  const cache = layoutCaches.get(measure);
  return { ...state, elements: state.elements.map((element) => {
    const role = roleFor(element, style), text = textFor(element, state.locale);
    // Case is a lettering convention, not a copy edit: canonical words stay as written.
    const display = role.text_case==="upper" ? text.toLocaleUpperCase(safeLocale(state.locale)) : text;
    const warnings = [];
    if (!text.trim()) warnings.push("empty_copy");
    if (hasMissingGlyphs(role.font, display)) warnings.push("missing_glyphs");
    const translation = translationStatus(element, state.locale);
    if (translation !== "current") warnings.push(`${translation}_translation`);
    const key=JSON.stringify([role,element.role,display,state.locale,element.placement.width,
      element.placement.height,element.tight_box,pageHeight]);
    let cached=cache.get(key);
    if (!cached) {
      let result=null, size=role.max_font_size;
      while (true) {
        result=fitText(element,role,display,size,pageHeight,measure,state.locale);
        if (result || size===role.min_font_size) break;
        size=Math.max(role.min_font_size,size-.5);
      }
      if (!result) {
        // Preserve every word, visibly flag overflow, and stop at the readable floor.
        const width=element.placement.width*1000, height=element.placement.height*pageHeight;
        const broken=balancedLines(display,Math.max(1,width*.75-2*role.padding),line=>lineWidth(line,role,size,measure),state.locale);
        result={...composeLayout(broken.lines,role,size,width,height,measure),overflow:true};
      }
      if (lettersOneByOne(role)) result={...result,line_metrics:result.line_metrics.map((metric,i)=>{
        const stops=glyphStops(result.lines[i],role,size,measure);
        return stops ? {...metric,glyph_x:stops} : metric;
      })};
      if (cache.size>=256) cache.clear();
      cached={result,size}; cache.set(key,cached);
    }
    const {result,size}=cached;
    const resolved = {
      engine_version: ENGINE_VERSION, locale: state.locale, text,
      lines:[...result.lines], font_size:number(size), line_height:number(size*role.line_height),
      width:result.width/1000, height:result.height/pageHeight,
      line_metrics:result.line_metrics.map(line=>({...line,...(line.glyph_x ? {glyph_x:[...line.glyph_x]} : {})})), overflow:result.overflow, warnings,
    };
    const next = { ...element, resolved };
    const bounds = transformedBounds(next, state.canvas_aspect_ratio);
    if (bounds.x < -0.0001 || bounds.y < -0.0001 || bounds.x + bounds.width > 1.0001 || bounds.y + bounds.height > 1.0001) {
      resolved.overflow = true; warnings.push("outside_page");
    }
    if (/\p{Script=Arabic}|\p{Script=Hebrew}|\p{Script=Devanagari}|\p{Script=Thai}/u.test(text)) {
      warnings.push("unsupported_script"); resolved.overflow = true;
    }
    if (/\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}/u.test(text) && role.font !== "M PLUS 1p") warnings.push("font_script_mismatch");
    return next;
  }) };
}
function contour(role,w,h) {
  const rx=w/2,ry=h/2,k=role.shape==="ellipse"?.5522847498:BALLOON_K;
  if (["ellipse","balloon","whisper"].includes(role.shape)) return [
    [[rx,0],[rx+k*rx,0],[w,ry-k*ry],[w,ry]],
    [[w,ry],[w,ry+k*ry],[rx+k*rx,h],[rx,h]],
    [[rx,h],[rx-k*rx,h],[0,ry+k*ry],[0,ry]],
    [[0,ry],[0,ry-k*ry],[rx-k*rx,0],[rx,0]],
  ];
  if (["cloud","burst","wavy","electric"].includes(role.shape)) return silhouette(role,w,h).curves.map(c=>c.map(([x,y])=>[rx+x*rx,ry+y*ry]));
  const r=clamp(role.corner_radius,0,Math.min(rx,ry)), e=.5522847498*r;
  return [straight([r,0],[w-r,0]),[[w-r,0],[w-r+e,0],[w,r-e],[w,r]],
    straight([w,r],[w,h-r]),[[w,h-r],[w,h-r+e],[w-r+e,h],[w-r,h]],
    straight([w-r,h],[r,h]),[[r,h],[r-e,h],[0,h-r+e],[0,h-r]],
    straight([0,h-r],[0,r]),[[0,r],[0,r-e],[r-e,0],[r,0]]];
}
const pointText=p=>p.map(number).join(",");
const curveText=c=>`C${pointText(c[1])} ${pointText(c[2])} ${pointText(c[3])}`;
function contourTable(curves) {
  const table=[{length:0,param:0,point:curves[0][0]}];
  let length=0, previous=curves[0][0];
  curves.forEach((c,index)=>{
    for (let i=1;i<=24;i++) {
      const point=curvePoint(c,i/24);
      length+=Math.hypot(point[0]-previous[0],point[1]-previous[1]);
      table.push({length,param:index+i/24,point}); previous=point;
    }
  });
  return table;
}
function paramAtLength(table,length) {
  const total=table.at(-1).length;
  length=((length%total)+total)%total;
  const end=table.findIndex(p=>p.length>=length);
  if (end<=0) return 0;
  const a=table[end-1],b=table[end];
  return a.param+(b.param-a.param)*(length-a.length)/(b.length-a.length);
}
function attachPoint(curves,table,target,w,h) {
  const center=[w/2,h/2], d=[target[0]-center[0],target[1]-center[1]];
  const cross=p=>(p[0]-center[0])*d[1]-(p[1]-center[1])*d[0];
  for (let i=1;i<table.length;i++) {
    const a=table[i-1],b=table[i];
    if (cross(a.point)*cross(b.point)>0) continue;
    const index=Math.min(curves.length-1,Math.floor(a.param+1e-8));
    let lo=a.param-index,hi=b.param-index;
    for (let j=0;j<20;j++) {
      const mid=(lo+hi)/2;
      if (cross(curvePoint(curves[index],lo))*cross(curvePoint(curves[index],mid))<=0) hi=mid; else lo=mid;
    }
    const t=(lo+hi)/2,p=curvePoint(curves[index],t);
    if ((p[0]-center[0])*d[0]+(p[1]-center[1])*d[1]<=0) continue;
    if (Math.hypot(...d)<=Math.hypot(p[0]-center[0],p[1]-center[1])+1) return null;
    const fraction=(t+index-a.param)/(b.param-a.param);
    return {point:p,length:a.length+(b.length-a.length)*fraction};
  }
  return null;
}
/** The tail's spine: a quadratic from the root to the tip, bowed sideways by
 * ``bend`` (-1..1). Thought puffs and both tail edges follow it. */
function tailSpine(root,target,bend) {
  const axis=[target[0]-root[0],target[1]-root[1]], length=Math.hypot(...axis)||1;
  const normal=[-axis[1]/length,axis[0]/length], lift=bend*length*.42;
  const control=[root[0]+axis[0]*.5+normal[0]*lift,root[1]+axis[1]*.5+normal[1]*lift];
  const at=t=>{const u=1-t; return [u*u*root[0]+2*u*t*control[0]+t*t*target[0],u*u*root[1]+2*u*t*control[1]+t*t*target[1]];};
  return {control,normal,length,at};
}
function tailPath(endPoint,startPoint,ta,tb,target,half,distance,tail) {
  const root=mix(endPoint,startPoint,.5), spine=tailSpine(root,target,tail.bend);
  if (tail.jagged) {
    // A lightning tail: two kinks across the spine, tapering to the tip.
    const zig=Math.min(spine.length*.11,half*1.15);
    const kinks=[.34,.67].map((t,i)=>{
      const p=spine.at(t), side=i ? -zig : zig;
      return {point:[p[0]+spine.normal[0]*side,p[1]+spine.normal[1]*side],taper:(1-t)*.9};
    });
    const edge=from=>kinks.map(({point,taper})=>[point[0]+(from[0]-root[0])*taper,point[1]+(from[1]-root[1])*taper]);
    const a=edge(endPoint), b=edge(startPoint).reverse();
    return [endPoint,...a,target,...b,startPoint].slice(1).map((p,i,rest)=>curveText(straight(i ? rest[i-1] : endPoint,p))).join("");
  }
  const ease=Math.min(half*.65,distance*.12);
  const c1=[endPoint[0]+ta[0]*ease,endPoint[1]+ta[1]*ease];
  const c2=[startPoint[0]-tb[0]*ease,startPoint[1]-tb[1]*ease];
  // A flared root that joins the body smoothly, then a slim, concave taper.
  const side=p=>[spine.control[0]+(p[0]-root[0])*.16,spine.control[1]+(p[1]-root[1])*.16];
  return curveText([endPoint,c1,side(endPoint),target])+curveText([target,side(startPoint),c2,startPoint]);
}
function outlinePath(curves,table,attach,target,fontSize,w,h,tail) {
  if (!attach) return `M${pointText(curves[0][0])}`+curves.map(curveText).join("")+"Z";
  const distance=Math.hypot(target[0]-attach.point[0],target[1]-attach.point[1]);
  const half=Math.min(fontSize*.48*tail.width,w*.12*tail.width,h*.22*tail.width,w*.2,h*.3,distance*.45);
  const a=paramAtLength(table,attach.length-half),b=paramAtLength(table,attach.length+half);
  const count=curves.length, end=a<=b?a+count:a;
  let cursor=b, path="",startPoint,endPoint;
  // Walk the actual body cubics, except for the short tail-root arc.
  while(cursor<end-1e-8) {
    const index=Math.floor(cursor+1e-9), stop=Math.min(index+1,end);
    const part=curvePart(curves[index%count],cursor-index,stop-index);
    if (!path) {startPoint=part[0];path=`M${pointText(startPoint)}`;}
    path+=curveText(part); endPoint=part[3]; cursor=stop;
  }
  const tangent=(parameter)=>{
    const index=Math.floor(parameter)%count,t=parameter-Math.floor(parameter),c=curves[index];
    const dx=3*(1-t)**2*(c[1][0]-c[0][0])+6*(1-t)*t*(c[2][0]-c[1][0])+3*t*t*(c[3][0]-c[2][0]);
    const dy=3*(1-t)**2*(c[1][1]-c[0][1])+6*(1-t)*t*(c[2][1]-c[1][1])+3*t*t*(c[3][1]-c[2][1]);
    const length=Math.hypot(dx,dy)||1;return [dx/length,dy/length];
  };
  // One continuous silhouette, including both tail edges: no triangle laid on
  // a stroked body, no white seam-cover line, and no opaque-fill assumption.
  return path+tailPath(endPoint,startPoint,tangent(a),tangent(b),target,half,distance,tail)+"Z";
}
/** Body outline in the element's own (untransformed) page coordinates. */
function bodyGeometry(element,role,x,y,w,h,pageHeight) {
  if (role.shape==="none") return null;
  const curves=contour(role,w,h),table=contourTable(curves);
  let target=null,attach=null;
  if (element.tail_target && ["speech","thought"].includes(element.role)) {
    // Tail targets stay in page space when the body is scaled or rotated.
    const wx=element.tail_target.x*1000-(x+w/2),wy=element.tail_target.y*pageHeight-(y+h/2);
    const angle=-element.rotation*Math.PI/180;
    target=[w/2+(wx*Math.cos(angle)-wy*Math.sin(angle))/element.scale,
      h/2+(wx*Math.sin(angle)+wy*Math.cos(angle))/element.scale];
    attach=attachPoint(curves,table,target,w,h);
  }
  const tail={width:role.tail_width,bend:element.tail_bend??0,jagged:role.shape==="electric"};
  const d=outlinePath(curves,table,element.role==="speech"?attach:null,target,element.resolved.font_size,w,h,tail);
  let puffs=[];
  if (element.role==="thought" && attach) {
    const distance=Math.hypot(target[0]-attach.point[0],target[1]-attach.point[1]);
    const spine=tailSpine(attach.point,target,tail.bend);
    puffs=[.24,.54,.83].map((t,i)=>{
      const [cx,cy]=spine.at(t),r=Math.min(element.resolved.font_size*(.58-i*.16),distance*.14);
      return {cx,cy,r};
    });
  }
  return {x,y,d,puffs};
}
function bodyMarkup(body,attrs,main=false) {
  const puffs=body.puffs.map((p,i)=>`<ellipse${main?` data-thought-puff="${i}"`:""} cx="${p.cx}" cy="${p.cy}" rx="${p.r}" ry="${p.r*.84}" ${attrs}/>`).join("");
  return `<g transform="translate(${number(body.x)} ${number(body.y)})"><path${main?` data-balloon-body="${main}"`:""} d="${body.d}" ${attrs}/>${puffs}</g>`;
}
/* Letters. Runs carry emphasis; letters placed one by one follow the warp
 * curve and a seeded bounce. Everything is derived from stored metrics, so
 * the server's export reproduces the editor exactly. */
function runsMarkup(line) {
  return runsOf(line).map(run=>run.em ? `<tspan font-style="italic" font-weight="700">${escape(run.text)}</tspan>` : escape(run.text)).join("");
}
function lettersMarkup(p,paint) {
  const {role,r,x,y}=p, size=r.font_size, slack=lineSlack(role,size);
  const attrs=`font-family="${escape(JSON.stringify(role.font))}" font-size="${size}" font-weight="${role.font_weight ?? 400}" letter-spacing="${role.letter_spacing}" fill="${paint.fill}" stroke="${paint.stroke}" stroke-width="${number(paint.width)}" paint-order="stroke fill" stroke-linejoin="round" xml:space="preserve"`;
  const lean=role.skew ? ` skewX(${number(-role.skew)})` : "";
  const left=Math.min(...r.line_metrics.map(m=>m.x)), right=Math.max(...r.line_metrics.map(m=>m.x+m.width));
  const centre=x+(left+right)/2, span=Math.max(1,(right-left)/2);
  const random=seededRandom(`${p.element.id}:${role.seed ?? ""}`);
  return r.lines.map((line,index)=>{
    const metric=r.line_metrics[index], baseline=y+metric.baseline, start=x+metric.x+slack.left;
    const glyphs=glyphsOf(line), stops=metric.glyph_x;
    if (!lettersOneByOne(role) || !stops || stops.length!==glyphs.length+1) {
      const transform=lean ? ` transform="translate(${number(start)} ${number(baseline)})${lean} translate(${number(-start)} ${number(-baseline)})"` : "";
      return `<text x="${number(start)}" y="${number(baseline)}" text-anchor="start" ${attrs}${transform}>${runsMarkup(line)}</text>`;
    }
    const amount=role.warp_amount*size;
    return glyphs.map((glyph,i)=>{
      const gx=start+stops[i], advance=(i<glyphs.length-1 ? stops[i+1]-role.letter_spacing : stops.at(-1))-stops[i];
      const cx=gx+advance/2, u=clamp((cx-centre)/span,-1,1);
      let dy=0, slope=0;
      if (role.warp==="arc") { dy=-amount*(1-u*u)+amount/2; slope=amount*2*u/span; }
      else if (role.warp==="wave") { dy=-amount*.9*Math.sin(Math.PI*u); slope=-amount*.9*Math.PI*Math.cos(Math.PI*u)/span; }
      const shake=role.jitter||0;
      const turn=Math.atan(slope)*180/Math.PI*(role.warp==="wave" ? .55 : 1)+(random()-.5)*2*shake*12;
      dy+=(random()-.5)*2*shake*size*.1;
      const grow=1+(random()-.5)*2*shake*.1;
      // Arcs turn letters on the baseline, like type set on a curve; waves and
      // bounces turn them about their middle so neighbours never collide.
      const pivot=role.warp==="arc" ? baseline : baseline-size*.36;
      const transform=`translate(${number(cx)} ${number(pivot+dy)}) rotate(${number(turn)})${lean} scale(${number(grow)}) translate(${number(-cx)} ${number(-pivot)})`;
      const text=glyph.em ? `<tspan font-style="italic" font-weight="700">${escape(glyph.text)}</tspan>` : escape(glyph.text);
      return `<text x="${number(gx)}" y="${number(baseline)}" text-anchor="start" ${attrs} transform="${transform}">${text}</text>`;
    }).join("");
  }).join("");
}
function fnv(text) {
  let hash=2166136261;
  for (const char of text) hash=Math.imul(hash^char.charCodeAt(0),16777619);
  return (hash>>>0).toString(36);
}
const visible=color=>color!=="transparent";
/** Copies behind the lettering, in page space so light falls the same way on
 * rotated elements: one drop shadow, or a solid extrusion stepped from far to near. */
function shadowOffsets(role) {
  if (role.shadow==="none" || !visible(role.shadow_color) || (!role.shadow_x && !role.shadow_y)) return [];
  if (role.shadow==="drop") return [[role.shadow_x,role.shadow_y]];
  const steps=clamp(Math.ceil(Math.hypot(role.shadow_x,role.shadow_y)/1.25),1,32);
  return Array.from({length:steps},(_,i)=>[role.shadow_x*(steps-i)/steps,role.shadow_y*(steps-i)/steps]);
}
function prepare(element,role,pageHeight) {
  const r=element.resolved, box=elementRect(element);
  const x=box.x*1000,y=box.y*pageHeight,w=box.width*1000,h=box.height*pageHeight;
  if (!r.line_metrics || r.line_metrics.length!==r.lines.length ||
      ![r.font_size,r.line_height,r.width,r.height].every(Number.isFinite) ||
      r.line_metrics.some(m=>![m.x,m.baseline,m.width,m.ascent,m.descent].every(Number.isFinite) ||
        (m.glyph_x!=null && (!Array.isArray(m.glyph_x) || !m.glyph_x.every(Number.isFinite))))) {
    throw new Error("Lettering needs measured line positions before it can be rendered.");
  }
  const transform=`translate(${x+w/2} ${y+h/2}) rotate(${element.rotation}) scale(${element.scale}) translate(${-x-w/2} ${-y-h/2})`;
  return {element,role,r,x,y,w,h,transform,body:bodyGeometry(element,role,x,y,w,h,pageHeight)};
}
function placed(p,markup,[dx,dy]=[0,0]) {
  return `<g transform="${dx||dy ? `translate(${number(dx)} ${number(dy)}) ` : ""}${p.transform}">${markup}</g>`;
}
function gradientFor(p) {
  const {role,r,y}=p;
  if (!visible(role.gradient_color) || !visible(role.color)) return {defs:"",fill:role.color};
  const first=r.line_metrics[0], last=r.line_metrics.at(-1);
  const top=y+(first?.baseline ?? 0)-(first?.ascent ?? r.font_size), bottom=y+(last?.baseline ?? 0)+(last?.descent ?? 0);
  const id=`lg-${fnv([p.element.id,role.color,role.gradient_color,top,bottom].join("|"))}`;
  return {fill:`url(#${id})`,defs:`<defs><linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="0" y1="${number(top)}" x2="0" y2="${number(Math.max(top+1,bottom))}"><stop offset="0" stop-color="${role.color}"/><stop offset="1" stop-color="${role.gradient_color}"/></linearGradient></defs>`};
}
/** Layers under an element's main paint: an outer knockout outline, then its
 * shadow or extrusion. Both belong to the balloon when there is one, otherwise
 * to the letters themselves. */
function underlays(p,{halo=true,shadow=true}={}) {
  const {role,body}=p, offsets=shadowOffsets(role);
  let out="";
  if (halo && role.halo_width>0 && visible(role.halo_color)) {
    const around=[...(role.shadow==="extrude" ? offsets : []),[0,0]];
    const markup=body
      ? bodyMarkup(body,`fill="none" stroke="${role.halo_color}" stroke-width="${number(role.stroke_width+2*role.halo_width)}" stroke-linejoin="round"`)
      : lettersMarkup(p,{fill:role.halo_color,stroke:role.halo_color,width:role.text_stroke_width+2*role.halo_width});
    out+=around.map(offset=>placed(p,markup,offset)).join("");
  }
  if (shadow && offsets.length) {
    const markup=body
      ? bodyMarkup(body,`fill="${visible(role.fill) ? role.shadow_color : "none"}" stroke="${role.shadow_color}" stroke-width="${role.stroke_width}" stroke-linejoin="round"`)
      : lettersMarkup(p,{fill:role.shadow_color,stroke:role.text_stroke_width>0 ? role.shadow_color : "transparent",width:role.text_stroke_width});
    out+=offsets.map(offset=>placed(p,markup,offset)).join("");
  }
  return out;
}
function bodyPaint(role) {
  const dash=role.shape==="whisper" ? ` stroke-dasharray="${number(Math.max(2,role.stroke_width*3))} ${number(Math.max(2,role.stroke_width*2))}"` : "";
  return `fill="${role.fill}" stroke="${role.stroke}" stroke-width="${role.stroke_width}" stroke-linejoin="round"${dash}`;
}
function textLayer(p) {
  const gradient=gradientFor(p);
  return gradient.defs+lettersMarkup(p,{fill:gradient.fill,stroke:p.role.text_stroke,width:p.role.text_stroke_width});
}
function elementSVG(p) {
  const main=(p.body ? bodyMarkup(p.body,bodyPaint(p.role),p.element.role) : "")+textLayer(p);
  return `<g data-lettering-id="${escape(p.element.id)}">${underlays(p)}${placed(p,main)}</g>`;
}
/* Linked balloons: one speaker's consecutive balloons joined by a pinched
 * bridge into ONE silhouette. Every outline is painted first at double width,
 * then every fill, so no line crosses the joins; the letters come last. */
const mergeable=p=>p && p.body && ["speech","thought"].includes(p.element.role) && visible(p.role.fill) && p.role.shape!=="whisper";
function bridge(a,b) {
  const ca=[a.x+a.w/2,a.y+a.h/2], cb=[b.x+b.w/2,b.y+b.h/2];
  const length=Math.hypot(cb[0]-ca[0],cb[1]-ca[1]);
  if (length<1) return null;
  const normal=[-(cb[1]-ca[1])/length,(cb[0]-ca[0])/length];
  const half=Math.max(6,Math.min(a.h*a.element.scale,b.h*b.element.scale,a.w*a.element.scale,b.w*b.element.scale)*.24);
  const at=(p,k)=>[p[0]+normal[0]*half*k,p[1]+normal[1]*half*k], mid=mix(ca,cb,.5);
  return `M${pointText(at(ca,1))}Q${pointText(at(mid,.35))} ${pointText(at(cb,1))}L${pointText(at(cb,-1))}Q${pointText(at(mid,-.35))} ${pointText(at(ca,-1))}Z`;
}
function linkedSVG(members,links) {
  const bridges=links.map(([from,to])=>({role:from.role,d:bridge(to,from)})).filter(b=>b.d);
  let out=members.map(p=>underlays(p,{shadow:false})).join("");
  out+=bridges.filter(b=>b.role.halo_width>0 && visible(b.role.halo_color))
    .map(b=>`<path d="${b.d}" fill="none" stroke="${b.role.halo_color}" stroke-width="${number(b.role.stroke_width+2*b.role.halo_width)}" stroke-linejoin="round"/>`).join("");
  for (const p of members) out+=underlays(p,{halo:false});
  for (const b of bridges) for (const [dx,dy] of shadowOffsets(b.role))
    out+=`<path transform="translate(${number(dx)} ${number(dy)})" d="${b.d}" fill="${b.role.shadow_color}" stroke="${b.role.shadow_color}" stroke-width="${b.role.stroke_width}" stroke-linejoin="round"/>`;
  const outline=r=>`fill="none" stroke="${r.stroke}" stroke-width="${number(r.stroke_width*2)}" stroke-linejoin="round"`;
  for (const p of members) out+=placed(p,bodyMarkup(p.body,outline(p.role)));
  for (const b of bridges) out+=`<path data-balloon-bridge d="${b.d}" ${outline(b.role)}/>`;
  for (const b of bridges) out+=`<path d="${b.d}" fill="${b.role.fill}" stroke="none"/>`;
  for (const p of members) out+=placed(p,bodyMarkup(p.body,`fill="${p.role.fill}" stroke="none"`,p.element.role));
  for (const p of members) out+=`<g data-lettering-id="${escape(p.element.id)}">${placed(p,textLayer(p))}</g>`;
  return `<g data-lettering-link="${escape(members[0].element.id)}">${out}</g>`;
}
export function renderOverlay(state, style) {
  validateEditableState(state,style);
  const pageHeight = 1000 / state.canvas_aspect_ratio;
  const ordered=[...state.elements].sort((a,b)=>a.z_index-b.z_index).filter((e)=>!e.hidden);
  const pieces=new Map(ordered.map(element=>{
    const r=element.resolved;
    if (!r || r.engine_version!==ENGINE_VERSION || r.locale!==state.locale || r.text!==textFor(element,state.locale)) {
      throw new Error("Lettering needs to be laid out before it can be rendered.");
    }
    return [element.id,prepare(element,roleFor(element,style),pageHeight)];
  }));
  // Union visible, mergeable links into groups; each group paints at its topmost member.
  const parent=new Map(ordered.map(e=>[e.id,e.id]));
  const find=id=>parent.get(id)===id ? id : find(parent.get(id));
  const links=[];
  for (const element of ordered) {
    const from=pieces.get(element.id), to=element.link_to ? pieces.get(element.link_to) : null;
    if (!mergeable(from) || !mergeable(to)) continue;
    links.push([from,to]);
    parent.set(find(element.id),find(to.element.id));
  }
  const groups=new Map();
  for (const element of ordered) {
    const root=find(element.id);
    groups.set(root,[...(groups.get(root) ?? []),pieces.get(element.id)]);
  }
  const content=ordered.map(element=>{
    const members=groups.get(find(element.id));
    if (members.length===1) return elementSVG(members[0]);
    if (members.at(-1).element.id!==element.id) return "";
    const ids=new Set(members.map(p=>p.element.id));
    return linkedSVG(members,links.filter(([from])=>ids.has(from.element.id)));
  }).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 1000 ${pageHeight}" role="img" aria-label="Page lettering" style="overflow:visible">${content}</svg>`;
}
