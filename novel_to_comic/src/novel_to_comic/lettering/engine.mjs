/**
 * Canary's sole lettering geometry/layout renderer. Imported by the Pages editor
 * and executed unchanged in Chromium by the server. No network or model calls.
 * Geometry is normalized; typography uses a 1000-unit vector page width.
 */
export const ENGINE_VERSION = "lettering-svg-v1";
export const FONT_FILES = Object.freeze({
  "Comic Neue": "ComicNeue-Bold.ttf",
  "EB Garamond": "EBGaramond-SemiBold.ttf",
  "Bangers": "Bangers-Regular.ttf",
  "Special Elite": "SpecialElite-Regular.ttf",
  "M PLUS 1p": "MPLUS1p-Bold.ttf",
  "Fredoka": "Fredoka-SemiBold.ttf",
  "Orbitron": "Orbitron-Bold.ttf",
  "Bungee": "Bungee-Regular.ttf",
});
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
  return (text, font, size, spacing = 0, weight = 400) => {
    const key = `${font}\0${size}\0${spacing}\0${weight}\0${text}`;
    if (cache.has(key)) return cache.get(key);
    context.font = `${weight} ${size}px "${font}"`;
    const value = context.measureText(text).width + Math.max(0, [...text].length - 1) * spacing;
    // Bound memory during a long editing session.
    if (cache.size > 12000) cache.clear();
    cache.set(key, value);
    return value;
  };
}

/** Word units preserve unbreakable words; CJK can break at grapheme boundaries.
 * Explicit newlines are hard breaks. Words are NEVER split to fake a fit.
 */
function unitsFor(paragraph, locale) {
  const text = paragraph.trim().replace(/[\t ]+/g, " ");
  if (!text) return [];
  if (/\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}/u.test(text)) {
    // Intl word segmentation keeps Latin words intact in mixed-script copy.
    const units = [...new Intl.Segmenter(safeLocale(locale), { granularity: "word" }).segment(text)]
      .map((part) => part.segment);
    const combined = [];
    for (const unit of units) {
      if (/^[\s、。，．！？!?：:；;）)」』】]+$/u.test(unit) && combined.length) {
        combined[combined.length - 1] += unit;
      } else combined.push(unit);
    }
    return { units: combined, separator: "" };
  }
  return { units: text.split(" "), separator: " " };
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
export function roleFor(element, style) {
  return element.style_override || style.roles[element.role];
}
export function textFor(element, locale) {
  return element.text_by_locale[locale] ?? element.text_by_locale.source;
}
export function elementRect(element) {
  return { ...element.placement,
    height: element.tight_box && element.resolved ? element.resolved.height : element.placement.height };
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
function validateEditableState(state, style) {
  const finite=(n)=>typeof n === "number" && Number.isFinite(n);
  const rect=(r)=>r && [r.x,r.y,r.width,r.height].every(finite) && r.x>=0 && r.y>=0 && r.width>0 && r.height>0 && r.x+r.width<=1.000001 && r.y+r.height<=1.000001;
  if (!finite(state.canvas_aspect_ratio) || state.canvas_aspect_ratio<=.1 || state.canvas_aspect_ratio>=10 || !Array.isArray(state.elements) || state.elements.length>200) throw new Error("Invalid lettering draft geometry.");
  if (typeof state.locale!=="string" || !/^(source|[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)$/.test(state.locale)) throw new Error("Invalid lettering language.");
  for (const element of state.elements) {
    const role=roleFor(element,style);
    if (!rect(element.placement) || !rect(element.suggested_placement) || ![element.rotation,element.scale,element.z_index].every(finite) || element.scale<.25 || element.scale>3 || Math.abs(element.rotation)>180) throw new Error("Invalid lettering placement.");
    if (!element.text_by_locale || typeof element.text_by_locale.source!=="string" || Object.values(element.text_by_locale).some(text=>typeof text!=="string"||text.length>10000)) throw new Error("Invalid lettering copy.");
    if (element.tail_target && (![element.tail_target.x,element.tail_target.y].every(finite) || element.tail_target.x<0 || element.tail_target.x>1 || element.tail_target.y<0 || element.tail_target.y>1)) throw new Error("Invalid lettering tail.");
    if (!role || !Object.hasOwn(FONT_FILES,role.font) || !["box","round","ellipse","cloud","none"].includes(role.shape) || !["left","center","right"].includes(role.align)) throw new Error("Invalid lettering style.");
    if ([role.color,role.fill,role.stroke,role.text_stroke].some(color=>typeof color!=="string"||!/^(#[0-9a-fA-F]{6}|transparent)$/.test(color))) throw new Error("Invalid lettering ink.");
    if (![role.min_font_size,role.max_font_size,role.line_height,role.stroke_width,role.padding,role.corner_radius,role.letter_spacing,role.text_stroke_width].every(finite) || role.min_font_size<12 || role.max_font_size>180 || role.min_font_size>role.max_font_size || role.line_height<=0 || ![400,700].includes(role.font_weight??400)) throw new Error("Invalid typography settings.");
  }
}
export function resolvePage(state, style, measure) {
  validateEditableState(state,style);
  const pageHeight = 1000 / state.canvas_aspect_ratio;
  return { ...state, elements: state.elements.map((element) => {
    const role = roleFor(element, style), text = textFor(element, state.locale);
    const warnings = [];
    if (!text.trim()) warnings.push("empty_copy");
    if (element.text_by_locale[state.locale] === undefined && state.locale !== "source") warnings.push("missing_translation");
    // Reserve curvature clearance as well as actual padding.
    const curve = ["ellipse", "cloud"].includes(role.shape) ? 0.30 : 0;
    const innerWidth = element.placement.width * 1000 * (1 - curve) - 2 * role.padding;
    const innerHeight = element.placement.height * pageHeight * (1 - curve) - 2 * role.padding;
    let result, size;
    for (size = role.max_font_size; size >= role.min_font_size; size -= 0.5) {
      result = balancedLines(text, innerWidth,
        (line) => measure(line, role.font, size, role.letter_spacing, role.font_weight ?? 400), state.locale);
      if (!result.overflow && result.lines.length * size * role.line_height <= innerHeight + 0.01) break;
    }
    if (size < role.min_font_size) {
      size = role.min_font_size;
      result = balancedLines(text, innerWidth,
        (line) => measure(line, role.font, size, role.letter_spacing, role.font_weight ?? 400), state.locale);
    }
    const required = (result.lines.length * size * role.line_height + 2 * role.padding) / (1 - curve);
    const overflow = innerWidth <= 0 || result.overflow || required > element.placement.height * pageHeight + 0.01;
    const resolved = {
      engine_version: ENGINE_VERSION, locale: state.locale, text,
      lines: result.lines, font_size: number(size), line_height: number(size * role.line_height),
      height: number(Math.max(0.001, Math.min(element.placement.height, required / pageHeight))),
      overflow, warnings,
    };
    const next = { ...element, resolved };
    const bounds = transformedBounds(next, state.canvas_aspect_ratio);
    if (bounds.x < -0.0001 || bounds.y < -0.0001 || bounds.x + bounds.width > 1.0001 || bounds.y + bounds.height > 1.0001) {
      resolved.overflow = true; warnings.push("outside_page");
    }
    // Unsupported scripts must be explicit: bundled fonts cover Latin and
    // Japanese, not all writing systems. Never claim fallback glyphs are a proof.
    if (/\p{Script=Arabic}|\p{Script=Hebrew}|\p{Script=Devanagari}|\p{Script=Thai}/u.test(text)) {
      warnings.push("unsupported_script");
      resolved.overflow = true;
    }
    if (/\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}/u.test(text) && role.font !== "M PLUS 1p") warnings.push("font_script_mismatch");
    return next;
  }) };
}
function cloudPath(x, y, w, h) {
  // Twelve outward scallops, bounded by the element rectangle. The inner
  // ellipse and 30% text clearance keep lettering away from the cloud's valleys.
  const cx = x + w / 2, cy = y + h / 2, steps = 12;
  const point = (angle, radius) => [cx + Math.cos(angle) * w / 2 * radius,
    cy + Math.sin(angle) * h / 2 * radius];
  let path = `M${point(-Math.PI / 2, .91).join(",")}`;
  for (let i = 0; i < steps; i++) {
    const angle = -Math.PI / 2 + i * Math.PI * 2 / steps;
    path += `Q${point(angle + Math.PI / steps, 1.04).join(",")} ${point(angle + Math.PI * 2 / steps, .91).join(",")}`;
  }
  return path + "Z";
}
function bodySVG(role, x, y, w, h) {
  const attrs = `fill="${role.fill}" stroke="${role.stroke}" stroke-width="${role.stroke_width}" stroke-linejoin="round"`;
  if (role.shape === "none") return "";
  if (role.shape === "ellipse") return `<ellipse cx="${x+w/2}" cy="${y+h/2}" rx="${w/2}" ry="${h/2}" ${attrs}/>`;
  if (role.shape === "cloud") return `<path d="${cloudPath(x,y,w,h)}" ${attrs}/>`;
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${role.shape === "box" ? role.corner_radius : Math.min(role.corner_radius, h/2)}" ${attrs}/>`;
}
function tailSVG(element, role, x, y, w, h, pageHeight) {
  if (!element.tail_target || !["speech","thought"].includes(element.role)) return "";
  const cx=x+w/2, cy=y+h/2;
  // The tail target is world/page space, even when its balloon rotates/scales.
  const wx=element.tail_target.x*1000-cx, wy=element.tail_target.y*pageHeight-cy;
  const angle=-element.rotation*Math.PI/180;
  const tx=cx+(wx*Math.cos(angle)-wy*Math.sin(angle))/element.scale;
  const ty=cy+(wx*Math.sin(angle)+wy*Math.cos(angle))/element.scale;
  const dx=tx-cx, dy=ty-cy;
  if (Math.abs(dx)<=w/2 && Math.abs(dy)<=h/2) return "";
  const ratio = ["ellipse","cloud"].includes(role.shape) ? 1/Math.sqrt((dx/(w/2))**2+(dy/(h/2))**2) : Math.min(w/2/Math.abs(dx),h/2/Math.abs(dy));
  const ax=cx+dx*ratio, ay=cy+dy*ratio;
  const common=`fill="${role.fill}" stroke="${role.stroke}" stroke-width="${role.stroke_width}"`;
  if (element.role === "thought") {
    return [0.22,0.53,0.8].map((t,i)=>`<ellipse cx="${ax+(tx-ax)*t}" cy="${ay+(ty-ay)*t}" rx="${7-i*2}" ry="${5-i*1.4}" ${common}/>`).join("");
  }
  const bottomTop = Math.abs(ax-cx)/(w/2) < Math.abs(ay-cy)/(h/2);
  const half = Math.min(10,w*.07,h*.15);
  const bx=bottomTop?half:0, by=bottomTop?0:half;
  return `<path d="M${ax-bx},${ay-by} Q${(ax+tx)/2},${(ay+ty)/2} ${tx},${ty} L${ax+bx},${ay+by} Z" ${common} stroke-linejoin="round"/>`+
    `<path d="M${ax-bx*.82},${ay-by*.82} L${ax+bx*.82},${ay+by*.82}" stroke="${role.fill}" stroke-width="${role.stroke_width+1.5}"/>`;
}
export function renderOverlay(state, style) {
  validateEditableState(state,style);
  const pageHeight = 1000 / state.canvas_aspect_ratio;
  const content = [...state.elements].sort((a,b)=>a.z_index-b.z_index).filter((e)=>!e.hidden).map((element)=>{
    const r=element.resolved;
    if (!r || r.engine_version!==ENGINE_VERSION || r.locale!==state.locale || r.text!==textFor(element,state.locale)) {
      throw new Error("Lettering needs to be laid out before it can be rendered.");
    }
    const role=roleFor(element,style), box=elementRect(element);
    const x=box.x*1000,y=box.y*pageHeight,w=box.width*1000,h=box.height*pageHeight;
    const curve = ["ellipse", "cloud"].includes(role.shape) ? .15 : 0;
    const textX = role.align==="left" ? x+role.padding+w*curve : role.align==="right" ? x+w-role.padding-w*curve : x+w/2;
    const anchor=role.align==="left"?"start":role.align==="right"?"end":"middle";
    const firstBaseline=y+(h-r.lines.length*r.line_height)/2+r.font_size*.82;
    const lines=r.lines.map((line,index)=>`<text x="${textX}" y="${firstBaseline+index*r.line_height}" text-anchor="${anchor}" font-family="${escape(role.font)}" font-size="${r.font_size}" font-weight="${role.font_weight ?? 400}" letter-spacing="${role.letter_spacing}" fill="${role.color}" stroke="${role.text_stroke}" stroke-width="${role.text_stroke_width}" paint-order="stroke fill" stroke-linejoin="round" xml:space="preserve">${escape(line)}</text>`).join("");
    return `<g data-lettering-id="${escape(element.id)}" transform="translate(${x+w/2} ${y+h/2}) rotate(${element.rotation}) scale(${element.scale}) translate(${-x-w/2} ${-y-h/2})">`+
      bodySVG(role,x,y,w,h)+tailSVG(element,role,x,y,w,h,pageHeight)+lines+"</g>";
  }).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 1000 ${pageHeight}" role="img" aria-label="Page lettering" style="overflow:visible">${content}</svg>`;
}
