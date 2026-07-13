import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useGenerationJobs,
  useStyles,
  useSuggestStyles,
  useSuggestStylesEstimate,
  useGenerateStyleSamples,
  useSetActiveStyle,
  useImageGenerationMeta,
  useProjectConfig,
  useStoryBible,
  useProjectStatus,
  useLetteringStyle,
  useGenerateLetteringStyle,
  useSetLetteringStyle,
  useStyleSampleEstimate,
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
  actionsDisabled,
  queueState,
  fallbackPrompt,
  fallbackParameters,
  featured = false,
}: {
  suggestion: StyleSuggestion;
  projectName: string;
  isGenerating: boolean;
  actionsDisabled: boolean;
  queueState: "queued" | "running" | null;
  fallbackPrompt: string;
  fallbackParameters: Record<string, unknown>;
  featured?: boolean;
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
      { project: projectName, indices: [suggestion.index] },
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

  const showLoading = isGenerating || (!suggestion.has_sample && actionsDisabled);
  const isActive = suggestion.is_active;
  const canSelect = !isActive && !isGenerating && !actionsDisabled;

  // The card itself is the selection — no per-card select buttons.
  const handleCardClick = () => {
    if (!canSelect) return;
    setSelectionError(null);
    setActive.mutate(
      { project: projectName, index: suggestion.index },
      { onError: (error) => setSelectionError(error.message) },
    );
  };

  return (
    <>
      <EntityCard
        active={isActive}
        interactive={canSelect}
        onClick={canSelect ? handleCardClick : undefined}
        ariaLabel={canSelect ? `${t("SELECT")} ${suggestion.label}` : undefined}
        ariaPressed={isActive}
        className={`${featured ? "min-h-[420px] md:grid md:grid-cols-[minmax(260px,0.9fr)_minmax(0,1.1fr)]" : "min-h-[440px]"} ${isActive ? "!border-ink-black" : ""}`}
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
                title={t("Open image")}
                aria-label={`${t("Open image")} · ${suggestion.label}`}
                className="flex h-10 w-10 items-center justify-center border-[2px] border-bristol bg-ink-black text-bristol transition-colors hover:bg-hero-red"
              >
                <span className="font-meta text-[0.78rem]">⌕</span>
              </button>
            </div>
          </div>
        }
      >
        <div className={featured
          ? "font-display text-[2rem] font-black uppercase leading-[0.92] tracking-[-0.035em] text-ink-black"
          : "font-display text-[1.35rem] font-black leading-tight tracking-[-0.03em] text-ink-black"}
        >
          {suggestion.label}
        </div>
        <p className={`mt-3 flex-1 font-body text-[0.92rem] font-semibold leading-relaxed text-ink-muted ${featured ? "line-clamp-6" : "line-clamp-3"}`}>
          {suggestion.template}
        </p>
        <div className="mt-4 font-meta text-[0.58rem] font-bold tracking-[0.08em] text-ink-muted">
          {isActive ? `✓ ${t("YOUR STYLE")}` : t("CLICK TO SELECT")}
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
              disabled={actionsDisabled && !isGenerating}
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
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const projectName = id ?? "";
  const { data: stylesData, isLoading, refetch: refetchStyles } = useStyles(id);
  const { data: projectConfig } = useProjectConfig(id);
  const { data: lettering } = useLetteringStyle(id);
  const generateLettering = useGenerateLetteringStyle();
  const setLettering = useSetLetteringStyle();
  const { data: storyBible } = useStoryBible(id);
  const { data: status } = useProjectStatus(id);
  const suggestStyles = useSuggestStyles();
  const { data: generationJobs } = useGenerationJobs(
    id,
    Object.values(useStyleJobIds(projectName)),
  );
  const pendingSet = usePendingIndices(projectName);
  const styleJobStatuses = useStyleJobStatuses(projectName);
  const { updateJob, remove } = useStyleGenStore();
  const events = usePipelineStore((s) => s.events);
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);
  const [sampleError, setSampleError] = useState<string | null>(null);
  const [suggestionStatus, setSuggestionStatus] = useState<"idle" | "running" | "failed">("idle");
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const [showSuggestConfirm, setShowSuggestConfirm] = useState(false);

  const styleStage = status?.stages.style;
  const isStageGenerating = styleStage?.status === "running";
  const approveStage = useApproveStage();
  const { handleRun, isPending: isPipelineRunning } = useRunAction();
  const { data: castEstimate } = useStageEstimate(id, "cast");
  const styleSelected = !!status?.style_selected;

  const isSuggesting = suggestionStatus === "running";
  const styleActionsDisabled = isStageGenerating || isSuggesting || suggestStyles.isPending;
  const { data: suggestEstimate } = useSuggestStylesEstimate(id, !isSuggesting);

  useEffect(() => {
    if (!projectName || !generationJobs?.jobs.length) return;
    const timer = window.setTimeout(() => {
      for (const job of generationJobs.jobs) {
        const index = Number(job.payload.index);
        if (!Number.isFinite(index)) continue;
        if (job.status === "complete") {
          setSampleError(null);
          remove(projectName, [index]);
        } else if (job.status === "failed") {
          setSampleError(job.error ?? "Sample generation failed");
          remove(projectName, [index]);
        } else {
          updateJob(projectName, job);
        }
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs, projectName, updateJob, remove]);

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

  // The selected style is pinned to first position.
  const suggestions = [...(stylesData?.suggestions ?? [])].sort(
    (a, b) => Number(b.is_active) - Number(a.is_active),
  );

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

  function startSuggestions() {
    clearEvents();
    setSuggestionStatus("running");
    setSuggestionError(null);
    suggestStyles.mutate(
      { project: projectName },
      {
        onSuccess: () => connect(projectName),
        onError: (err) => {
          setSuggestionStatus("failed");
          setSuggestionError(err.message);
        },
      },
    );
  }

  const anyGenerating = pendingSet.size > 0;
  const runningStyleCount = Object.values(styleJobStatuses).filter((status) => status === "running").length;
  const queuedStyleCount = Object.values(styleJobStatuses).filter((status) => status === "queued").length;
  const effectiveSteps = projectConfig?.dev_mode
     ? Math.min(projectConfig?.image_steps ?? 0, projectConfig?.dev_image_steps ?? 0)
     : projectConfig?.image_steps;
  const selectedSuggestion = suggestions.find((suggestion) => suggestion.is_active);
  const candidateSuggestions = selectedSuggestion
    ? suggestions.filter((suggestion) => suggestion.index !== selectedSuggestion.index)
    : suggestions;

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker="LOOK"
        title="CHOOSE THE LOOK"
        lead="Choose one visual direction. Scenewright carries it through characters, places, and panels."
        actions={
          <div className="flex items-center gap-3">
            {anyGenerating && (
              <span className="font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/50">
                {runningStyleCount > 0 && `${runningStyleCount} RUNNING`}{runningStyleCount > 0 && queuedStyleCount > 0 && " / "}{queuedStyleCount > 0 && `${queuedStyleCount} QUEUED`}
              </span>
            )}
            {sampleError && (
              <span className="font-meta text-[0.48rem] tracking-[0.16em] text-hero-red">
                {sampleError}
              </span>
            )}
            <div className="flex flex-col items-end gap-1">
              <Button
                size="sm"
                variant="primary"
                onClick={() => setShowSuggestConfirm(true)}
                disabled={styleActionsDisabled}
              >
                {suggestStyles.isPending || isSuggesting
                  ? "SUGGESTING…"
                  : isStageGenerating
                    ? "GENERATING…"
                    : "SUGGEST MORE STYLES"}
              </Button>
              {suggestEstimate && suggestEstimate.estimate_credits > 0 && (
                <span className="font-meta text-[0.48rem] tracking-[0.14em] text-ink-black/45">
                  ~{suggestEstimate.estimate_credits.toLocaleString()} credits
                </span>
              )}
            </div>
          </div>
        }
      />

      {(isSuggesting || isStageGenerating || suggestionStatus === "failed") && (
        <div className={`mt-4 border-[2px] border-ink-black p-3 ${
          suggestionStatus === "failed" ? "bg-hero-red text-bristol" : "bg-narrator-gold text-ink-black"
        }`}>
          <div className="flex items-center gap-2">
            {(isSuggesting || isStageGenerating) && <span className="animate-press-blink h-2.5 w-2.5 bg-hero-red" />}
            <span className="font-meta text-[0.58rem] font-bold tracking-[0.1em]">
              {suggestionStatus === "failed"
                ? "STYLE SUGGESTION FAILED"
                : isStageGenerating
                  ? "GENERATING STYLE OPTIONS"
                  : "GENERATING ADDITIONAL STYLES"}
            </span>
          </div>
          <div className="mt-1 font-body text-[0.78rem] leading-relaxed">
            {suggestionStatus === "failed"
              ? suggestionError
              : "Asking the art director for visual directions and rendering one sample image per style. Samples appear as they complete."}
          </div>
        </div>
      )}

      {suggestions.length === 0 ? (
        <Surface padding="lg">
          <StateBlock
            minHeight="min-h-[22vh]"
            title={isStageGenerating ? "GENERATING STYLE OPTIONS" : "NO STYLE SUGGESTIONS YET"}
            description={
              isStageGenerating
                ? "Five style descriptions and sample images are on the way."
                : "Approve the extract stage to start generating style options."
            }
            icon="styles"
          />
        </Surface>
      ) : (
        <>
          {selectedSuggestion && (
            <section className="mt-6">
              <SectionHeader
                variant="underline"
                kicker="SELECTED DIRECTION"
                title="YOUR STORY'S LOOK"
                description="This proof is now the visual reference for every character, place, and panel."
              />
              <StyleCard
                key={selectedSuggestion.index}
                suggestion={selectedSuggestion}
                projectName={id}
                isGenerating={pendingSet.has(selectedSuggestion.index)}
                actionsDisabled={styleActionsDisabled}
                queueState={
                  pendingSet.has(selectedSuggestion.index)
                    ? styleJobStatuses[selectedSuggestion.index] ?? "queued"
                    : null
                }
                fallbackPrompt={buildFallbackStyleSamplePrompt(selectedSuggestion, storyBible)}
                fallbackParameters={{
                  width: projectConfig?.image_width,
                  height: projectConfig?.image_height,
                  steps: effectiveSteps,
                  guidance_scale: projectConfig?.flux_guidance_scale,
                  style_template: selectedSuggestion.template,
                }}
                featured
              />
            </section>
          )}

          {candidateSuggestions.length > 0 && (
            <section className="mt-10">
              <SectionHeader
                variant="underline"
                title={selectedSuggestion ? "OTHER DIRECTIONS" : "STYLE PROOFS"}
                description={selectedSuggestion
                  ? "Choose another proof at any time; nothing changes until you continue."
                  : "Each direction is previewed against your story, not a generic demo image."}
              />
              <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-5">
                {candidateSuggestions.map((s) => (
                  <StyleCard
                    key={s.index}
                    suggestion={s}
                    projectName={id}
                    isGenerating={pendingSet.has(s.index)}
                    actionsDisabled={styleActionsDisabled}
                    queueState={pendingSet.has(s.index) ? styleJobStatuses[s.index] ?? "queued" : null}
                    fallbackPrompt={buildFallbackStyleSamplePrompt(s, storyBible)}
                    fallbackParameters={{
                      width: projectConfig?.image_width,
                      height: projectConfig?.image_height,
                      steps: effectiveSteps,
                      guidance_scale: projectConfig?.flux_guidance_scale,
                      style_template: s.template,
                    }}
                  />
                ))}
              </div>
            </section>
          )}
          {suggestions.some((s) => s.has_sample) && (
            <p className="mt-4 font-meta text-[0.58rem] font-bold tracking-[0.08em] text-ink-muted">
              ✓ EVERY SAMPLE ABOVE WAS PREVIEWED ON YOUR STORY&apos;S OPENING SCENE
            </p>
          )}

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
        </>
      )}

      <ApprovalBar
        next={styleSelected
          ? "Scenewright casts your characters and places in this style"
          : "Pick a style — click the card that fits your story"}
        estimateCredits={styleSelected && styleNeedsApproval ? castEstimate?.estimate_credits : null}
        primaryLabel={styleNeedsApproval || !styleSelected ? "LOOKS RIGHT — CONTINUE →" : "GO TO CAST →"}
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
    </RoomShell>
  );
}
