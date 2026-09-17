/**
 * Canary's sole lettering geometry/layout renderer. Imported by the Pages editor
 * and executed unchanged in Chromium by the server. No network or model calls.
 * Geometry is normalized; typography uses a 1000-unit vector page width.
 */
import { FONT_COVERAGE } from "./font-coverage.mjs";

export const ENGINE_VERSION = "lettering-svg-v4";
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
  const metrics = (text, font, size, spacing = 0, weight = 400) => {
    const key = `${font}\0${size}\0${spacing}\0${weight}\0${text}`;
    if (cache.has(key)) return cache.get(key);
    context.font = `${weight} ${size}px "${font}"`;
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
    width: element.tight_box && element.resolved?.width ? element.resolved.width : element.placement.width,
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
    if (!role || !Object.hasOwn(FONT_FILES,role.font) || !["box","round","balloon","ellipse","cloud","none"].includes(role.shape) || !["left","center","right"].includes(role.align)) throw new Error("Invalid lettering style.");
    if ([role.color,role.fill,role.stroke,role.text_stroke].some(color=>typeof color!=="string"||!/^(#[0-9a-fA-F]{6}|transparent)$/.test(color))) throw new Error("Invalid lettering ink.");
    if (![role.min_font_size,role.max_font_size,role.line_height,role.stroke_width,role.padding,role.corner_radius,role.letter_spacing,role.text_stroke_width].every(finite) || role.min_font_size<12 || role.max_font_size>180 || role.min_font_size>role.max_font_size || role.line_height<=0 || ![400,700].includes(role.font_weight??400)) throw new Error("Invalid typography settings.");
  }
}
// Optical text extents, not em-box guesses. Tests can inject a width-only
// measurer; production records Chromium's actual glyph ascent and descent.
function inkMetrics(text, role, size, measure) {
  const width = measure(text, role.font, size, role.letter_spacing, role.font_weight ?? 400);
  const ink = measure.metrics?.(text, role.font, size, role.letter_spacing, role.font_weight ?? 400);
  return { width, ascent: ink?.ascent ?? size * .74, descent: ink?.descent ?? size * .2 };
}
const curved = (shape) => ["balloon", "ellipse", "cloud"].includes(shape);
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
// Four Hermite cubics per scallop preserve the radial curve's tangent at
// both crests and valleys. The same normalized cubics drive drawing and fit.
const cloudCurves=Array.from({length:32},(_,i)=>{
  const step=Math.PI/16;
  const at=index=>{
    const wrapped=index%32, angle=-Math.PI/2+wrapped*step, phase=wrapped*Math.PI/2;
    const radius=.96+.04*Math.cos(phase), derivative=-.32*Math.sin(phase);
    const x=Math.cos(angle), y=Math.sin(angle);
    return {point:[radius*x,radius*y], tangent:[derivative*x-radius*y,derivative*y+radius*x]};
  };
  const a=at(i), b=at(i+1);
  return [a.point,a.point.map((v,j)=>v+a.tangent[j]*step/3),
    b.point.map((v,j)=>v-b.tangent[j]*step/3),b.point];
});
function curveExtrema(c, axis) {
  const [p,q,r,s]=c.map(point=>point[axis]);
  const a=-p+3*q-3*r+s, b=2*(p-2*q+r), d=q-p;
  if (Math.abs(a)<1e-12) return Math.abs(b)<1e-12 ? [] : [-d/b].filter(t=>t>0 && t<1);
  const discriminant=b*b-4*a*d;
  return discriminant<0 ? [] : [(-b-Math.sqrt(discriminant))/(2*a),(-b+Math.sqrt(discriminant))/(2*a)].filter(t=>t>0 && t<1);
}
// A scallop can turn in both x and y. Split at every extremum once, so row
// bands test their entire boundary, not just their corners or an inset ellipse.
const cloudBands=cloudCurves.slice(0,16).flatMap(c=>{
  const cuts=[0,...curveExtrema(c,0),...curveExtrema(c,1),1].sort((a,b)=>a-b);
  return cuts.slice(1).flatMap((end,i)=>end-cuts[i]>1e-10 ? [curvePart(c,cuts[i],end)] : []);
});
function cloudFactor(top,bottom) {
  if (top<=-1 || bottom>=1) return 0;
  let factor=1;
  for (const c of cloudBands) {
    const low=Math.max(top,Math.min(c[0][1],c[3][1])), high=Math.min(bottom,Math.max(c[0][1],c[3][1]));
    if (low>high) continue;
    for (const y of [low,high]) {
      let lo=0,hi=1;
      const ascending=c[3][1]>=c[0][1];
      for (let i=0;i<20;i++) {
        const t=(lo+hi)/2;
        if ((curvePoint(c,t)[1]<y)===ascending) lo=t; else hi=t;
      }
      factor=Math.min(factor,curvePoint(c,(lo+hi)/2)[0]);
    }
  }
  return Math.max(0,factor-1e-6);
}
// The rounded oval uses four smooth cubics. Layout queries this SAME curve,
// rather than reserving an arbitrary rectangular 30% inset for all lines.
function ovalFactor(distance, shape) {
  if (distance >= 1) return 0;
  const k=shape === "ellipse" ? .5522847498 : .68;
  const c=[[0,-1],[k,-1],[1,-k],[1,0]];
  let lo=0, hi=1;
  for (let i=0;i<18;i++) {
    const t=(lo+hi)/2;
    if (-curvePoint(c,t)[1]>distance) lo=t; else hi=t;
  }
  return curvePoint(c,(lo+hi)/2)[0];
}
function rowSpace(role, height, top, bottom) {
  if (role.shape==="cloud") return {factor:cloudFactor(top/(height/2)-1,bottom/(height/2)-1),inset:0};
  const distance=Math.max(Math.abs(top-height/2),Math.abs(bottom-height/2));
  if (curved(role.shape)) return { factor: ovalFactor(distance/(height/2),role.shape), inset: 0 };
  const radius=Math.min(role.corner_radius,height/2);
  const edge=Math.min(top,height-bottom);
  const inset=role.shape !== "none" && radius>0 && edge<radius
    ? radius-Math.sqrt(Math.max(0,radius*radius-(radius-edge)**2)) : 0;
  return { factor: 1, inset };
}
function rowGeometry(role, height, count, ascent, descent, leading) {
  const baseline=(height-(ascent+descent+(count-1)*leading))/2+ascent;
  const padding=["ellipse","cloud"].includes(role.shape) ? role.padding+role.stroke_width/2+role.text_stroke_width/2 : 0;
  return Array.from({length:count},(_,i)=>{
    const y=baseline+i*leading;
    return { baseline:y, ...rowSpace(role,height,y-ascent-padding,y+descent+padding) };
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
  const leading=size*role.line_height;
  const rows=rowGeometry(role,height,lines.length,ascent,descent,leading);
  const padding=role.padding+role.stroke_width/2+role.text_stroke_width/2;
  const line_metrics=ink.map((m,i)=>{
    const row=rows[i], inset=width*(1-row.factor)/2+padding+row.inset;
    const x=role.align==="left" ? inset : role.align==="right" ? width-inset-m.width : (width-m.width)/2;
    return { x:number(x), baseline:number(row.baseline), width:number(m.width), ascent:number(m.ascent), descent:number(m.descent) };
  });
  const overflow=ink.some((m,i)=>m.width+2*(padding+rows[i].inset)>width*rows[i].factor+.05)
    || ascent+descent+(lines.length-1)*leading+2*padding>height+.05;
  return {lines,width,height,line_metrics,overflow};
}
function fitBalloon(text, role, size, maxWidth, maxHeight, measure, locale, tight) {
  const padding=role.padding+role.stroke_width/2+role.text_stroke_width/2;
  const all=inkMetrics(text.replace(/\n/g," "),role,size,measure), leading=size*role.line_height;
  const optimizeOval=["ellipse","cloud"].includes(role.shape);
  const clearance=curved(role.shape) && !optimizeOval ? size*.55 : 0;
  const naturalHeight=count=>all.ascent+all.descent+(count-1)*leading+2*padding+clearance;
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
    if (!widths.has(line)) widths.set(line,measure(line,role.font,size,role.letter_spacing,role.font_weight??400));
    return widths.get(line);
  };
  const candidates=[];
  // Hard breaks are editorial decisions. Keep them, including blank lines.
  if (/[\r\n]/.test(text) || (tokenized.units?.length ?? 0)>100) {
    for (let step=5;step<=16;step++) {
      const result=balancedLines(text,Math.max(1,maxWidth*step/16-2*padding),widthOf,locale);
      if (result.overflow) continue;
      for (const height of heightsFor(result.lines.length)) {
        const rows=rowGeometry(role,height,result.lines.length,all.ascent,all.descent,leading);
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
        const rows=rowGeometry(role,height,count,all.ascent,all.descent,leading);
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
      ? Math.max(0,ratio-3)**2*.2+Math.max(0,(role.shape==="cloud" ? 1.8 : 1.3)-ratio)**2*(role.shape==="cloud" ? 2 : .5)
      : Math.max(0,ratio-3.7)**2*.25+Math.max(0,2.3-ratio)**2*2;
    const score=candidate.width*natural*(1+loneEnding+aspectPenalty);
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
  const result=balancedLines(text,w-2*padding,line=>measure(line,role.font,size,role.letter_spacing,role.font_weight??400),locale);
  const ink=result.lines.map(line=>inkMetrics(line,role,size,measure));
  const height=Math.max(...ink.map(m=>m.ascent))+Math.max(...ink.map(m=>m.descent))+(result.lines.length-1)*size*role.line_height+2*padding;
  const width=Math.max(.1,...ink.map(m=>m.width))+2*padding;
  if (result.overflow || height>h+.01 || width>w+.01) return null;
  const layout=composeLayout(result.lines,role,size,element.tight_box?width:w,element.tight_box?Math.max(1,height):h,measure);
  return layout.overflow ? null : layout;
}
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
    const warnings = [];
    if (!text.trim()) warnings.push("empty_copy");
    if (hasMissingGlyphs(role.font, text)) warnings.push("missing_glyphs");
    if (element.text_by_locale[state.locale] === undefined && state.locale !== "source") warnings.push("missing_translation");
    const key=JSON.stringify([role,element.role,text,state.locale,element.placement.width,
      element.placement.height,element.tight_box,pageHeight]);
    let cached=cache.get(key);
    if (!cached) {
      let result=null, size=role.max_font_size;
      while (true) {
        result=fitText(element,role,text,size,pageHeight,measure,state.locale);
        if (result || size===role.min_font_size) break;
        size=Math.max(role.min_font_size,size-.5);
      }
      if (!result) {
        // Preserve every word, visibly flag overflow, and stop at the readable floor.
        const width=element.placement.width*1000, height=element.placement.height*pageHeight;
        const broken=balancedLines(text,Math.max(1,width*.75-2*role.padding),line=>measure(line,role.font,size,role.letter_spacing,role.font_weight??400),state.locale);
        result={...composeLayout(broken.lines,role,size,width,height,measure),overflow:true};
      }
      if (cache.size>=256) cache.clear();
      cached={result,size}; cache.set(key,cached);
    }
    const {result,size}=cached;
    const resolved = {
      engine_version: ENGINE_VERSION, locale: state.locale, text,
      lines:[...result.lines], font_size:number(size), line_height:number(size*role.line_height),
      width:result.width/1000, height:result.height/pageHeight,
      line_metrics:result.line_metrics.map(line=>({...line})), overflow:result.overflow, warnings,
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
  const rx=w/2,ry=h/2,k=role.shape==="ellipse"?.5522847498:.68;
  if (["ellipse","balloon"].includes(role.shape)) return [
    [[rx,0],[rx+k*rx,0],[w,ry-k*ry],[w,ry]],
    [[w,ry],[w,ry+k*ry],[rx+k*rx,h],[rx,h]],
    [[rx,h],[rx-k*rx,h],[0,ry+k*ry],[0,ry]],
    [[0,ry],[0,ry-k*ry],[rx-k*rx,0],[rx,0]],
  ];
  if (role.shape==="cloud") return cloudCurves.map(c=>c.map(([x,y])=>[rx+x*rx,ry+y*ry]));
  const r=clamp(role.corner_radius,0,Math.min(rx,ry)), e=.5522847498*r;
  const line=(a,b)=>[a,mix(a,b,1/3),mix(a,b,2/3),b];
  return [line([r,0],[w-r,0]),[[w-r,0],[w-r+e,0],[w,r-e],[w,r]],
    line([w,r],[w,h-r]),[[w,h-r],[w,h-r+e],[w-r+e,h],[w-r,h]],
    line([w-r,h],[r,h]),[[r,h],[r-e,h],[0,h-r+e],[0,h-r]],
    line([0,h-r],[0,r]),[[0,r],[0,r-e],[r-e,0],[r,0]]];
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
function outlinePath(curves,table,attach,target,fontSize,w,h) {
  if (!attach) return `M${pointText(curves[0][0])}`+curves.map(curveText).join("")+"Z";
  const distance=Math.hypot(target[0]-attach.point[0],target[1]-attach.point[1]);
  const half=Math.min(fontSize*.48,w*.12,h*.22,distance*.45);
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
  const ta=tangent(a),tb=tangent(b),ease=Math.min(half*.65,distance*.12);
  const c1=[endPoint[0]+ta[0]*ease,endPoint[1]+ta[1]*ease];
  const c2=[startPoint[0]-tb[0]*ease,startPoint[1]-tb[1]*ease];
  // One continuous silhouette, including both tail edges: no triangle laid on
  // a stroked body, no white seam-cover line, and no opaque-fill assumption.
  return path+curveText([endPoint,c1,mix(target,endPoint,.16),target])
    +curveText([target,mix(target,startPoint,.16),c2,startPoint])+"Z";
}
function bodySVG(element,role,x,y,w,h,pageHeight) {
  if (role.shape==="none") return "";
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
  const attrs=`fill="${role.fill}" stroke="${role.stroke}" stroke-width="${role.stroke_width}" stroke-linejoin="round"`;
  const path=outlinePath(curves,table,element.role==="speech"?attach:null,target,element.resolved.font_size,w,h);
  let puffs="";
  if (element.role==="thought" && attach) {
    const distance=Math.hypot(target[0]-attach.point[0],target[1]-attach.point[1]);
    puffs=[.28,.59,.86].map((t,i)=>{
      const p=mix(attach.point,target,t),r=Math.min(element.resolved.font_size*(.29-i*.075),distance*.11);
      return `<ellipse cx="${p[0]}" cy="${p[1]}" rx="${r}" ry="${r*.77}" ${attrs}/>`;
    }).join("");
  }
  return `<g transform="translate(${number(x)} ${number(y)})"><path data-balloon-body="${element.role}" d="${path}" ${attrs}/>${puffs}</g>`;
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
    if (!r.line_metrics || r.line_metrics.length!==r.lines.length ||
        ![r.font_size,r.line_height,r.width,r.height].every(Number.isFinite) ||
        r.line_metrics.some(m=>![m.x,m.baseline,m.width,m.ascent,m.descent].every(Number.isFinite))) {
      throw new Error("Lettering needs measured line positions before it can be rendered.");
    }
    const lines=r.lines.map((line,index)=>{
      const metric=r.line_metrics[index];
      return `<text x="${number(x+metric.x)}" y="${number(y+metric.baseline)}" text-anchor="start" font-family="${escape(role.font)}" font-size="${r.font_size}" font-weight="${role.font_weight ?? 400}" letter-spacing="${role.letter_spacing}" fill="${role.color}" stroke="${role.text_stroke}" stroke-width="${role.text_stroke_width}" paint-order="stroke fill" stroke-linejoin="round" xml:space="preserve">${escape(line)}</text>`;
    }).join("");
    return `<g data-lettering-id="${escape(element.id)}" transform="translate(${x+w/2} ${y+h/2}) rotate(${element.rotation}) scale(${element.scale}) translate(${-x-w/2} ${-y-h/2})">`+
      bodySVG(element,role,x,y,w,h,pageHeight)+lines+"</g>";
  }).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 1000 ${pageHeight}" role="img" aria-label="Page lettering" style="overflow:visible">${content}</svg>`;
}
