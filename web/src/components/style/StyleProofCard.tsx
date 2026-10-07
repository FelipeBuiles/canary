import { useEffect, useRef, useState } from "react";
import { Check, Expand, EyeOff, Eye, Pencil, RotateCcw, ScanLine } from "lucide-react";
import { useImageGenerationMeta, useSetActiveStyle, useUpdateStylePresentation } from "../../api/queries";
import { isAuthorDirection, proofImageUrl, styleName, type StyleSuggestion } from "../../api/styles";
import { useI18n } from "../../i18n";
import { EntityCard } from "../composites";
import { Button } from "../ui/Button";
import { ImageGenerationPreview } from "../composites/ImageGenerationPreview";
import { GenerationDetailsModal } from "../ui/GenerationDetailsModal";
import { LazyImage } from "../ui/LazyImage";
import { Loupe } from "../ui/Loupe";
import { Stamp, usePress } from "../ui/motion";

const ROLE_LABELS: Record<string, string> = {
  story_fit_primary: "BEST FIT",
  story_fit_secondary: "STRONG FIT",
  story_fit_tertiary: "STRONG FIT",
  adjacent: "ADJACENT",
  contrast: "CONTRAST",
  wildcard: "WILDCARD",
  faithful: "YOUR DIRECTION",
};

const ICON_BUTTON = "flex min-h-11 min-w-11 items-center justify-center text-ink-muted hover:text-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red disabled:opacity-40";

export function StyleProofCard({
  suggestion,
  projectName,
  isGenerating,
  generationDisabled,
  retryDisabled,
  awaitingBatch = false,
  selectionDisabled,
  queueState,
  fallbackPrompt,
  fallbackParameters,
  isCompared,
  compareDisabled = false,
  onToggleCompare,
  validationBusy,
  onValidate,
  onRefresh,
  onRetry,
}: {
  suggestion: StyleSuggestion;
  projectName: string;
  isGenerating: boolean;
  /** Blocks auditions, which wait for proofs already drawing. */
  generationDisabled: boolean;
  /** Blocks queueing this proof again (retry or refresh); other proofs in flight do not. */
  retryDisabled: boolean;
  /** A batch (stage run or suggestion) is still drawing proofs that have not arrived. */
  awaitingBatch?: boolean;
  selectionDisabled: boolean;
  queueState: "queued" | "running" | null;
  fallbackPrompt: string;
  fallbackParameters: Record<string, unknown>;
  isCompared: boolean;
  compareDisabled?: boolean;
  onToggleCompare: () => void;
  validationBusy: boolean;
  onValidate: () => void;
  onRefresh: () => void;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  const name = styleName(suggestion);
  const yours = isAuthorDirection(suggestion);
  const presentation = useUpdateStylePresentation();
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(name);
  const [presentationError, setPresentationError] = useState<string | null>(null);
  const sampleUrl = proofImageUrl(projectName, suggestion);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [selectionConfirmed, setSelectionConfirmed] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const displayedProofUrl = `${sampleUrl}${sampleUrl.includes("?") ? "&" : "?"}t=${timestamp}`;
  const [proofLoad, setProofLoad] = useState({ url: displayedProofUrl, hasSample: suggestion.has_sample, failed: false });
  // Model changes can replace a cached preview URL with the saved raw proof.
  // Reset on each source change, including a return to the original model.
  if (proofLoad.url !== displayedProofUrl || proofLoad.hasSample !== suggestion.has_sample) {
    setProofLoad({ url: displayedProofUrl, hasSample: suggestion.has_sample, failed: false });
  }
  const imgFailed = !suggestion.has_sample || (proofLoad.url === displayedProofUrl && proofLoad.failed);
  const wasGenerating = useRef(isGenerating);
  // A finished proof seats with a press instead of fading in.
  const arrival = usePress(timestamp);
  const setActive = useSetActiveStyle();
  const { data: meta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `samples/style_${suggestion.index}.png`,
    isDetailsOpen,
    timestamp,
  );

  useEffect(() => {
    const wasGeneratingValue = wasGenerating.current;
    wasGenerating.current = isGenerating;
    if (!wasGeneratingValue || isGenerating) return;
    const timer = window.setTimeout(() => {
      setProofLoad((current) => ({ ...current, failed: false }));
      setTimestamp(Date.now());
    }, 0);
    return () => window.clearTimeout(timer);
  }, [isGenerating]);

  const showLoading = isGenerating
    || (!suggestion.has_sample && awaitingBatch && suggestion.generation_status !== "failed");
  const sampleRetryAvailable = !suggestion.has_sample && !isGenerating;
  const isActive = suggestion.is_active;
  const canSelect = suggestion.has_sample && !isActive && !isGenerating && !selectionDisabled && !setActive.isPending;

  const updatePresentation = (changes: { display_label?: string; hidden?: boolean }, onSuccess?: () => void) => {
    setPresentationError(null);
    presentation.mutate(
      { project: projectName, id: suggestion.id, changes },
      { onSuccess, onError: (error) => setPresentationError(error.message) },
    );
  };
  const saveName = () => {
    const next = draftName.trim();
    if (!next || next === name) {
      setRenaming(false);
      return;
    }
    updatePresentation({ display_label: next }, () => setRenaming(false));
  };

  const handleSelect = () => {
    if (!canSelect) return;
    setSelectionError(null);
    setActive.mutate(
      { project: projectName, id: suggestion.id },
      {
        onSuccess: () => setSelectionConfirmed(true),
        onError: (error) => setSelectionError(error.message),
      },
    );
  };

  const failed = suggestion.generation_status === "failed";
  const openDetails = () => setIsDetailsOpen(true);

  return (
    <>
      {/* Five rows, aligned across the grid: proof · name · fit · actions · details. */}
      {/* The grid has no row gap (a subgrid would absorb it into each section); the margin spaces rows. */}
      <EntityCard active={isActive} subgridRows={5} className="mb-8 min-w-0">
        <div className={`relative bg-surface-container ${arrival.className}`} onAnimationEnd={arrival.onAnimationEnd}>
          <ImageGenerationPreview project={projectName} target={`samples/style_${suggestion.index}.png`}
            active={showLoading} finalSrc={suggestion.has_sample ? displayedProofUrl : undefined} aspect="4 / 5"
            label={queueState === "queued" ? t("QUEUED") : t("GENERATING SAMPLES…")}>
          {imgFailed ? (
            <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-4 p-6 text-center">
              <div className={`font-meta text-[0.62rem] font-bold tracking-[0.1em] ${failed && !suggestion.has_sample ? "text-hero-red" : "text-ink-muted"}`}>
                {suggestion.has_sample ? t("PROOF IMAGE UNAVAILABLE") : t(failed ? "SAMPLE PROOF FAILED" : "PROOF NOT GENERATED")}
              </div>
              {sampleRetryAvailable && (
                <Button variant="outline" size="xs" disabled={retryDisabled} onClick={onRetry}>
                  <RotateCcw size={14} aria-hidden="true" />{t("TRY SAMPLE AGAIN")}
                </Button>
              )}
            </div>
          ) : (
            <Loupe>
              <LazyImage
                key={displayedProofUrl}
                src={displayedProofUrl}
                alt={name}
                loading="lazy"
                width={320}
                height={400}
                aspect="4 / 5"
                containerClassName="w-full"
                className="object-contain object-center"
                onError={() => setProofLoad((current) => current.url === displayedProofUrl ? { ...current, failed: true } : current)}
              />
              {/* The proof itself opens the full view; the corner mark only signals it. */}
              <button
                type="button"
                onClick={openDetails}
                aria-label={`${t("View proof and direction")} · ${name}`}
                className="group absolute inset-0 flex cursor-zoom-in items-start justify-end p-3 in-[.cursor-none]:cursor-none focus-visible:outline-[3px] focus-visible:-outline-offset-[3px] focus-visible:outline-hero-red"
              >
                <span
                  aria-hidden="true"
                  className="flex h-9 w-9 items-center justify-center border-[2px] border-bristol bg-ink-black/75 text-bristol transition-colors group-hover:bg-hero-red group-focus-visible:bg-hero-red"
                >
                  <Expand size={15} />
                </span>
              </button>
            </Loupe>
          )}

          </ImageGenerationPreview>

          {isActive && (
            <Stamp play={selectionConfirmed} onSettled={() => setSelectionConfirmed(false)} className="pointer-events-none absolute left-3 top-4 shadow-ink-sm">
              <Check size={14} aria-hidden="true" />{t("YOUR STYLE")}
            </Stamp>
          )}
        </div>

        <div className="min-w-0 px-5 pt-4">
          <div className="flex min-h-9 items-center gap-2">
            <span className="shrink-0 bg-pulp-paper px-2 py-1 font-meta text-[0.65rem] font-bold tracking-[0.06em] text-ink-muted">
              {yours ? t("YOURS") : t(ROLE_LABELS[suggestion.role ?? ""] ?? "DIRECTION")}
            </span>
            {suggestion.medium && <span className="min-w-0 truncate text-xs leading-5 text-ink-muted" title={suggestion.medium}>{suggestion.medium}</span>}
            <span className="-mr-2 ml-auto flex shrink-0 items-center">
              {yours && !renaming && (
                <button
                  type="button"
                  onClick={() => { setDraftName(name); setRenaming(true); }}
                  aria-label={`${t("Rename")} · ${name}`}
                  title={t("Rename")}
                  className={ICON_BUTTON}
                >
                  <Pencil size={15} aria-hidden="true" />
                </button>
              )}
              {!isActive && (
                <button
                  type="button"
                  disabled={presentation.isPending}
                  onClick={() => updatePresentation({ hidden: !suggestion.hidden })}
                  aria-label={`${t(suggestion.hidden ? "Show" : "Hide")} · ${name}`}
                  title={t(suggestion.hidden ? "Show" : "Hide")}
                  className={ICON_BUTTON}
                >
                  {suggestion.hidden ? <Eye size={15} aria-hidden="true" /> : <EyeOff size={15} aria-hidden="true" />}
                </button>
              )}
            </span>
          </div>
          {renaming ? (
            <form
              className="mt-2 flex flex-wrap items-center gap-2"
              onSubmit={(event) => { event.preventDefault(); saveName(); }}
            >
              <input
                autoFocus
                aria-label={t("Proof name")}
                value={draftName}
                maxLength={60}
                onChange={(event) => setDraftName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Escape") return;
                  event.preventDefault();
                  setRenaming(false);
                }}
                className="min-h-11 min-w-0 flex-[1_1_12rem] border-[2px] border-ink-black bg-bristol px-3 font-display text-lg font-black text-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
              />
              <Button type="submit" size="xs" disabled={presentation.isPending || !draftName.trim()}>{t("SAVE NAME")}</Button>
              <Button type="button" variant="outline" size="xs" onClick={() => setRenaming(false)}>{t("CANCEL")}</Button>
            </form>
          ) : (
            <h3 className="mt-2 line-clamp-3 text-balance font-display text-[1.45rem] font-black leading-[1.08] tracking-[-0.03em] text-ink-black" title={name}>
              {name}
            </h3>
          )}
          {yours && suggestion.origin !== "user_image" && suggestion.template && (
            <blockquote className="mt-2 line-clamp-2 border-l-[3px] border-narrator-gold pl-3 font-body text-sm italic leading-6 text-ink-black/75" title={suggestion.template}>
              “{suggestion.template}”
            </blockquote>
          )}
        </div>

        <div className="min-w-0 px-5 pt-4">
          {suggestion.story_fit && (
            <>
              <div className="font-meta text-[0.65rem] font-bold tracking-[0.06em] text-ink-muted">{t("WHY IT FITS")}</div>
              <p className="mt-1.5 font-body text-sm leading-6 text-ink-black">{suggestion.story_fit}</p>
            </>
          )}
        </div>

        <div className="min-w-0 px-5 pt-5">
          <div className="flex flex-wrap gap-2">
            <Button
              variant={isActive ? "secondary" : "primary"}
              size="sm"
              disabled={!canSelect}
              onClick={handleSelect}
              aria-pressed={isActive}
              className={`flex-[2_1_10rem] ${isActive ? "disabled:opacity-100 disabled:bg-narrator-gold disabled:text-ink-black" : ""}`}
              aria-busy={setActive.isPending}
            >
              {isActive && <Check size={16} aria-hidden="true" />}
              {setActive.isPending ? t("SELECTING…") : isActive ? t("YOUR STYLE") : t("SELECT THIS STYLE")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="flex-[1_1_6rem]"
              disabled={!isCompared && (compareDisabled || !suggestion.has_sample)}
              title={compareDisabled && !isCompared ? t("Three proofs added. Remove one to compare another.") : undefined}
              onClick={onToggleCompare}
              aria-pressed={isCompared}
            >
              {isCompared && <Check size={14} aria-hidden="true" />}
              {isCompared ? t("COMPARING") : t("COMPARE")}
            </Button>
          </div>
          {(selectionError || presentationError) && (
            <p role="alert" className="mt-3 bg-hero-red/10 p-3 text-sm leading-6 text-hero-red">
              {selectionError ?? presentationError}
            </p>
          )}
        </div>

        <div className="min-w-0 space-y-2 px-5 pb-5 pt-5">
          {suggestion.sample_stale && (
            <div className="flex items-center justify-between gap-3 bg-pulp-paper px-3 py-2">
              <span className="font-meta text-[0.62rem] font-bold tracking-[0.08em] text-ink-black/65">
                {t("REFRESH AVAILABLE")}
              </span>
              <Button
                variant="outline"
                size="xs"
                disabled={retryDisabled || isGenerating}
                onClick={onRefresh}
              >
                {t("REFRESH PROOF")}
              </Button>
            </div>
          )}
          <details className="group bg-surface-container px-3">
            <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold text-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
              {t("VISUAL DIRECTION")}
            </summary>
            <div className="pb-4">
              <p className="text-sm leading-6 text-ink-black">{suggestion.template}</p>
              <dl className="mt-5 space-y-4">
                {[
                  ["CHARACTER DESIGN", suggestion.character_design || ""],
                  ["PALETTE", suggestion.palette || t("Set by the direction")],
                  ["LINE & FINISH", suggestion.line_rendering || suggestion.medium],
                  ["LIGHTING", suggestion.lighting_value],
                  ["SEQUENTIAL STRENGTHS", suggestion.sequential_art_strengths],
                  ["WATCH FOR", suggestion.risk],
                ].filter(([, value]) => value).map(([label, value]) => (
                  <div key={label}>
                    <dt className="font-meta text-[0.65rem] font-bold tracking-[0.06em] text-ink-muted">{t(label)}</dt>
                    <dd className="mt-1 text-sm leading-6 text-ink-black">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </details>
          <details className="bg-surface-container px-3">
            <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold text-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
              {t("ACTION AUDITION")}
              {suggestion.has_validation && <span className="ml-2 font-normal text-ink-muted">{t("PROOF READY")}</span>}
              {validationBusy && <span className="ml-2 font-normal text-ink-muted">{t("TESTING IN ACTION…")}</span>}
            </summary>
            <div className="pb-4">
              <p className="mb-3 text-sm leading-6 text-ink-muted">{t("See how this direction handles a scene in motion.")}</p>
              {suggestion.has_validation && suggestion.validation_url && (
                <LazyImage
                  src={suggestion.validation_url}
                  alt={`${name} · ${t("ACTION AUDITION")}`}
                  loading="lazy"
                  width={320}
                  height={400}
                  aspect="4 / 5"
                  containerClassName="mb-4 w-full"
                  className="object-contain object-center"
                />
              )}
              <Button
                variant="outline"
                size="sm"
                disabled={validationBusy || generationDisabled}
                onClick={onValidate}
                aria-busy={validationBusy}
                className="w-full"
              >
                <ScanLine size={16} aria-hidden="true" />
                {validationBusy ? t("TESTING IN ACTION…") : suggestion.has_validation ? t("RETEST IN ACTION") : t("TEST IN ACTION")}
              </Button>
            </div>
          </details>
        </div>
      </EntityCard>
      <GenerationDetailsModal
        isOpen={isDetailsOpen}
        onClose={() => setIsDetailsOpen(false)}
        title={name}
        imageUrl={displayedProofUrl}
        metadata={meta}
        prompt={fallbackPrompt}
        parameters={fallbackParameters}
        isFallback={!meta}
        isLoading={isMetaLoading}
        imageAvailable={!imgFailed}
        overview={(
          <div className="space-y-5">
            <div>
              <div className="font-meta text-[0.54rem] tracking-[0.16em] text-ink-black/45">{t("VISUAL DIRECTION")}</div>
              <p className="mt-1 text-[0.8rem] leading-6 text-ink-black/75">{suggestion.template}</p>
            </div>
          </div>
        )}
      />
    </>
  );
}
