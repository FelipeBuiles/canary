import { useEffect, useRef, useState } from "react";
import { Check, Expand, ScanLine } from "lucide-react";
import { useImageGenerationMeta, useSetActiveStyle } from "../../api/queries";
import type { StyleSuggestion } from "../../api/styles";
import { useI18n } from "../../i18n";
import { EntityCard } from "../composites";
import { Button } from "../ui/Button";
import { FlowingDotsPlaceholder } from "../ui/FlowingDotsPlaceholder";
import { GenerationDetailsModal } from "../ui/GenerationDetailsModal";
import { LazyImage } from "../ui/LazyImage";

const ROLE_LABELS: Record<string, string> = {
  story_fit_primary: "BEST FIT",
  story_fit_secondary: "STRONG FIT",
  story_fit_tertiary: "STRONG FIT",
  adjacent: "ADJACENT",
  contrast: "CONTRAST",
  wildcard: "WILDCARD",
  faithful: "YOUR DIRECTION",
};

export function StyleProofCard({
  suggestion,
  projectName,
  isGenerating,
  generationDisabled,
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
}: {
  suggestion: StyleSuggestion;
  projectName: string;
  isGenerating: boolean;
  generationDisabled: boolean;
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
}) {
  const { t } = useI18n();
  const artUrl = `/api/projects/${encodeURIComponent(projectName)}/files/samples/style_${suggestion.index}.png`;
  const sampleUrl = suggestion.sample_preview_url ?? artUrl;
  const [imgFailed, setImgFailed] = useState(!suggestion.has_sample);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [selectionConfirmed, setSelectionConfirmed] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const displayedProofUrl = `${sampleUrl}${sampleUrl.includes("?") ? "&" : "?"}t=${timestamp}`;
  const wasGenerating = useRef(isGenerating);
  const setActive = useSetActiveStyle();
  const { data: meta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `samples/style_${suggestion.index}.png`,
    isDetailsOpen,
    timestamp,
  );

  useEffect(() => {
    if (!suggestion.has_sample) return;
    const timer = window.setTimeout(() => setImgFailed(false), 0);
    return () => window.clearTimeout(timer);
  }, [suggestion.has_sample]);

  useEffect(() => {
    const wasGeneratingValue = wasGenerating.current;
    wasGenerating.current = isGenerating;
    if (!wasGeneratingValue || isGenerating) return;
    const timer = window.setTimeout(() => {
      setImgFailed(false);
      setTimestamp(Date.now());
    }, 0);
    return () => window.clearTimeout(timer);
  }, [isGenerating]);

  const showLoading = isGenerating || (!suggestion.has_sample && generationDisabled);
  const sampleRetryAvailable = !suggestion.has_sample && !isGenerating && !generationDisabled;
  const isActive = suggestion.is_active;
  const canSelect = suggestion.has_sample && !isActive && !isGenerating && !selectionDisabled && !setActive.isPending;

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

  return (
    <>
      <EntityCard
        active={isActive}
        padding="tight"
        className="min-w-0"
        media={
          <div className="relative bg-surface-container">
            {showLoading ? (
              <FlowingDotsPlaceholder
                aspect="4 / 5"
                className="h-full w-full"
                label={queueState === "queued" ? t("QUEUED") : t("GENERATING SAMPLES…")}
              />
            ) : imgFailed ? (
              <div className="flex aspect-[4/5] w-full flex-col items-center justify-center">
                <div className="font-meta text-[0.58rem] font-bold tracking-[0.1em] text-ink-muted">
                  {suggestion.has_sample ? t("PROOF IMAGE UNAVAILABLE") : t(suggestion.generation_status === "failed" ? "SAMPLE PROOF FAILED" : "PROOF NOT GENERATED")}
                </div>
              </div>
            ) : (
              <LazyImage
                src={displayedProofUrl}
                alt={suggestion.label}
                loading="lazy"
                width={320}
                height={400}
                aspect="4 / 5"
                containerClassName="w-full"
                className="object-contain object-center"
                onError={() => setImgFailed(true)}
              />
            )}

            {isActive && (
              <div onAnimationEnd={() => setSelectionConfirmed(false)} className={`${selectionConfirmed ? "animate-register-stamp " : ""}absolute left-0 top-0 bg-narrator-gold px-3 py-1.5 font-meta text-xs font-bold text-ink-black shadow-ink-sm`}>
                <span className="flex items-center gap-2"><Check size={14} aria-hidden="true" />{t("YOUR STYLE")}</span>
              </div>
            )}

            <div className="absolute right-3 top-3 flex gap-1.5">
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setIsDetailsOpen(true); }}
                aria-label={`${t("View proof and direction")} · ${suggestion.label}`}
                className="flex min-h-11 items-center justify-center border-[2px] border-bristol bg-ink-black px-3 font-meta text-[0.68rem] font-bold tracking-[0.08em] text-bristol transition-colors hover:bg-hero-red"
              >
                <Expand size={14} className="mr-2" aria-hidden="true" />{t("VIEW PROOF")}
              </button>
            </div>
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="bg-pulp-paper px-2 py-1 font-meta text-[0.65rem] font-bold tracking-[0.06em] text-ink-muted">
            {t(ROLE_LABELS[suggestion.role ?? ""] ?? "DIRECTION")}
          </span>
          {suggestion.medium && <span className="text-xs leading-5 text-ink-muted">{suggestion.medium}</span>}
        </div>
        <h3 className="mt-3 text-balance font-display text-[1.7rem] font-black leading-[1.08] tracking-[-0.03em] text-ink-black">
          {suggestion.label}
        </h3>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button
            variant={isActive ? "secondary" : "primary"}
            size="sm"
            disabled={!canSelect}
            onClick={handleSelect}
            aria-pressed={isActive}
            className={`flex-[2_1_12rem] ${isActive ? "disabled:opacity-100 disabled:bg-narrator-gold disabled:text-ink-black" : ""}`}
            aria-busy={setActive.isPending}
          >
            {isActive && <Check size={16} aria-hidden="true" />}
            {setActive.isPending ? t("SELECTING…") : isActive ? t("YOUR STYLE") : t("SELECT THIS STYLE")}
          </Button>
          <Button variant="outline" size="sm" className="flex-[1_1_6rem]" disabled={compareDisabled} title={compareDisabled ? t("Three proofs added. Remove one to compare another.") : undefined} onClick={onToggleCompare} aria-pressed={isCompared}>
            {isCompared && <Check size={14} aria-hidden="true" />}
            {isCompared ? t("COMPARING") : t("COMPARE")}
          </Button>
        </div>
        {selectionError && (
          <p role="alert" className="mt-3 bg-hero-red/10 p-3 text-sm leading-6 text-hero-red">
            {selectionError}
          </p>
        )}
        {suggestion.story_fit && (
          <div className="mt-6">
            <div className="font-meta text-[0.65rem] font-bold tracking-[0.06em] text-ink-muted">{t("WHY IT FITS")}</div>
            <p className="mt-2 font-body text-sm leading-6 text-ink-black">{suggestion.story_fit}</p>
          </div>
        )}
        <div className="mt-5 space-y-2">
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
                  alt={`${suggestion.label} · ${t("ACTION AUDITION")}`}
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

        {suggestion.sample_stale && (
          <div className="mt-4 flex items-center justify-between gap-3 bg-pulp-paper px-3 py-2.5">
            <span className="font-meta text-[0.62rem] font-bold tracking-[0.08em] text-ink-black/65">
              {t("REFRESH AVAILABLE")}
            </span>
            <Button
              variant="outline"
              size="xs"
              disabled={generationDisabled || isGenerating}
              onClick={onRefresh}
            >
              {t("REFRESH PROOF")}
            </Button>
          </div>
        )}

        {sampleRetryAvailable && (
          <div className="mt-4 flex items-center justify-between gap-3 border-[2px] border-hero-red/35 bg-hero-red/10 px-3 py-2.5">
            <span className="font-meta text-[0.62rem] font-bold tracking-[0.08em] text-hero-red">
              {t(suggestion.generation_status === "failed" ? "SAMPLE PROOF FAILED" : "PROOF NOT GENERATED")}
            </span>
            <Button
              variant="outline"
              size="xs"
              disabled={generationDisabled || isGenerating}
              onClick={onRefresh}
            >
              {t("TRY SAMPLE AGAIN")}
            </Button>
          </div>
        )}

      </EntityCard>
      <GenerationDetailsModal
        isOpen={isDetailsOpen}
        onClose={() => setIsDetailsOpen(false)}
        title={suggestion.label}
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
