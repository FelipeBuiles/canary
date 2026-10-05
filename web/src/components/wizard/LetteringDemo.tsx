import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { canvasMeasure, elementRect, fontCSS, renderOverlay, resolvePage, type LetteringStyle, type Measure, type PageLettering, type Rect } from "@lettering-engine";
import { useI18n } from "../../i18n";

/** A one-balloon sandbox on the real lettering engine: nothing is saved and no API is involved. */
const SAMPLE = "/lettering-comparison";
const BALLOON = "lettering_0135";
type Locale = "source" | "es";
interface Sample { page: PageLettering; style: LetteringStyle; measure: Measure }

const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

async function loadSample(): Promise<Sample> {
  const [page, style] = await Promise.all([`${SAMPLE}/cthulhu-26.json`, `${SAMPLE}/style.json`].map(async url => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Sample unavailable: ${url}`);
    return response.json();
  }));
  // The sample only uses EB Garamond; loading every comic face would be wasted weight here.
  await document.fonts.load('24px "EB Garamond"');
  if (!document.fonts.check('24px "EB Garamond"')) throw new Error("Sample font unavailable");
  const measure = canvasMeasure();
  resolvePage(page, style, measure);
  return { page, style, measure };
}

function withBalloon(page: PageLettering, change: (element: PageLettering["elements"][number]) => Partial<PageLettering["elements"][number]>): PageLettering {
  return { ...page, elements: page.elements.map(element => element.id === BALLOON ? { ...element, ...change(element) } : element) };
}

/** Scripted rewrite of the last sentence, paced like a person: hold backspace, pause, then type
 * key by key with uneven gaps. The jitter is fixed so every loop (and test) plays the same. */
const KEY_JITTER = [0, 45, 15, 70, 25, 55, 5, 35];
function rewriteSteps(text: string): Array<{ text: string; delay: number }> {
  const cut = text.lastIndexOf(". ", text.length - 2);
  const prefix = cut > 0 ? text.slice(0, cut + 2) : `${text} `;
  const ending = "I shaped it in my sleep.";
  const steps: Array<{ text: string; delay: number }> = [];
  // Key repeat: a beat before the first deletion, then a steady run.
  for (let length = text.length - 1; length >= prefix.length; length--) steps.push({ text: text.slice(0, length), delay: length === text.length - 1 ? 420 : 30 });
  for (let index = 0; index < ending.length; index++) {
    const key = ending[index], previous = ending[index - 1];
    // Thinking before the first word, small hesitations between words and before the full stop.
    const delay = index === 0 ? 650 : 60 + KEY_JITTER[index % KEY_JITTER.length] + (previous === " " ? 90 : 0) + (/[.,!?]/.test(key) ? 140 : 0);
    steps.push({ text: prefix + ending.slice(0, index + 1), delay });
  }
  return steps;
}

export default function LetteringDemo({ crop, autoplay, fallback }: { crop: Rect; autoplay: boolean; fallback: ReactNode }) {
  const { t } = useI18n();
  const [sample, setSample] = useState<Sample | null>(null);
  const [page, setPage] = useState<PageLettering | null>(null);
  const [playing, setPlaying] = useState(autoplay);
  const [caption, setCaption] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const surface = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const balloon = useRef<HTMLButtonElement>(null);
  const drag = useRef<{ x: number; y: number; rect: DOMRect; base: PageLettering; origin: Rect; moved: boolean } | null>(null);

  useEffect(() => {
    let live = true;
    loadSample().then(next => { if (live) { setSample(next); setPage(next.page); } }).catch(() => { /* The still sample stays in place. */ });
    return () => { live = false; };
  }, []);

  // Crop bounds in page coordinates: the balloon never leaves the visible panel.
  const view = { x: crop.x / 1024, y: crop.y / 1536, width: crop.width / 1024, height: crop.height / 1536 };
  const { x: viewX, y: viewY, width: viewWidth, height: viewHeight } = view;
  const layout = useMemo(() => {
    if (!sample || !page) return null;
    try {
      let resolved = resolvePage(page, sample.style, sample.measure);
      // Longer words grow the balloon; slide it back inside the panel instead of clipping it.
      const grown = elementRect(resolved.elements.find(element => element.id === BALLOON)!);
      const x = clamp(grown.x, viewX, Math.max(viewX, viewX + viewWidth - grown.width));
      const y = clamp(grown.y, viewY, Math.max(viewY, viewY + viewHeight - grown.height));
      if (x !== grown.x || y !== grown.y) resolved = resolvePage(withBalloon(page, element => ({ placement: { ...element.placement, x, y } })), sample.style, sample.measure);
      return { svg: renderOverlay(resolved, sample.style), balloon: resolved.elements.find(element => element.id === BALLOON)! };
    } catch { return null; }
  }, [sample, page, viewX, viewY, viewWidth, viewHeight]);

  useEffect(() => {
    if (!sample || !playing) return;
    let live = true;
    const initial = sample.page;
    const original = initial.elements.find(element => element.id === BALLOON)!;
    const show = (next: PageLettering) => { if (live) setPage(next); };
    (async () => {
      while (live) {
        setCaption("Move the balloon");
        for (let frame = 1; frame <= 24 && live; frame++) {
          const eased = 1 - (1 - frame / 24) ** 3;
          show(withBalloon(initial, element => ({ placement: { ...element.placement, x: original.placement.x - .045 * eased, y: original.placement.y + .035 * eased } })));
          await sleep(28);
        }
        await sleep(900);
        if (!live) return;
        setCaption("Rewrite the words");
        const moved = withBalloon(initial, element => ({ placement: { ...element.placement, x: original.placement.x - .045, y: original.placement.y + .035 } }));
        for (const { text, delay } of rewriteSteps(original.text_by_locale.source)) {
          await sleep(delay);
          if (!live) return;
          show(withBalloon(moved, element => ({ text_by_locale: { ...element.text_by_locale, source: text } })));
        }
        await sleep(1300);
        if (!live) return;
        setCaption("Translate it");
        show({ ...moved, locale: "es" });
        await sleep(2400);
        if (!live) return;
        setCaption(null);
        show(initial);
        await sleep(1400);
      }
    })();
    return () => { live = false; };
  }, [sample, playing]);

  // Selected words make the first keystroke a rewrite; closing hands focus back to the balloon.
  const wasEditing = useRef(false);
  useEffect(() => {
    if (editing) field.current?.select();
    else if (wasEditing.current) balloon.current?.focus();
    wasEditing.current = editing;
  }, [editing]);

  if (!sample || !page || !layout) return <>{fallback}</>;
  const locale = page.locale as Locale;
  const rect = elementRect(layout.balloon);
  const text = layout.balloon.text_by_locale[locale] ?? "";
  const changed = JSON.stringify(page) !== JSON.stringify(sample.page);

  // The first touch takes over from the scripted demo and starts from the untouched page.
  function takeOver(): PageLettering {
    if (!playing) return page!;
    setPlaying(false);
    setCaption(null);
    setPage(sample!.page);
    return sample!.page;
  }
  // A grown balloon may be shown nudged inside the panel; edits continue from what is visible.
  function shown(base: PageLettering): Rect {
    return base === page ? layout!.balloon.placement : base.elements.find(element => element.id === BALLOON)!.placement;
  }
  function place(base: PageLettering, origin: Rect, dx: number, dy: number) {
    setPage(withBalloon(base, element => ({ placement: { ...element.placement,
      x: clamp(origin.x + dx, view.x, view.x + view.width - rect.width),
      y: clamp(origin.y + dy, view.y, view.y + view.height - rect.height) } })));
  }
  function down(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    const base = takeOver();
    const origin = shown(base);
    drag.current = { x: event.clientX, y: event.clientY, rect: surface.current!.getBoundingClientRect(), base, origin, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current;
    if (!current) return;
    const px = event.clientX - current.x, py = event.clientY - current.y;
    // Fingers wobble more than mice; small wobbles still count as a tap.
    if (Math.hypot(px, py) > (event.pointerType === "mouse" ? 4 : 10)) current.moved = true;
    if (!current.moved) return;
    // The surface shows view.width of the page across its own width.
    place(current.base, current.origin, px / current.rect.width * view.width, py / current.rect.height * view.height);
  }
  function up() {
    const current = drag.current;
    drag.current = null;
    if (current && !current.moved) openEditor();
  }
  function nudge(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); takeOver(); openEditor(); return; }
    const step = event.shiftKey ? .03 : .01;
    const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
    const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
    if (!dx && !dy) return;
    event.preventDefault();
    const base = takeOver();
    place(base, shown(base), dx, dy);
  }
  function openEditor() { setEditing(true); }
  function closeEditor() { setEditing(false); }
  function chooseLocale(next: Locale) {
    const base = takeOver();
    setPage({ ...base, locale: next });
  }

  const hint = playing ? caption : editing ? null : "Drag the balloon · tap it to edit the words";
  return <div className="relative bg-pulp-paper">
    <style>{fontCSS()}</style>
    <div ref={surface} className="relative overflow-hidden" style={{ aspectRatio: `${crop.width} / ${crop.height}` }}>
      <div className="absolute" style={{ top: `${-100 * crop.y / crop.height}%`, left: `${-100 * crop.x / crop.width}%`, width: `${102400 / crop.width}%`, aspectRatio: "2 / 3" }}>
        <img src={`${SAMPLE}/cthulhu-26-base.webp`} alt={t("Editable lettering sample: artwork with a movable speech balloon")} className="absolute inset-0 h-full w-full select-none" draggable={false} />
        <div className="pointer-events-none absolute inset-0" aria-hidden="true" dangerouslySetInnerHTML={{ __html: layout.svg }} />
        <button ref={balloon} type="button" aria-label={t("Speech balloon. Drag to move it, or press Enter to edit its words.")} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => { drag.current = null; }} onKeyDown={nudge}
          className="absolute cursor-move touch-none border-2 border-dashed border-transparent outline-none hover:border-ink-black/50 focus-visible:border-ink-black"
          style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.width * 100}%`, height: `${rect.height * 100}%` }} />
      </div>
    </div>
    <div className="absolute right-2 top-2 flex gap-2">
      {!playing && changed && !editing && <button type="button" onClick={() => setPage({ ...sample.page, locale })} className="min-h-8 bg-bristol px-2.5 text-xs font-bold ring-2 ring-ink-black hover:bg-surface-container">{t("Reset")}</button>}
      <div role="group" aria-label={t("Sample language")} className="flex bg-bristol text-xs font-bold ring-2 ring-ink-black">
        {(["source", "es"] as const).map(option => <button key={option} type="button" aria-pressed={locale === option} onClick={() => chooseLocale(option)} className={`min-h-8 px-2.5 ${locale === option ? "bg-ink-black text-bristol" : "hover:bg-surface-container"}`}>{option === "es" ? "ES" : "EN"}</button>)}
      </div>
    </div>
    {hint && <p aria-hidden="true" className="pointer-events-none absolute bottom-2 left-2 bg-ink-black px-2 py-1 text-xs font-bold text-bristol">{t(hint)}</p>}
    {/* Below the panel, so the balloon stays visible while it reflows. */}
    {editing && <div className="flex items-end gap-2 border-t-2 border-ink-black bg-bristol p-2">
      <textarea ref={field} aria-label={t("Words in the balloon")} rows={2} value={text} maxLength={180}
        onChange={event => setPage(withBalloon(page, element => ({ text_by_locale: { ...element.text_by_locale, [locale]: event.target.value } })))}
        onKeyDown={event => { if (event.key === "Escape" || (event.key === "Enter" && !event.shiftKey)) { event.preventDefault(); closeEditor(); } }}
        className="min-w-0 flex-1 resize-none bg-pulp-paper p-1.5 text-sm leading-snug" />
      <button type="button" onClick={closeEditor} className="min-h-8 bg-ink-black px-3 text-xs font-bold text-bristol">{t("Done")}</button>
    </div>}
  </div>;
}
