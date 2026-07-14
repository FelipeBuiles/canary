import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useGenerationJobs,
  useStyles,
  useSuggestStyles,
  useCreateStyleDirection,
  useSuggestStylesEstimate,
  useGenerateStyleSamples,
  useGenerateStyleValidation,
  useSetActiveStyle,
  useImageGenerationMeta,
  useProjectConfig,
  useStoryBible,
  useProjectStatus,
  useLetteringStyle,
  useGenerateLetteringStyle,
  useSetLetteringStyle,
  useStyleSampleEstimate,
  useStyleDirectionEstimate,
} from "../../api/queries";
import { Button } from "../../components/ui/Button";
import { GenerationDetailsModal } from "../../components/ui/GenerationDetailsModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StateBlock } from "../../components/ui/StateBlock";
import { Surface } from "../../components/ui/Surface";
import { ApprovalBar, EntityCard, RegenAction, RoomHeader, ConfirmDrawer, RerunStageAction, RoomShell, SectionHeader } from "../../components/composites";
import { useApproveStage, useStageEstimate } from "../../api/queries";
import { useRunAction } from "../../hooks/useRunAction";
import { useI18n } from "../../i18n";
import { FlowingDotsPlaceholder } from "../../components/ui/FlowingDotsPlaceholder";
import { LetteringChooser } from "../../components/compose/LetteringChooser";
import { StyleDirectionComposer, type StyleDirectionMode } from "../../components/style/StyleDirectionComposer";
import {
  useStyleGenStore,
  usePendingIndices,
  useStyleJobIds,
  useStyleJobStatuses,
} from "../../store/styleGen";
import { usePipelineStore } from "../../store/pipeline";
import type { StyleSuggestion } from "../../api/styles";
import type { StoryBible } from "../../types/api";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";

const ROLE_LABELS: Record<string, string> = {
  story_fit_primary: "BEST FIT",
  story_fit_secondary: "STRONG FIT",
  adjacent: "ADJACENT",
  contrast: "CONTRAST",
  wildcard: "WILDCARD",
  faithful: "YOUR DIRECTION",
};

function buildFallbackStyleSamplePrompt(suggestion: StyleSuggestion, storyBible: StoryBible | undefined): string {
  const charDesc =
    storyBible?.characters?.[0]?.visual_anchor?.trim() ||
    storyBible?.characters?.[0]?.name?.trim() ||
    "a mysterious cloaked figure";
  const locDesc =
    storyBible?.locations?.[0]?.visual_anchor?.trim() ||
    storyBible?.locations?.[0]?.name?.trim() ||
    "a dramatic atmospheric setting";
  return (
    `${suggestion.template}\n\n` +
    `${charDesc}. Set in: ${locDesc}. ` +
    "Medium shot, eye-level camera, dramatic lighting. " +
    "Portrait 4:5 aspect ratio. Fill the entire frame edge to edge - " +
    "no letterboxing, no pillarboxing, no border margins. " +
    "No text. No speech bubbles. No captions. Single panel only."
  );
}

function StyleCard({
  suggestion,
  projectName,
  isGenerating,
  generationDisabled,
  selectionDisabled,
  queueState,
  fallbackPrompt,
  fallbackParameters,
  isCompared,
  onToggleCompare,
  validationBusy,
  onValidate,
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
  onToggleCompare: () => void;
  validationBusy: boolean;
  onValidate: () => void;
}) {
  const { t } = useI18n();
  const sampleUrl = `/api/projects/${encodeURIComponent(projectName)}/files/samples/style_${suggestion.index}.png`;
  const [imgFailed, setImgFailed] = useState(!suggestion.has_sample);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const wasGenerating = useRef(isGenerating);
  const generateSamples = useGenerateStyleSamples();
  const setActive = useSetActiveStyle();
  const { add, attachJobs, remove } = useStyleGenStore();
  const { data: meta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `samples/style_${suggestion.index}.png`,
    isDetailsOpen,
    timestamp,
  );
  const { data: sampleEstimate } = useStyleSampleEstimate(projectName, isDetailsOpen);

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

  const handleGenerate = () => {
    setGenerationError(null);
    if (imgFailed) setImgFailed(true);
    add(projectName, [suggestion.index]);
    generateSamples.mutate(
      { project: projectName, ids: [suggestion.id] },
      {
        onSuccess: (data) => attachJobs(projectName, data.jobs),
        onError: (error) => {
          remove(projectName, [suggestion.index]);
          if (maybeShowInsufficientCredits(error, { actionLabel: "Regenerate style proof", onRetry: handleGenerate })) return;
          setGenerationError(error.message);
        },
      },
    );
  };

  const showLoading = isGenerating || (!suggestion.has_sample && generationDisabled);
  const isActive = suggestion.is_active;
  const canSelect = !isActive && !isGenerating && !selectionDisabled;

  // The card itself is the selection — no per-card select buttons.
  const handleCardClick = () => {
    if (!canSelect) return;
    setSelectionError(null);
    setActive.mutate(
      { project: projectName, id: suggestion.id },
      { onError: (error) => setSelectionError(error.message) },
    );
  };

  return (
    <>
      <EntityCard
        active={isActive}
        className={`min-h-[520px] ${isActive ? "!border-ink-black" : ""}`}
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
                  {t("NO STYLE SUGGESTIONS YET")}
                </div>
              </div>
            ) : (
              <LazyImage
                src={`${sampleUrl}?t=${timestamp}`}
                alt={suggestion.label}
                loading="lazy"
                width={320}
                height={400}
                aspect="4 / 5"
                containerClassName="w-full"
                className="object-cover object-center"
                onError={() => setImgFailed(true)}
              />
            )}

            {isActive && (
              <div className="animate-register-stamp absolute left-0 top-0 bg-narrator-gold px-3 py-1.5 font-meta text-[0.58rem] font-bold tracking-[0.1em] text-ink-black shadow-ink-sm">
                ✓ {t("YOUR STYLE")}
              </div>
            )}

            <div className="absolute right-3 top-3 flex gap-1.5">
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setIsDetailsOpen(true); }}
                aria-label={`${t("View proof and direction")} · ${suggestion.label}`}
                className="flex min-h-11 items-center justify-center border-[2px] border-bristol bg-ink-black px-3 font-meta text-[0.68rem] font-bold tracking-[0.08em] text-bristol transition-colors hover:bg-hero-red"
              >
                {t("VIEW PROOF")}
              </button>
            </div>
          </div>
        }
      >
        <div className="flex items-start justify-between gap-3">
          <div className="font-display text-[1.55rem] font-black leading-none tracking-[-0.03em] text-ink-black">
          {suggestion.label}
          </div>
          <span className="shrink-0 bg-pulp-paper px-2 py-1 font-meta text-[0.62rem] font-bold tracking-[0.08em] text-ink-black/65">
            {t(ROLE_LABELS[suggestion.role ?? ""] ?? "DIRECTION")}
          </span>
        </div>
        <p className="mt-3 font-body text-[0.92rem] font-semibold leading-relaxed text-ink-black/72">
          {suggestion.template}
        </p>

        <dl className="mt-5 grid gap-3 border-t-[2px] border-ink-black/10 pt-4 sm:grid-cols-2">
          <div>
            <dt className="font-meta text-[0.65rem] font-bold tracking-[0.08em] text-ink-black/50">{t("PALETTE")}</dt>
            <dd className="mt-1 text-[0.78rem] leading-5 text-ink-black/72">{suggestion.palette || t("Set by the direction")}</dd>
          </div>
          <div>
            <dt className="font-meta text-[0.65rem] font-bold tracking-[0.08em] text-ink-black/50">{t("LINE & FINISH")}</dt>
            <dd className="mt-1 text-[0.78rem] leading-5 text-ink-black/72">{suggestion.line_rendering || suggestion.medium}</dd>
          </div>
        </dl>

        {suggestion.story_fit && (
          <div className="mt-4 bg-surface-container px-3 py-3">
            <div className="font-meta text-[0.65rem] font-bold tracking-[0.08em] text-ink-black/55">{t("WHY IT FITS")}</div>
            <p className="mt-1 text-[0.8rem] leading-5 text-ink-black/75">{suggestion.story_fit}</p>
          </div>
        )}

        {suggestion.has_validation && suggestion.validation_url && (
          <div className="mt-4 border-t-[2px] border-ink-black/10 pt-4">
            <div className="font-meta text-[0.65rem] font-bold tracking-[0.08em] text-ink-black/55">{t("ACTION AUDITION")}</div>
            <LazyImage
              src={suggestion.validation_url}
              alt={`${suggestion.label} · ${t("ACTION AUDITION")}`}
              loading="lazy"
              width={320}
              height={400}
              aspect="4 / 5"
              containerClassName="mt-2 w-full"
              className="object-cover object-center"
            />
          </div>
        )}

        <div className="mt-auto flex flex-wrap gap-2 pt-5">
          <Button
            variant={isActive ? "secondary" : "primary"}
            size="sm"
            disabled={!canSelect}
            onClick={handleCardClick}
            aria-pressed={isActive}
            className="flex-1"
          >
            {isActive ? `✓ ${t("YOUR STYLE")}` : t("SELECT THIS STYLE")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onToggleCompare}
            aria-pressed={isCompared}
          >
            {isCompared ? t("COMPARING") : t("COMPARE")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={validationBusy || generationDisabled}
            onClick={onValidate}
            className="w-full"
          >
            {validationBusy
              ? t("TESTING IN ACTION…")
              : suggestion.has_validation
                ? t("RETEST IN ACTION")
                : t("TEST IN ACTION")}
          </Button>
        </div>
        {selectionError && (
          <div className="mt-2 font-meta text-[0.55rem] font-bold tracking-[0.06em] text-hero-red">
            {selectionError}
          </div>
        )}
      </EntityCard>
      <GenerationDetailsModal
        isOpen={isDetailsOpen}
        onClose={() => setIsDetailsOpen(false)}
        title={suggestion.label}
        imageUrl={`${sampleUrl}?t=${timestamp}`}
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
            <RegenAction
              assetLabel={suggestion.label}
              cost={sampleEstimate}
              hasImage={!imgFailed}
              allowInstruction={false}
              busy={isGenerating}
              busyLabel={queueState === "queued" ? t("QUEUED") : t("DRAWING…")}
              disabled={generationDisabled && !isGenerating}
              error={generationError}
              onRegenerate={handleGenerate}
            />
          </div>
        )}
      />
    </>
  );
}

export function StyleRoom() {
  const { t } = useI18n();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const projectName = id ?? "";
  const {
    data: stylesData,
    isLoading,
    isError: stylesLoadFailed,
    refetch: refetchStyles,
  } = useStyles(id);
  const { data: projectConfig } = useProjectConfig(id);
  const { data: lettering } = useLetteringStyle(id);
  const generateLettering = useGenerateLetteringStyle();
  const setLettering = useSetLetteringStyle();
  const { data: storyBible } = useStoryBible(id);
  const { data: status } = useProjectStatus(id);
  const suggestStyles = useSuggestStyles();
  const createStyleDirection = useCreateStyleDirection();
  const generateValidation = useGenerateStyleValidation();
  const { data: generationJobs } = useGenerationJobs(
    id,
    Object.values(useStyleJobIds(projectName)),
  );
  const [validationJobs, setValidationJobs] = useState<Record<string, string>>({});
  const { data: validationJobResults } = useGenerationJobs(id, Object.values(validationJobs));
  const pendingSet = usePendingIndices(projectName);
  const styleJobStatuses = useStyleJobStatuses(projectName);
  const { add, attachJobs, updateJob, remove } = useStyleGenStore();
  const events = usePipelineStore((s) => s.events);
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);
  const [sampleError, setSampleError] = useState<string | null>(null);
  const [suggestionStatus, setSuggestionStatus] = useState<"idle" | "running" | "failed">("idle");
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const [showSuggestConfirm, setShowSuggestConfirm] = useState(false);
  const [showDirectionComposer, setShowDirectionComposer] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showLetteringControls, setShowLetteringControls] = useState(false);
  const [pendingCustomInput, setPendingCustomInput] = useState<{
    direction: string;
    image: File | null;
    mode: StyleDirectionMode;
  } | null>(null);
  const [pendingValidation, setPendingValidation] = useState<StyleSuggestion | null>(null);

  const styleStage = status?.stages.style;
  const isStageGenerating = styleStage?.status === "running";
  const approveStage = useApproveStage();
  const { handleRun, isPending: isPipelineRunning } = useRunAction();
  const { data: castEstimate } = useStageEstimate(id, "cast");
  const styleSelected = !!status?.style_selected;

  const isSuggesting = suggestionStatus === "running";
  const styleActionsDisabled = isStageGenerating || isSuggesting || suggestStyles.isPending || createStyleDirection.isPending;
  const { data: suggestEstimate } = useSuggestStylesEstimate(id, !isSuggesting);
  const { data: directionEstimate } = useStyleDirectionEstimate(id, !createStyleDirection.isPending);

  const startSuggestions = useCallback((directionId?: string) => {
    clearEvents();
    setSuggestionStatus("running");
    setSuggestionError(null);
    suggestStyles.mutate(
      { project: projectName, directionId },
      {
        onSuccess: () => connect(projectName),
        onError: (err) => {
          setSuggestionStatus("failed");
          setSuggestionError(err.message);
        },
      },
    );
  }, [clearEvents, connect, projectName, suggestStyles]);

  useEffect(() => {
    if (!projectName || !generationJobs?.jobs.length) return;
    const timer = window.setTimeout(() => {
      for (const job of generationJobs.jobs) {
        const index = Number(job.payload.index);
        if (!Number.isFinite(index)) continue;
        if (job.status === "complete") {
          setSampleError(null);
          remove(projectName, [index]);
          refetchStyles();
        } else if (job.status === "failed") {
          setSampleError(job.error ?? "Sample generation failed");
          remove(projectName, [index]);
        } else {
          updateJob(projectName, job);
        }
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs, projectName, refetchStyles, remove, updateJob]);

  useEffect(() => {
    if (!validationJobResults?.jobs.length) return;
    const terminalJobs = validationJobResults.jobs.filter(
      (job) => job.status === "complete" || job.status === "failed",
    );
    if (!terminalJobs.length) return;
    const timer = window.setTimeout(() => {
      const finishedIds = new Set(terminalJobs.map((job) => String(job.payload.id ?? "")).filter(Boolean));
      setValidationJobs((current) => Object.fromEntries(
        Object.entries(current).filter(([suggestionId]) => !finishedIds.has(suggestionId)),
      ));
      const failure = terminalJobs.find((job) => job.status === "failed");
      if (failure) setSampleError(failure.error ?? t("Action audition failed"));
      if (terminalJobs.some((job) => job.status === "complete")) refetchStyles();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refetchStyles, t, validationJobResults]);

  // Track the suggest-more-styles SSE job: it streams stage_complete /
  // stage_fail under the "style_suggest" stage tag.
  useEffect(() => {
    if (!isSuggesting) return;
    for (let i = events.length - 1; i >= 0; i--) {
      const event = events[i];
      if (event.stage !== "style_suggest") continue;
      if (event.type === "stage_complete") {
        const timer = window.setTimeout(() => {
          setSuggestionStatus("idle");
          setSuggestionError(null);
          refetchStyles();
        }, 0);
        return () => window.clearTimeout(timer);
      }
      if (event.type === "stage_fail") {
        const timer = window.setTimeout(() => {
          setSuggestionStatus("failed");
          setSuggestionError(event.message ?? "Style suggestion failed");
        }, 0);
        return () => window.clearTimeout(timer);
      }
    }
  }, [events, isSuggesting, refetchStyles]);

  // Refetch styles whenever the style pipeline stage emits progress so that
  // newly written sample images appear as soon as each one finishes.
  useEffect(() => {
    if (!events.length) return;
    const last = events[events.length - 1];
    if (last.stage !== "style" && last.stage !== "style_suggest") return;
    if (last.type !== "stage_progress" && last.type !== "stage_complete") return;
    refetchStyles();
  }, [events, refetchStyles]);

  // Auto-tune lettering once when a style is selected but not yet matched.
  const autoLetteringRef = useRef(false);
  useEffect(() => {
    if (!id || !styleSelected || !lettering) return;
    if (lettering.label || autoLetteringRef.current) return;
    autoLetteringRef.current = true;
    generateLettering.mutate({ project: id });
  }, [id, styleSelected, lettering, generateLettering]);

  if (isLoading) {
    return <RoomShell project={id ?? ""} isLoading loadingText="MIXING PALETTES…" />;
  }

  if (!id) {
    return (
      <RoomShell
        project={id ?? ""}
        isEmpty
        emptyTitle="STYLES UNAVAILABLE"
        emptyDescription="Select a project first."
      />
    );
  }

  const suggestions = stylesData?.suggestions ?? [];

  const styleNeedsApproval = styleStage?.status === "awaiting_review";
  const castStarted = status?.stages.cast?.status != null && status.stages.cast.status !== "pending";

  function handleContinueToCast() {
    if (!id) return;
    const startCastIfNeeded = () => {
      if (!castStarted) handleRun(id, "cast", { actionLabel: "Cast characters & places" });
      navigate(`/project/${id}/cast`);
    };

    if (styleNeedsApproval && styleSelected) {
      approveStage.mutate(
        { project: id, stage: "style" },
        {
          onSuccess: () => {
            startCastIfNeeded();
          },
        },
      );
    } else {
      // A previously approved style can leave cast pending when the user
      // returns to this room. Continuing must still launch the missing run.
      if (styleSelected) startCastIfNeeded();
      else navigate(`/project/${id}/cast`);
    }
  }

  function createCustomDirection(input: { direction: string; image: File | null; mode: StyleDirectionMode }) {
    setSuggestionError(null);
    createStyleDirection.mutate(
      {
        project: projectName,
        direction: input.direction,
        image: input.image,
        withNeighbors: input.mode === "neighbors",
      },
      {
        onSuccess: (data) => {
          if (data.direction.has_image && !data.direction.image_supported) {
            setSampleError(t("The uploaded image was saved, but this image model used your text description for the proof."));
          }
          add(projectName, [data.suggestion.index]);
          attachJobs(projectName, [data.job]);
          setShowDirectionComposer(false);
        },
        onError: (error) => {
          setSuggestionStatus("failed");
          setSuggestionError(error.message);
        },
      },
    );
  }

  function toggleCompare(idToToggle: string) {
    setCompareIds((current) => {
      if (current.includes(idToToggle)) return current.filter((id) => id !== idToToggle);
      if (current.length >= 3) return [...current.slice(1), idToToggle];
      return [...current, idToToggle];
    });
  }

  const anyGenerating = pendingSet.size > 0;
  const runningStyleCount = Object.values(styleJobStatuses).filter((status) => status === "running").length;
  const queuedStyleCount = Object.values(styleJobStatuses).filter((status) => status === "queued").length;
  const effectiveSteps = projectConfig?.dev_mode
     ? Math.min(projectConfig?.image_steps ?? 0, projectConfig?.dev_image_steps ?? 0)
     : projectConfig?.image_steps;
  const comparedSuggestions = compareIds
    .map((suggestionId) => suggestions.find((suggestion) => suggestion.id === suggestionId))
    .filter((suggestion): suggestion is StyleSuggestion => !!suggestion);

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker="LOOK"
        title="CHOOSE THE LOOK"
        lead="Choose one visual direction. Scenewright carries it through characters, places, and panels."
        actions={suggestions.length > 0 ? (
          <div className="flex items-center gap-3">
            {anyGenerating && (
              <span role="status" aria-live="polite" className="font-meta text-[0.68rem] font-bold tracking-[0.08em] text-ink-black/65">
                {runningStyleCount > 0 && `${runningStyleCount} ${t("RUNNING")}`}{runningStyleCount > 0 && queuedStyleCount > 0 && " / "}{queuedStyleCount > 0 && `${queuedStyleCount} ${t("QUEUED")}`}
              </span>
            )}
            {sampleError && (
              <span role="alert" className="text-[0.75rem] font-semibold text-hero-red">
                {sampleError}
              </span>
            )}
            <div className="flex flex-col items-end gap-1">
              <Button
                size="sm"
                variant="primary"
                onClick={() => setShowDirectionComposer((visible) => !visible)}
                disabled={styleActionsDisabled}
              >
                {showDirectionComposer ? t("CLOSE ART DIRECTION") : t("ADD A DIRECTION")}
              </Button>
            </div>
          </div>
        ) : undefined}
      />

      {(isSuggesting || isStageGenerating || suggestionStatus === "failed") && (
        <div className={`mt-4 border-[2px] border-ink-black p-3 ${
          suggestionStatus === "failed" ? "bg-hero-red text-bristol" : "bg-narrator-gold text-ink-black"
        }`} role={suggestionStatus === "failed" ? "alert" : "status"} aria-live="polite">
          <div className="flex items-center gap-2">
            {(isSuggesting || isStageGenerating) && <span className="animate-press-blink h-2.5 w-2.5 bg-hero-red" />}
            <span className="font-meta text-[0.7rem] font-bold tracking-[0.08em]">
              {suggestionStatus === "failed"
                ? t("STYLE SUGGESTION FAILED")
                : isStageGenerating
                  ? t("GENERATING STYLE OPTIONS")
                  : t("GENERATING ADDITIONAL STYLES")}
            </span>
          </div>
          <div className="mt-1 font-body text-[0.84rem] leading-relaxed">
            {suggestionStatus === "failed"
              ? suggestionError
              : t("Asking the art director for visual directions and rendering one sample image per style. Samples appear as they complete.")}
          </div>
        </div>
      )}

      {stylesLoadFailed ? (
        <Surface padding="lg" className="mt-6">
          <StateBlock
            minHeight="min-h-[22vh]"
            title={t("WE COULDN'T LOAD THE PROOFS")}
            description={t("The style room could not reach the project. Your existing work is unchanged.")}
            icon="styles"
            tone="danger"
            action={<Button size="sm" onClick={() => refetchStyles()}>{t("TRY AGAIN")}</Button>}
          />
        </Surface>
      ) : suggestions.length === 0 && !isStageGenerating && !isSuggesting ? (
        <div className="mt-6">
          <StyleDirectionComposer
            automaticCost={suggestEstimate?.estimate_credits}
            customSingleCost={directionEstimate?.estimates.faithful.estimate_credits}
            customNeighborsCost={directionEstimate?.estimates.faithful_with_neighbors.estimate_credits}
            customSingleReferenceCost={directionEstimate?.estimates_with_reference.faithful.estimate_credits}
            customNeighborsReferenceCost={directionEstimate?.estimates_with_reference.faithful_with_neighbors.estimate_credits}
            imageReferenceSupported={directionEstimate?.image_reference_supported}
            busy={styleActionsDisabled || !suggestEstimate || !directionEstimate}
            error={suggestionError}
            onAutomatic={() => setShowSuggestConfirm(true)}
            onCustom={setPendingCustomInput}
          />
        </div>
      ) : suggestions.length === 0 ? (
        <Surface padding="lg" className="mt-6">
          <StateBlock
            minHeight="min-h-[22vh]"
            title={t("GENERATING STYLE OPTIONS")}
            description={t("Five art-directed proofs are on the way. Each appears as soon as it is ready.")}
            icon="styles"
          />
        </Surface>
      ) : (
        <>
          {showDirectionComposer && (
            <div className="mt-6">
              <StyleDirectionComposer
                automaticCost={suggestEstimate?.estimate_credits}
                customSingleCost={directionEstimate?.estimates.faithful.estimate_credits}
                customNeighborsCost={directionEstimate?.estimates.faithful_with_neighbors.estimate_credits}
                customSingleReferenceCost={directionEstimate?.estimates_with_reference.faithful.estimate_credits}
                customNeighborsReferenceCost={directionEstimate?.estimates_with_reference.faithful_with_neighbors.estimate_credits}
                imageReferenceSupported={directionEstimate?.image_reference_supported}
                busy={styleActionsDisabled || !suggestEstimate || !directionEstimate}
                error={suggestionError}
                onAutomatic={() => setShowSuggestConfirm(true)}
                onCustom={setPendingCustomInput}
              />
            </div>
          )}

          {comparedSuggestions.length >= 2 && (
            <section className="mt-8 bg-ink-black p-4 text-bristol md:p-6">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="font-meta text-[0.68rem] font-bold tracking-[0.1em] text-narrator-gold">{t("COMPARE PROOFS")}</div>
                  <p className="mt-1 text-[0.82rem] text-bristol/70">{t("Equal-size proofs make palette, finish, and story fit easier to judge.")}</p>
                </div>
                <Button variant="onInk" size="xs" onClick={() => setCompareIds([])}>{t("CLEAR")}</Button>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {comparedSuggestions.map((suggestion) => (
                  <div key={suggestion.id} className="bg-bristol p-3 text-ink-black">
                    <LazyImage
                      src={`/api/projects/${encodeURIComponent(id)}/files/samples/style_${suggestion.index}.png`}
                      alt={suggestion.label}
                      width={320}
                      height={400}
                      aspect="4 / 5"
                      className="object-cover object-center"
                    />
                    <div className="mt-3 font-display text-[1.1rem] font-black uppercase tracking-[-0.025em]">{suggestion.label}</div>
                    <p className="mt-1 text-[0.76rem] leading-5 text-ink-black/70">{suggestion.palette}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="mt-10">
            <SectionHeader
              variant="underline"
              title="STYLE PROOFS"
              description="Every direction uses the same story-specific audition. Select up to three to compare; choosing one never moves the cards."
            />
            <div className="grid gap-6 lg:grid-cols-2">
              {suggestions.map((suggestion) => (
                  <StyleCard
                    key={suggestion.id}
                    suggestion={suggestion}
                    projectName={id}
                    isGenerating={pendingSet.has(suggestion.index)}
                    generationDisabled={styleActionsDisabled}
                    selectionDisabled={isStageGenerating}
                    queueState={pendingSet.has(suggestion.index) ? styleJobStatuses[suggestion.index] ?? "queued" : null}
                    fallbackPrompt={buildFallbackStyleSamplePrompt(suggestion, storyBible)}
                    fallbackParameters={{
                      width: projectConfig?.image_width,
                      height: projectConfig?.image_height,
                      steps: effectiveSteps,
                      guidance_scale: projectConfig?.flux_guidance_scale,
                      style_template: suggestion.template,
                    }}
                    isCompared={compareIds.includes(suggestion.id)}
                    onToggleCompare={() => toggleCompare(suggestion.id)}
                    validationBusy={suggestion.id in validationJobs}
                    onValidate={() => setPendingValidation(suggestion)}
                  />
              ))}
            </div>
          </section>

          {suggestions.length > 0 && suggestions.every((suggestion) => suggestion.has_sample) && (
            <p className="mt-4 font-meta text-[0.68rem] font-bold tracking-[0.08em] text-ink-black/60">
              ✓ {t("EVERY COMPLETED PROOF USES THE SAME STORY-SPECIFIC AUDITION")}
            </p>
          )}

          {styleSelected && (
            <Surface border="soft" shadow="none" padding="md" className="mt-10">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-meta text-[0.68rem] font-bold tracking-[0.1em] text-ink-black/60">{t("LETTERING")}</div>
                  <p className="mt-1 text-[0.86rem] text-ink-black/72">
                    {lettering?.label ? `${t("Matched automatically:")} ${lettering.label}` : t("Lettering will be matched automatically to the selected style.")}
                  </p>
                </div>
                <Button variant="outline" size="sm" onClick={() => setShowLetteringControls((visible) => !visible)}>
                  {showLetteringControls ? t("HIDE CONTROLS") : t("CUSTOMIZE")}
                </Button>
              </div>
              {showLetteringControls && (
                <LetteringChooser
                  lettering={lettering}
                  isGenerating={generateLettering.isPending || setLettering.isPending}
                  disabled={styleActionsDisabled}
                  onMatchMyStyle={() =>
                    id &&
                    setLettering.mutate(
                      { project: id, mode: "auto" },
                      { onSuccess: () => generateLettering.mutate({ project: id }) },
                    )
                  }
                  onReroll={() => id && generateLettering.mutate({ project: id, reroll: true })}
                  onSelectPreset={(preset) => id && setLettering.mutate({ project: id, mode: "preset", preset })}
                />
              )}
            </Surface>
          )}
        </>
      )}

      <ApprovalBar
        next={styleSelected
          ? t("Scenewright casts your characters and places in this style")
          : t("Pick a style — click the card that fits your story")}
        estimateCredits={styleSelected && styleNeedsApproval ? castEstimate?.estimate_credits : null}
        primaryLabel={styleNeedsApproval || !styleSelected ? t("LOOKS RIGHT — CONTINUE →") : t("GO TO CAST →")}
        onPrimary={handleContinueToCast}
        primaryDisabled={!styleSelected || approveStage.isPending || isPipelineRunning || isStageGenerating || isSuggesting}
        busy={approveStage.isPending}
        secondary={suggestions.length > 0 && (styleStage?.status === "complete" || styleStage?.status === "awaiting_review") ? (
          <RerunStageAction
            project={id}
            stage="style"
            label="styles"
            disabled={isPipelineRunning || isStageGenerating || isSuggesting}
          />
        ) : undefined}
      />

      <ConfirmDrawer
        open={showSuggestConfirm}
        title="Suggest more styles?"
        body="Generates five additional style descriptions and sample images. Credits are reserved now and settled to actual usage."
        cost={suggestEstimate}
        confirmLabel="Suggest"
        busy={suggestStyles.isPending || isSuggesting}
        onConfirm={() => {
          setShowSuggestConfirm(false);
          startSuggestions();
        }}
        onClose={() => setShowSuggestConfirm(false)}
      />
      <ConfirmDrawer
        open={pendingCustomInput !== null}
        title={pendingCustomInput?.mode === "neighbors" ? t("Create five directed proofs?") : t("Create this proof?")}
        body={pendingCustomInput?.mode === "neighbors"
          ? t("Creates one faithful proof and four deliberately varied neighbors around your direction.")
          : t("Creates one story-specific proof from your text, visual reference, or both.")}
        cost={pendingCustomInput?.mode === "neighbors"
          ? pendingCustomInput.image && directionEstimate?.image_reference_supported
            ? directionEstimate.estimates_with_reference.faithful_with_neighbors
            : directionEstimate?.estimates_without_reference.faithful_with_neighbors
          : pendingCustomInput?.image && directionEstimate?.image_reference_supported
            ? directionEstimate.estimates_with_reference.faithful
            : directionEstimate?.estimates_without_reference.faithful}
        confirmLabel={pendingCustomInput?.mode === "neighbors" ? t("CREATE FIVE DIRECTIONS") : t("CREATE MY PROOF")}
        busy={createStyleDirection.isPending}
        onConfirm={() => {
          if (!pendingCustomInput) return;
          const input = pendingCustomInput;
          setPendingCustomInput(null);
          createCustomDirection(input);
        }}
        onClose={() => setPendingCustomInput(null)}
      />
      <ConfirmDrawer
        open={pendingValidation !== null}
        title={t("Test this style in action?")}
        body={t("Generates an optional second proof using a readable action silhouette, expressive face and hands, and a layered environment.")}
        cost={pendingValidation?.has_style_reference
          ? directionEstimate?.estimates_with_reference.faithful
          : directionEstimate?.estimates_without_reference.faithful}
        confirmLabel={t("TEST IN ACTION")}
        busy={generateValidation.isPending || !directionEstimate?.estimates_without_reference.faithful}
        onConfirm={() => {
          if (!pendingValidation) return;
          const suggestion = pendingValidation;
          generateValidation.mutate(
            { project: projectName, id: suggestion.id },
            {
              onSuccess: (data) => {
                setValidationJobs((current) => ({ ...current, [suggestion.id]: data.job.id }));
                setPendingValidation(null);
              },
              onError: (error) => {
                if (maybeShowInsufficientCredits(error, {
                  actionLabel: "Generate action audition",
                  onRetry: () => setPendingValidation(suggestion),
                })) return;
                setSampleError(error.message);
                setPendingValidation(null);
              },
            },
          );
        }}
        onClose={() => setPendingValidation(null)}
      />
    </RoomShell>
  );
}
