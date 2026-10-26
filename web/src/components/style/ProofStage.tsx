import type { KeyboardEvent } from "react";
import { ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import { styleName, type StyleSuggestion } from "../../api/styles";
import { useI18n } from "../../i18n";
import { ImageGenerationPreview } from "../composites/ImageGenerationPreview";
import { InspectButton } from "../ui/InspectButton";
import { LazyImage } from "../ui/LazyImage";
import { useProofImage } from "./useProofImage";

export const STAGE_BUTTON = "flex size-11 items-center justify-center border border-pulp-paper/22 bg-ink-black/70 text-pulp-paper transition-colors hover:bg-pulp-paper hover:text-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold";

/**
 * One proof under the lamp. Every proof draws the same scene, so stepping
 * through them in place is the honest comparison: arrow keys flip, and the
 * proof keeps its own failure and retry state.
 */
export function ProofStage({
  projectName,
  suggestion,
  position,
  count,
  isGenerating,
  awaitingBatch,
  queueState,
  retryDisabled,
  onRetry,
  onStep,
  inspectImages,
  inspectIndex,
  onInspectIndexChange,
}: {
  projectName: string;
  suggestion: StyleSuggestion;
  position: number;
  count: number;
  isGenerating: boolean;
  /** A batch (stage run or suggestion) is still drawing proofs that have not arrived. */
  awaitingBatch: boolean;
  queueState: "queued" | "running" | null;
  retryDisabled: boolean;
  onRetry: () => void;
  onStep: (delta: number) => void;
  inspectImages: { src: string; alt: string }[];
  inspectIndex: number;
  onInspectIndexChange: (index: number) => void;
}) {
  const { t } = useI18n();
  const name = styleName(suggestion);
  const image = useProofImage(projectName, suggestion, isGenerating);
  const failed = suggestion.generation_status === "failed";
  const showLoading = isGenerating
    || (!suggestion.has_sample && awaitingBatch && !failed);
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowRight") { event.preventDefault(); onStep(1); }
    if (event.key === "ArrowLeft") { event.preventDefault(); onStep(-1); }
  };

  return (
    <div
      tabIndex={0}
      role="group"
      aria-roledescription={t("proof")}
      aria-label={`${name}, ${position} / ${count}`}
      onKeyDown={keys}
      className="relative flex min-h-0 flex-1 items-center justify-center px-16 pb-5 pt-1 focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-narrator-gold"
    >
      <div className={`relative aspect-[4/5] w-[min(100%,calc(70svh*4/5))] max-w-full bg-ink-black studio-desktop:h-full studio-desktop:max-h-full studio-desktop:w-auto shadow-[0_30px_60px_-20px_rgb(0_0_0/0.75),0_0_0_1px_rgb(252_250_237/0.12)] ${image.arrival.className}`}
        onAnimationEnd={image.arrival.onAnimationEnd}>
        <ImageGenerationPreview project={projectName} target={`samples/style_${suggestion.index}.png`}
          active={showLoading} finalSrc={suggestion.has_sample ? image.src : undefined} aspect="4 / 5" surface="ink" className="h-full"
          label={queueState === "queued" ? t("Queued") : t("Drawing this proof…")}>
          {image.failed ? (
            <div className="benday-ink flex h-full w-full flex-col items-center justify-center gap-4 p-6 text-center text-pulp-paper">
              <p className={`font-meta text-sm font-semibold ${failed && !suggestion.has_sample ? "text-narrator-gold" : "text-on-chrome-muted"}`}>
                {suggestion.has_sample ? t("Proof image unavailable") : t(failed ? "This proof didn't finish" : "Not drawn yet")}
              </p>
              {!suggestion.has_sample && !isGenerating && (
                <button type="button" disabled={retryDisabled} onClick={onRetry}
                  className="inline-flex h-9 items-center gap-2 border border-pulp-paper/30 px-3 font-meta text-[0.8125rem] font-medium text-pulp-paper hover:bg-pulp-paper/10 disabled:opacity-45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold">
                  <RotateCcw size={14} aria-hidden="true" />{t("Try this proof again")}
                </button>
              )}
            </div>
          ) : (
            <>
              <LazyImage
                key={image.src}
                src={image.src}
                alt={name}
                width={1122}
                height={1402}
                containerClassName="h-full w-full"
                className="object-cover"
                onError={image.onError}
              />
              <InspectButton images={inspectImages} index={inspectIndex} onIndexChange={onInspectIndexChange} />
            </>
          )}
        </ImageGenerationPreview>
      </div>
      {count > 1 && (
        <>
          <button type="button" className={`${STAGE_BUTTON} absolute left-5 top-1/2 -translate-y-1/2`} onClick={() => onStep(-1)} aria-label={t("Previous proof")} title={`${t("Previous proof")} (←)`}>
            <ChevronLeft size={20} aria-hidden="true" />
          </button>
          <button type="button" className={`${STAGE_BUTTON} absolute right-5 top-1/2 -translate-y-1/2`} onClick={() => onStep(1)} aria-label={t("Next proof")} title={`${t("Next proof")} (→)`}>
            <ChevronRight size={20} aria-hidden="true" />
          </button>
        </>
      )}
    </div>
  );
}
