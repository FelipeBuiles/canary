import { lazy, Suspense, useEffect, useState } from "react";
import { useI18n } from "../../i18n";
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
type Crop = { x: number; y: number; width: number; height: number };
const CHOICES = {
  integrated: {
    promise: "Words drawn as part of the art.",
    strengths: ["Sound effects drawn into the action", "Balloons and captions shaped to each scene", "One cohesive, hand-made look"],
    cost: "Changing a word means redrawing the page. It uses credits and can change the art.",
    bestFor: "One finished edition that feels fully hand-drawn.",
  },
  editable: {
    promise: "The art is finished. The words stay yours.",
    strengths: ["Every word matches your script exactly", "Fix typos or rewrite lines instantly, without credits", "Translate onto the same artwork"],
    cost: "Sound effects use styled fonts and shapes, not hand-drawn letters.",
    bestFor: "Books you'll keep polishing or publish in more than one language.",
  },
} as const;
// Short, wide crops keep both cards’ text above the fold.
const HERO_CROPS = { integrated: { x: 316, y: 614, width: 348, height: 160 }, editable: { x: 400, y: 450, width: 600, height: 277 } } as const;
const SAMPLE_ORDER: SamplePage[] = [26, 25, 3];
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
function EditableHero() {
  const { t } = useI18n();
  const reducedMotion = useReducedMotion();
  const still = <div className="bg-pulp-paper"><CroppedImage src={`${ASSETS}/${SAMPLES[26].asset}-editable.webp`} alt={t("Editable lettering sample: artwork with a movable speech balloon")} crop={HERO_CROPS.editable} /></div>;
  return <Suspense fallback={still}><LetteringDemo crop={HERO_CROPS.editable} autoplay={!reducedMotion} fallback={still} /></Suspense>;
}

function IntegratedHero() {
  const { t } = useI18n();
  return <div className="bg-pulp-paper"><CroppedImage src={`${ASSETS}/${SAMPLES[3].asset}-integrated.webp`} alt={t("Integrated lettering sample: the word LEAP drawn into the cat’s motion")} crop={HERO_CROPS.integrated} /></div>;
}

function ChoiceCard({ mode, selected, onChange }: { mode: LetteringMode; selected: boolean; onChange: (value: LetteringMode) => void }) {
  const { t } = useI18n();
  const choice = CHOICES[mode];
  return <div className={`relative flex flex-col transition-colors ${selected ? "bg-chip-gold ring-[3px] ring-inset ring-ink-black" : "bg-surface-container ring-2 ring-inset ring-ink-black/15 hover:bg-pulp-paper"}`}>
    {/* The hero sits outside the label so its demo controls stay separate from the choice. */}
    <div className="p-[3px] pb-0">{mode === "integrated" ? <IntegratedHero /> : <EditableHero />}</div>
    <label className="flex flex-1 cursor-pointer flex-col p-4 group-disabled:cursor-wait">
      <span className="flex items-center gap-3">
        <input type="radio" name="letteringMode" value={mode} checked={selected} onChange={() => onChange(mode)} aria-describedby={`lettering-${mode}-details`} className="h-5 w-5 shrink-0 accent-ink-black" />
        <span className="font-display text-xl font-bold">{t(LABELS[mode])}</span>
      </span>
      <span id={`lettering-${mode}-details`} className="mt-2 block">
        <span className="block font-body text-base font-bold leading-snug">{t(choice.promise)}</span>
        <span className="mt-3 block space-y-1.5">
          {choice.strengths.map(strength => <span key={strength} className="flex gap-2 text-sm leading-snug"><span aria-hidden="true" className="font-bold">✓</span>{t(strength)}</span>)}
        </span>
        <span className="mt-3 block text-sm leading-snug text-ink-muted">{t(choice.cost)}</span>
        <span className="mt-3 block border-t-2 border-ink-black/10 pt-3 text-sm leading-snug"><strong>{t("Best for:")}</strong> {t(choice.bestFor)}</span>
      </span>
    </label>
  </div>;
}

export function LetteringChoice({ value, onChange, disabled }: { value: LetteringMode | null; onChange: (value: LetteringMode) => void; disabled: boolean }) {
  const { t } = useI18n();
  const [detailsOpen, setDetailsOpen] = useState(false);
  return <div className="mt-5 space-y-5">
    <fieldset disabled={disabled} aria-describedby="lettering-consequence" className={`group ${disabled ? "opacity-60" : ""}`}>
      <legend className="sr-only">{t("Choose how your comic is lettered")}</legend>
      <div className="grid gap-4 sm:grid-cols-2">
        {MODES.map(mode => <ChoiceCard key={mode} mode={mode} selected={value === mode} onChange={onChange} />)}
      </div>
      <p id="lettering-consequence" className="mt-4 text-sm leading-relaxed"><strong>{t("This choice is permanent for this project.")}</strong> {t("Not sure? Choose editable lettering: it’s the one you can fix later.")}</p>
    </fieldset>

    <details className="bg-surface-container px-4" onToggle={event => setDetailsOpen(event.currentTarget.open)}>
      <summary className="min-h-11 cursor-pointer py-3 font-body text-sm font-bold">{t("Compare in detail")}</summary>
      {detailsOpen && <LetteringDetails />}
    </details>
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
