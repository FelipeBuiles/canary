import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { useSetActiveStyle } from "../../api/queries";
import { isAuthorDirection, proofImageUrl, styleName, type StyleSuggestion } from "../../api/styles";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { InspectButton } from "../ui/InspectButton";
import { usePress } from "../ui/motion";

/** Deterministic tilt per proof so the stack looks hand-dropped but never jitters. */
function tilt(seed: number, spread: number): number {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return ((x - Math.floor(x)) - 0.5) * spread;
}

/**
 * Every proof shows the same scene, so flipping through them is the fastest
 * honest comparison. Arrow keys flip; holding one flips quickly via key repeat.
 */
export function ProofFlipViewer({
  projectName,
  suggestions,
  index,
  onIndexChange,
  selectionDisabled,
}: {
  projectName: string;
  suggestions: StyleSuggestion[];
  index: number;
  onIndexChange: (index: number) => void;
  selectionDisabled: boolean;
}) {
  const { t } = useI18n();
  const setActive = useSetActiveStyle();
  const [error, setError] = useState<string | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const safeIndex = Math.min(Math.max(index, 0), Math.max(suggestions.length - 1, 0));
  const current = suggestions[safeIndex];
  const press = usePress(current?.id);

  useEffect(() => { stage.current?.focus({ preventScroll: true }); }, []);

  if (!current) return null;
  const go = (next: number) => onIndexChange((next + suggestions.length) % suggestions.length);
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowRight") { event.preventDefault(); go(safeIndex + 1); }
    if (event.key === "ArrowLeft") { event.preventDefault(); go(safeIndex - 1); }
  };
  const yours = isAuthorDirection(current);
  const name = styleName(current);
  const drawn = suggestions.filter((item) => item.has_sample);
  const behind = [2, 1].map((age) => suggestions[safeIndex - age]).filter((item): item is StyleSuggestion => !!item);
  const select = () => {
    setError(null);
    setActive.mutate({ project: projectName, id: current.id }, { onError: (failure) => setError(failure.message) });
  };

  return (
    <section aria-label={t("Flip through proofs")} className="bg-pulp-paper p-4 md:p-6">
      <div
        ref={stage}
        tabIndex={0}
        role="group"
        aria-roledescription={t("proof flipbook")}
        aria-label={`${yours ? `${t("Yours")} · ` : ""}${name}, ${safeIndex + 1} / ${suggestions.length}`}
        onKeyDown={keys}
        className="grid gap-6 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red md:grid-cols-[minmax(0,1fr)_minmax(0,18rem)] md:items-center"
      >
        <div className="relative mx-auto aspect-[4/5] w-full max-w-[min(100%,calc(72dvh*0.8))]">
          {behind.map((item) => {
            const age = safeIndex - suggestions.indexOf(item);
            return (
              <div
                key={item.id}
                aria-hidden="true"
                className="absolute inset-0 overflow-hidden border-[3px] border-ink-black bg-bristol shadow-ink brightness-[0.82]"
                style={{ transform: `translate(${age * 14}px, ${age * 9}px) rotate(${tilt(item.index, 5)}deg)` }}
              >
                <img src={proofImageUrl(projectName, item)} alt="" className="h-full w-full object-contain" />
              </div>
            );
          })}
          <div
            className={`absolute inset-0 overflow-hidden border-[3px] border-ink-black bg-bristol shadow-ink ${press.className}`}
            style={{ rotate: `${tilt(current.index, 1.6)}deg` }}
            onAnimationEnd={press.onAnimationEnd}
          >
            <img src={proofImageUrl(projectName, current)} alt={name} className="h-full w-full object-contain" />
            {current.has_sample && <InspectButton
              images={drawn.map((item) => ({ src: proofImageUrl(projectName, item), alt: styleName(item) }))}
              index={drawn.indexOf(current)}
              onIndexChange={(next) => onIndexChange(suggestions.indexOf(drawn[next]))}
            />}
          </div>
          {[1, 2].map((ahead) => suggestions[safeIndex + ahead]).filter(Boolean).map((item) => (
            <link key={item!.id} rel="preload" as="image" href={proofImageUrl(projectName, item!)} />
          ))}
        </div>
        <div className="min-w-0">
          <span className={`inline-block border-[3px] border-ink-black px-3 py-1.5 font-meta text-sm font-bold uppercase tracking-[0.1em] shadow-ink-sm ${yours ? "bg-hero-red text-bristol" : "bg-narrator-gold text-ink-black"}`}>
            {yours && `${t("Yours")} · `}{name}
          </span>
          <p className="mt-3 font-meta text-xs font-bold text-ink-muted" aria-live="polite">{safeIndex + 1} / {suggestions.length}</p>
          {current.story_fit && <p className="mt-3 font-body text-sm leading-6">{current.story_fit}</p>}
          <div className="mt-5 flex gap-2">
            <Button variant="outline" size="sm" aria-label={t("Previous proof")} onClick={() => go(safeIndex - 1)}><ChevronLeft size={16} aria-hidden="true" /></Button>
            <Button variant="outline" size="sm" aria-label={t("Next proof")} onClick={() => go(safeIndex + 1)}><ChevronRight size={16} aria-hidden="true" /></Button>
          </div>
          <Button
            className="mt-4 w-full"
            variant={current.is_active ? "secondary" : "primary"}
            aria-pressed={current.is_active}
            disabled={current.is_active || !current.has_sample || selectionDisabled || setActive.isPending}
            onClick={select}
          >
            {current.is_active && <Check size={16} aria-hidden="true" />}
            {setActive.isPending ? t("SELECTING…") : current.is_active ? t("YOUR STYLE") : t("SELECT THIS STYLE")}
          </Button>
          {error && <p role="alert" className="mt-3 text-sm text-hero-red">{error}</p>}
          <p className="mt-4 font-body text-xs leading-5 text-ink-muted">{t("Use ← and → to flip. Hold an arrow to flip quickly.")}</p>
        </div>
      </div>
    </section>
  );
}

/** Every proof as an equal card; clicking one opens it in the flipbook. */
export function ProofWall({
  projectName,
  suggestions,
  onOpen,
}: {
  projectName: string;
  suggestions: StyleSuggestion[];
  onOpen: (index: number) => void;
}) {
  const { t } = useI18n();
  return (
    <ul aria-label={t("Proof wall")} className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 xl:grid-cols-8">
      {suggestions.map((suggestion, index) => {
        const name = styleName(suggestion);
        return (
          <li key={suggestion.id}>
            <button
              type="button"
              onClick={() => onOpen(index)}
              aria-label={`${t("Flip to")} ${isAuthorDirection(suggestion) ? `${t("Yours")} · ` : ""}${name}`}
              title={name}
              className="block w-full border-[2px] border-ink-black bg-bristol transition-[transform,box-shadow] duration-[120ms] hover:-translate-x-[3px] hover:-translate-y-[3px] hover:shadow-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
            >
              <img src={proofImageUrl(projectName, suggestion)} alt="" loading="lazy" className="aspect-[4/5] w-full object-contain" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
