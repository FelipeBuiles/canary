import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { useI18n } from "../../i18n";
import { useShortViewport } from "../../hooks/useShortViewport";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";

export type LetteringMode = "integrated" | "editable";
const ASSETS = "/lettering-comparison";
const MODES = ["integrated", "editable"] as const;
const LABELS = { integrated: "Integrated lettering", editable: "Editable lettering" };
const SAMPLES = {
  3: { asset: "dcc-3", title: "DCC1.2", credit: "Dungeon Crawler Carl · Matt Dinniman", label: "Sound & motion", crop: { x: 650, y: 990, width: 374, height: 350 } },
  26: { asset: "cthulhu-26", title: "The Call of Cthulhu", credit: "H. P. Lovecraft", label: "Narration & detail", crop: { x: 400, y: 450, width: 550, height: 380 } },
  25: { asset: "cthulhu-25", title: "The Call of Cthulhu", credit: "H. P. Lovecraft", label: "Two speakers", crop: { x: 300, y: 950, width: 530, height: 420 } },
} as const;
type SamplePage = keyof typeof SAMPLES;
const SAMPLE_ORDER: SamplePage[] = [26, 25, 3];
type Crop = { x: number; y: number; width: number; height: number };
/** The trade in one glance: integrated wins on look, editable on changing words. */
const CHOICES = {
  integrated: {
    tag: "Best-looking",
    promise: "The words are painted with the page, like a hand-lettered comic.",
    ratings: { look: 5, words: 1 },
    pros: ["Sound effects and bursts painted into the action", "Balloons and captions shaped to each scene"],
    cons: ["Changing a word means redrawing the page. It uses credits and can change the art.", "Another language means drawing the pages again"],
    bestFor: "One finished edition you won't need to rewrite.",
  },
  editable: {
    tag: "Most flexible · safest if unsure",
    promise: "The art is finished. The words stay yours to fix, rewrite or translate.",
    ratings: { look: 3, words: 5 },
    pros: ["Fix typos or rewrite lines instantly, without credits", "Translate onto the same artwork"],
    cons: ["Sound effects use styled fonts and preset bursts, not hand-drawn letters", "Lettering reads clean and even rather than hand-made"],
    bestFor: "Books you'll keep polishing or publish in more than one language.",
  },
} as const;
/** The same moments side by side: where integrated wins (sound), where they tie (captions), where editable wins (translation). */
const COMPARE_VIEWS = ["sound", "captions", "translation"] as const;
type CompareView = typeof COMPARE_VIEWS[number];
const COMPARE_LABELS: Record<CompareView, string> = { sound: "Sound effects", captions: "Captions", translation: "Translation" };
const VIEW_CROPS: Record<CompareView, Crop> = {
  sound: { x: 540, y: 1004, width: 470, height: 176 },
  captions: { x: 16, y: 454, width: 992, height: 340 },
  translation: { x: 16, y: 454, width: 992, height: 340 },
};
/** Laptop-height windows keep the same moments in a wider strip so the whole choice fits. */
const SHORT_VIEW_CROPS: Record<CompareView, Crop> = {
  sound: { x: 540, y: 1008, width: 470, height: 156 },
  captions: { x: 16, y: 454, width: 992, height: 280 },
  translation: { x: 16, y: 454, width: 992, height: 280 },
};
const VIEW_TAGS: Record<CompareView, Record<LetteringMode, string>> = {
  sound: { integrated: "Painted with the art", editable: "Set on top of the art" },
  captions: { integrated: "Painted with the art", editable: "Set on top of the art" },
  translation: { integrated: "Spanish means redrawing every page", editable: "Spanish: same art, new words" },
};
const TRADEOFFS = [
  ["Look and feel", "Art, text, and balloons are drawn together. Often more expressive and closely integrated.", "Text and balloons are added separately. Consistent and adjustable, but may feel less integrated."],
  ["Sound effects & action", "Letters can be drawn with custom shapes, perspective, and texture as part of the action.", "Style, rotate, and resize effects with fonts, outlines, and preset shapes. Custom drawn letterforms are not reproduced automatically."],
  ["Typos and wording", "Request an image correction. It uses generation credits and may change the artwork too.", "Edit words without redrawing the art. Manual text edits use no generation credits."],
  ["Other languages", "Generate new pages for each language. Artwork can differ between versions.", "Reuse the artwork with translated text. AI translation uses credits; review font support and text fit."],
  ["Before exporting", "Read every page for missing words, typos, and reading order.", "Check text fit, balloon placement, and speaker tails, especially after edits or translation."],
] as const;

function CroppedImage({ src, alt, crop, onError, className = "" }: { src: string; alt: string; crop: Crop | null; onError?: () => void; className?: string }) {
  return <div className={`relative overflow-hidden ${className}`} style={{ aspectRatio: crop ? `${crop.width} / ${crop.height}` : "2 / 3" }}>
    <img src={src} alt={alt} width={1024} height={1536} loading="lazy" onError={onError} className="absolute max-w-none" style={{ top: crop ? `${-100 * crop.y / crop.height}%` : 0, left: crop ? `${-100 * crop.x / crop.width}%` : 0, width: crop ? `${102400 / crop.width}%` : "100%" }} />
  </div>;
}

function SampleImage({ page, mode, detail, spanish = false, hideLettering = false, motion = false }: { page: SamplePage; mode: LetteringMode; detail: boolean; spanish?: boolean; hideLettering?: boolean; motion?: boolean }) {
  const { t } = useI18n();
  const [failed, setFailed] = useState(false);
  const sample = SAMPLES[page];
  const baseOnly = mode === "editable" && hideLettering;
  const src = `${ASSETS}/${sample.asset}-${baseOnly ? "base" : mode}${spanish ? "-es" : ""}.webp`;
  const description = t(baseOnly ? "Editable artwork only" : LABELS[mode]);
  const crop = page === 3 && motion ? { x: 320, y: 570, width: 330, height: 310 } : sample.crop;
  return (
    <div>
      {failed ? <div role="status" className="bg-pulp-paper p-5 text-sm leading-relaxed">{t("This sample could not load. You can still compare the tradeoffs below.")} <Button type="button" variant="outline" onClick={() => setFailed(false)}>{t("TRY AGAIN")}</Button></div> : (
        <a href={src} target="_blank" rel="noopener noreferrer" aria-label={`${t("Open full-size sample")}: ${description}, ${t(sample.title)}, ${t("Page")} ${page}${spanish ? ", Español" : ", English"}`} className="block bg-pulp-paper focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red">
          <CroppedImage src={src} alt={`${t(sample.title)}, ${t("Page")} ${page} · ${description} · ${spanish ? "Español" : "English"}`} crop={detail ? crop : null} onError={() => setFailed(true)} />
        </a>
      )}
    </div>
  );
}

function useReducedMotion() {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => globalThis.matchMedia?.(query).matches ?? true);
  useEffect(() => {
    const media = globalThis.matchMedia?.(query);
    if (!media) return;
    const sync = () => setReduced(media.matches);
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  return reduced;
}

// The sandbox pulls in the lettering engine, so it loads only when this step opens.
const LetteringDemo = lazy(() => import("./LetteringDemo"));

/** Editable's proof: move the balloon and change its words on the real lettering engine. */
function EditableDemo({ crop }: { crop: Crop }) {
  const { t } = useI18n();
  const reducedMotion = useReducedMotion();
  const still = <CroppedImage src={`${ASSETS}/${SAMPLES[26].asset}-editable.webp`} alt={t("Editable lettering sample: artwork with a movable speech balloon")} crop={crop} />;
  return <Suspense fallback={still}><LetteringDemo crop={crop} autoplay={!reducedMotion} fallback={still} /></Suspense>;
}

function ComparisonImage({ mode, view }: { mode: LetteringMode; view: CompareView }) {
  const { t } = useI18n();
  const crop = (useShortViewport() ? SHORT_VIEW_CROPS : VIEW_CROPS)[view];
  if (mode === "editable" && view === "captions") return <EditableDemo crop={crop} />;
  const asset = view === "sound" ? SAMPLES[3].asset : SAMPLES[26].asset;
  const spanish = mode === "editable" && view === "translation";
  const alt = view === "sound"
    ? t(mode === "integrated" ? "Integrated lettering: the cat’s cry hand-drawn in a painted burst" : "Editable lettering: the cat’s cry in styled type on a preset burst")
    : t(mode === "integrated" ? "Integrated lettering: caption and balloon drawn into the panel" : spanish ? "Editable lettering: the same panel with its words in Spanish" : "Editable lettering: caption and balloon set above the finished art");
  return <CroppedImage src={`${ASSETS}/${asset}-${mode}${spanish ? "-es" : ""}.webp`} alt={alt} crop={crop} />;
}

function Rating({ label, value }: { label: string; value: number }) {
  const { t } = useI18n();
  return <>
    <span className="font-meta text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-ink-soft">{t(label)}</span>
    <span role="img" aria-label={t("{value} out of 5", { value })} className="flex gap-1">
      {[1, 2, 3, 4, 5].map((step) => <span key={step} className={cn("h-2.5 w-6", step <= value ? "bg-ink-black" : "border border-ink-black/30")} />)}
    </span>
  </>;
}

function ChoiceCard({ mode, view, selected, onChange }: { mode: LetteringMode; view: CompareView; selected: boolean; onChange: (value: LetteringMode) => void }) {
  const { t } = useI18n();
  const choice = CHOICES[mode];
  return <div className={cn(
    "flex flex-col overflow-hidden bg-bristol transition-[translate,box-shadow] duration-150",
    selected ? "border-2 border-ink-black shadow-[8px_8px_0_0_var(--color-narrator-gold),8px_8px_0_1px_var(--color-ink-black)]"
      : "border-2 border-ink-black/12 shadow-[4px_4px_0_0_var(--color-ghost-shadow)] hover:-translate-x-0.5 hover:-translate-y-0.5",
  )}>
    {/* The image sits outside the label so the live demo's controls stay separate from the choice. */}
    <div className="relative border-b border-ink-black/15 bg-preview-tint">
      <ComparisonImage mode={mode} view={view} />
      <span className="pointer-events-none absolute bottom-3 left-3 border border-ink-black bg-pulp-paper px-2 py-1 font-meta text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-ink-black">{t(VIEW_TAGS[view][mode])}</span>
    </div>
    <label className="flex flex-1 cursor-pointer flex-col gap-4 px-6 pb-6 pt-5 short:gap-3.5 short:pb-5 short:pt-4 group-disabled:cursor-wait">
      <span className="flex flex-wrap items-center gap-3">
        <input type="radio" name="letteringMode" value={mode} checked={selected} onChange={() => onChange(mode)} aria-describedby={`lettering-${mode}-details`} className="size-5 shrink-0 accent-hero-red" />
        <span className="font-display text-[1.375rem] font-black uppercase leading-none tracking-[-0.02em]">{t(LABELS[mode])}</span>
        <span className={cn("ml-auto px-2 py-1 font-meta text-xs font-semibold", mode === "integrated" ? "border border-ink-black bg-narrator-gold text-ink-black" : "border border-ready bg-chip-sage text-ready")}>{t(choice.tag)}</span>
      </span>
      <span id={`lettering-${mode}-details`} className="flex flex-col gap-4">
        <span className="text-base font-semibold leading-snug">{t(choice.promise)}</span>
        <span className="grid grid-cols-[9.5rem_auto] items-center gap-x-3.5 gap-y-2">
          <Rating label="Hand-made look" value={choice.ratings.look} />
          <Rating label="Changing words" value={choice.ratings.words} />
        </span>
        <span className="flex flex-col gap-2 border-t border-ink-black/12 pt-3.5 text-sm leading-5">
          {choice.pros.map((pro) => <span key={pro} className="flex gap-2.5"><span className="grid size-[18px] shrink-0 place-items-center bg-chip-sage text-[0.8125rem] font-bold leading-none text-ready"><span aria-hidden="true">+</span><span className="sr-only">{t("Pro:")}</span></span>{t(pro)}</span>)}
          {choice.cons.map((con) => <span key={con} className="flex gap-2.5"><span className="grid size-[18px] shrink-0 place-items-center bg-chip-red text-[0.8125rem] font-bold leading-none text-status-blocked-text"><span aria-hidden="true">−</span><span className="sr-only">{t("Con:")}</span></span>{t(con)}</span>)}
        </span>
        <span className="text-sm leading-5 text-ink-muted short:hidden"><strong className="text-ink-black">{t("Best for:")}</strong> {t(choice.bestFor)}</span>
      </span>
    </label>
  </div>;
}

export function LetteringChoice({ value, onChange, disabled, heading }: { value: LetteringMode | null; onChange: (value: LetteringMode) => void; disabled: boolean; heading?: ReactNode }) {
  const { t } = useI18n();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [view, setView] = useState<CompareView>("sound");
  return <div className="space-y-5 short:space-y-4">
    <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
      {heading}
      <div className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-2">
        <div role="group" aria-label={t("Compare")} className="flex items-center font-meta text-xs text-ink-muted">
          <span className="inline-flex border border-ink-black/55 bg-bristol">
            {COMPARE_VIEWS.map((key) => <button key={key} type="button" aria-pressed={view === key} onClick={() => setView(key)}
              className={cn("h-8 px-3 font-meta text-xs font-semibold transition-colors [&+&]:shadow-[inset_1px_0_0_rgb(27_28_21/0.12)]", view === key ? "bg-ink-black text-pulp-paper" : "text-ink-muted hover:bg-sidebar-tint hover:text-ink-black")}>
              {t(COMPARE_LABELS[key])}
            </button>)}
          </span>
        </div>
        <button type="button" aria-expanded={detailsOpen} aria-controls="lettering-details" onClick={() => setDetailsOpen(open => !open)}
          className="min-h-8 font-meta text-[0.8125rem] font-medium underline decoration-ink-black/35 underline-offset-4 hover:text-hero-red">
          {t("Compare in detail")}
        </button>
      </div>
    </div>
    <fieldset disabled={disabled} aria-describedby="lettering-consequence" className={`group ${disabled ? "opacity-60" : ""}`}>
      <legend className="sr-only">{t("Choose how your comic is lettered")}</legend>
      <div className="grid gap-6 md:grid-cols-2 lg:gap-8">
        {MODES.map(mode => <ChoiceCard key={mode} mode={mode} view={view} selected={value === mode} onChange={onChange} />)}
      </div>
      {/* The footer says this visibly beside Create project; screen readers hear it with the choice. */}
      <p id="lettering-consequence" className="sr-only">
        {t("This choice is permanent for this project.")} {t("Not sure? Choose editable lettering: it’s the one you can fix later.")}
      </p>
    </fieldset>

    {detailsOpen && <section id="lettering-details" aria-label={t("Compare in detail")} className="border-t border-ink-black/12 pt-2"><LetteringDetails /></section>}
  </div>;
}

/** Full comparison for careful readers: real pages, close-ups, the hidden layer, and every tradeoff. */
function LetteringDetails() {
  const { t } = useI18n();
  const [page, setPage] = useState<SamplePage>(26);
  const [detail, setDetail] = useState(false);
  const [hideLettering, setHideLettering] = useState(false);
  const [motion, setMotion] = useState(false);
  const sample = SAMPLES[page];
  return <div className="space-y-6 pb-4">
      <section aria-labelledby="lettering-samples-title">
      <h2 id="lettering-samples-title" className="font-display text-xl font-bold">{t("See the difference on a real page")}</h2>
      <p className="mt-2 text-sm leading-relaxed">{t("These are two ways of building a page, not just two fonts. Integrated words are pixels in the artwork. Editable words are separate objects placed over text-free art.")}</p>
      <div className="my-3 flex flex-wrap justify-between gap-3">
        <div role="group" aria-label={t("Example page")} className="flex flex-wrap gap-2">
          {SAMPLE_ORDER.map(number => <Button key={number} type="button" variant={page === number ? "secondary" : "outline"} aria-pressed={page === number} onClick={() => setPage(number)}>{t(SAMPLES[number].label)}</Button>)}
        </div>
        <Button type="button" variant="outline" aria-pressed={detail} onClick={() => setDetail(!detail)}>{t(detail ? "Show full pages" : "Compare close-ups")}</Button>
      </div>
      <p className="mb-2 text-sm leading-relaxed text-ink-muted">{t(sample.title)} · {sample.credit} · {t("Page")} {page} · {t("English samples")}</p>
      <p className="mb-3 text-sm leading-relaxed text-ink-muted">{t(page === 3 ? "Compare LEAP and the cat’s cry: the integrated letters and burst are drawn for this scene. The editable version uses Bangers, rotation, outlines, and a burst shape from the current editor." : detail ? "Magnified equally: compare the text spacing, balloon shape, and speaker tails. Switch to full pages to judge the whole composition." : page === 26 ? "Look at the long captions and the balloon beside the statue: spacing and placement shape the reading experience." : "Look at the two speech balloons: their size and tails need to lead you naturally from one speaker to the next.")}</p>
      {page === 3 && detail && <div role="group" aria-label={t("Sound-effect detail")} className="mb-3 flex flex-wrap gap-2">
        <Button type="button" variant={motion ? "outline" : "secondary"} aria-pressed={!motion} onClick={() => setMotion(false)}>{t("Cat’s cry")}</Button>
        <Button type="button" variant={motion ? "secondary" : "outline"} aria-pressed={motion} onClick={() => setMotion(true)}>{t("LEAP in motion")}</Button>
      </div>}
      <div className="mb-4 bg-surface-container p-4">
        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm font-bold">
          <input type="checkbox" checked={hideLettering} onChange={event => setHideLettering(event.target.checked)} className="h-5 w-5 shrink-0 accent-ink-black" />
          {t("Hide the editable lettering layer")}
        </label>
        <p className="mt-1 text-sm leading-relaxed" role="status">{t(hideLettering ? "Only the editable sample changes. Its artwork stays in place. Integrated lettering cannot be switched off: removing it requires an image edit." : "Try it: captions, balloons, and sound effects disappear from the editable sample. The integrated page stays as drawn.")}</p>
      </div>
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        {MODES.map((mode) => <figure key={mode}>
          <figcaption className="mb-2 text-sm leading-relaxed"><strong className="block font-body">{t(LABELS[mode])}</strong><span>{t(mode === "integrated" ? "One image: artwork and words drawn together" : hideLettering ? "Artwork only: lettering layer hidden" : "Two layers: artwork + editable words and shapes")}</span></figcaption>
          <SampleImage key={`${page}-${mode}-${detail}-${hideLettering}`} page={page} mode={mode} detail={detail} hideLettering={hideLettering} motion={motion} />
        </figure>)}
      </div>
      <p className="mt-3 text-sm leading-relaxed text-ink-muted">{t("Same words, matched composition, equal display size. Open either image to read it at full size.")}</p>
      <p className="mt-2 text-sm leading-relaxed text-ink-muted">{t("Prepared comparison: the editable sample uses AI-cleaned reference artwork and manually matched placement with our real lettering tools. It is not an automatic conversion or a prediction of your first generated page.")}</p>
    </section>

    <section aria-labelledby="lettering-tradeoffs-title">
      <h2 id="lettering-tradeoffs-title" className="font-display text-xl font-bold">{t("What this means for your book")}</h2>
      <div className="mt-3 divide-y-2 divide-ink-black/10">
        {TRADEOFFS.map(([heading, integrated, editable]) => <div key={heading} className="py-4">
          <h3 className="mb-2 font-body text-sm font-bold">{t(heading)}</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <p className="text-sm leading-relaxed"><strong className="block text-ink-muted">{t(LABELS.integrated)}</strong>{t(integrated)}</p>
            <p className="text-sm leading-relaxed"><strong className="block text-ink-muted">{t(LABELS.editable)}</strong>{t(editable)}</p>
          </div>
        </div>)}
      </div>
    </section>

    <details className="bg-surface-container p-4">
      <summary className="min-h-11 cursor-pointer py-2 font-body text-sm font-bold">{t("See a second language on the same artwork")}</summary>
      <p className="my-3 text-sm leading-relaxed">{t("Editable lettering · English and Spanish. This prepared translation keeps the same base art. Longer translations may need larger boxes or different placement; always review the result.")}</p>
      <div className="grid gap-5 sm:grid-cols-2">
        <figure><figcaption className="mb-2 text-sm font-bold">English</figcaption><SampleImage page={26} mode="editable" detail /></figure>
        <figure><figcaption className="mb-2 text-sm font-bold">Español</figcaption><SampleImage page={26} mode="editable" detail spanish /></figure>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-ink-muted">{t("With integrated lettering, this language change requires new image generation and can change the art.")}</p>
    </details>
  </div>;
}
