import { loadedCatalog } from "../locales/messages";
import { LANGUAGES } from "../locales/languages";

// Only literal catalog labels can opt in. Interpolated labels may contain author content.
const labels = new Set<string>();
const indexedCatalogs = new WeakSet<Record<string, string>>();

export function safeReplayLabel(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length > 80 || value.includes("{")) return undefined;
  // Displayed translations have already been loaded by I18nProvider. Index only
  // those trusted catalogs; never fetch unused languages for the recorder.
  for (const { code } of LANGUAGES) {
    const catalog = loadedCatalog(code);
    if (!catalog || indexedCatalogs.has(catalog)) continue;
    for (const [key, label] of Object.entries(catalog)) {
      if (!key.includes("{") && label && label.length <= 80 && !label.includes("{")) labels.add(label);
    }
    indexedCatalogs.add(catalog);
  }
  return labels.has(value) ? value : undefined;
}

export function replayText(text: string, label?: string): string {
  return label && safeReplayLabel(label) && text.trim() === label ? text : text.replace(/\S/g, "*");
}

export function applicationStylesheet(value: string): string | undefined {
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin === window.location.origin && /^\/assets\/[A-Za-z0-9_.-]+\.css$/.test(url.pathname)) return url.origin + url.pathname;
  } catch { /* Untrusted stylesheet. */ }
  return undefined;
}

/** Trust CSS loaded by the application build or Vite's application stylesheet. */
function trustedSheets(): CSSStyleSheet[] {
  return Array.from(document.styleSheets).filter(sheet => {
    if (sheet.href && applicationStylesheet(sheet.href)) return true;
    const owner = sheet.ownerNode as Element | null;
    // jsdom does not expose ownerNode; use the matching DOM style element too.
    const node = owner ?? Array.from(document.querySelectorAll("style")).find(node => node.sheet === sheet);
    return /(?:^|\/)src\/index\.css$/.test(node?.getAttribute("data-vite-dev-id") ?? "");
  });
}

function classNames(rules: CSSRuleList, names: Set<string>): void {
  for (const rule of Array.from(rules)) {
    if ("selectorText" in rule && typeof rule.selectorText === "string") {
      for (const match of rule.selectorText.matchAll(/\.((?:\\(?:[a-f0-9]{1,6}\s?|.)|[a-z0-9_-])+)/gi)) {
        names.add(match[1].replace(/\\([a-f0-9]{1,6}\s?|.)/gi, (_, escaped: string) =>
          /^[a-f0-9]{1,6}\s?$/i.test(escaped) ? String.fromCodePoint(parseInt(escaped.trim(), 16)) : escaped));
      }
    }
    if ("cssRules" in rule) classNames(rule.cssRules as CSSRuleList, names);
  }
}

const sheetClasses = new WeakMap<CSSStyleSheet, { count: number; first: CSSRule | undefined; last: CSSRule | undefined; names: Set<string> }>();
export function replayClasses(value: string): string | undefined {
  const sources: Set<string>[] = [];
  for (const sheet of trustedSheets()) {
    try {
      const rules = sheet.cssRules;
      let cached = sheetClasses.get(sheet);
      if (!cached || cached.count !== rules.length || cached.first !== rules[0] || cached.last !== rules[rules.length - 1]) {
        const classes = new Set<string>();
        classNames(rules, classes);
        cached = { count: rules.length, first: rules[0], last: rules[rules.length - 1], names: classes };
        sheetClasses.set(sheet, cached);
      }
      sources.push(cached.names);
    } catch { /* Inaccessible styles are omitted. */ }
  }
  const clean = value.split(/\s+/).filter(name => sources.some(names => names.has(name))).slice(0, 80).join(" ");
  return clean || undefined;
}

/** Reconstruct trusted CSS from the live app, never from serialized replay data. */
export function replayStylesheet(devId: unknown): string | undefined {
  if (typeof devId !== "string" || !/(?:^|\/)src\/index\.css$/.test(devId)) return undefined;
  const sheet = trustedSheets().find(sheet => Array.from(document.querySelectorAll("style"))
    .some(node => node.sheet === sheet && node.getAttribute("data-vite-dev-id") === devId));
  if (!sheet) return undefined;
  try {
    return Array.from(sheet.cssRules).map(rule => rule.cssText).join("\n").replace(/url\(([^)]*)\)/gi, (_match, target: string) => {
      const path = target.trim().replace(/^["']|["']$/g, "");
      try {
        const url = new URL(path, window.location.origin);
        if (url.origin === window.location.origin && /^\/(?:assets|fonts)\/[A-Za-z0-9_.-]+$/.test(url.pathname)) return `url("${url.origin}${url.pathname}")`;
      } catch { /* Drop content-bearing URLs. */ }
      return "url(\"\")";
    }).replace(/@import[^;]+;/gi, "");
  } catch { return undefined; }
}
