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
} from "../../api/queries";
import { Button } from "../../components/ui/Button";
import { GenerationDetailsModal } from "../../components/ui/GenerationDetailsModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StateBlock } from "../../components/ui/StateBlock";
import { Surface } from "../../components/ui/Surface";
import { ApprovalBar, EntityCard, RoomHeader, ConfirmDrawer, RoomShell } from "../../components/composites";
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
}: {
  suggestion: StyleSuggestion;
  projectName: string;
  isGenerating: boolean;
  actionsDisabled: boolean;
  queueState: "queued" | "running" | null;
  fallbackPrompt: string;
  fallbackParameters: Record<string, unknown>;
}) {
  const { t } = useI18n();
  const sampleUrl = `/api/projects/${encodeURIComponent(projectName)}/files/samples/style_${suggestion.index}.png`;
  const [imgFailed, setImgFailed] = useState(!suggestion.has_sample);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const wasGenerating = useRef(isGenerating);
  const generateSamples = useGenerateStyleSamples();
  const setActive = useSetActiveStyle();
  const { add, attachJobs, remove } = useStyleGenStore();
  const { data: meta } = useImageGenerationMeta(
    projectName,
    `samples/style_${suggestion.index}.png`,
    isDetailsOpen,
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

  const handleGenerate = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (imgFailed) setImgFailed(true);
    add(projectName, [suggestion.index]);
    generateSamples.mutate(
      { project: projectName, indices: [suggestion.index] },
      {
        onSuccess: (data) => attachJobs(projectName, data.jobs),
        onError: () => remove(projectName, [suggestion.index]),
      },
    );
  };

  const showLoading = isGenerating || (!suggestion.has_sample && actionsDisabled);
  const isActive = suggestion.is_active;
  const canSelect = !isActive && !isGenerating && !actionsDisabled;

  // The card itself is the selection — no per-card select buttons.
  const handleCardClick = () => {
    if (canSelect) setActive.mutate({ project: projectName, index: suggestion.index });
  };

  return (
    <>
      <EntityCard
        active={isActive}
        interactive={canSelect}
        onClick={handleCardClick}
        className={`min-h-[460px] ${isActive ? "!border-hero-red shadow-[4px_4px_0_0_var(--color-hero-red)]" : ""}`}
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
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">
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
              <div className="absolute left-0 top-0 bg-hero-red px-3 py-1.5 font-meta text-[0.56rem] tracking-[0.18em] text-bristol">
                ✓ {t("YOUR STYLE")}
              </div>
            )}

            <div className="absolute right-3 top-3 flex gap-1.5">
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setIsDetailsOpen(true); }}
                title="View sample details"
                className="flex h-9 w-9 items-center justify-center bg-ink-black/55 text-bristol transition-colors hover:bg-ink-black"
              >
                <span className="font-meta text-[0.78rem]">⌕</span>
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); handleGenerate(e); }}
                disabled={isGenerating || actionsDisabled}
                title={suggestion.has_sample ? "Regenerate sample" : "Generate sample"}
                className="flex h-9 w-9 items-center justify-center bg-ink-black/55 text-bristol transition-colors hover:bg-ink-black disabled:opacity-40"
              >
                <span className="font-meta text-[0.78rem]">↺</span>
              </button>
            </div>
          </div>
        }
      >
        <div className="font-display text-[1.35rem] font-bold leading-tight tracking-[-0.04em] text-ink-black">
          {suggestion.label}
        </div>
        <p className="mt-2 flex-1 font-body text-[0.92rem] font-semibold leading-relaxed text-ink-black/68 line-clamp-2">
          {suggestion.template}
        </p>
        <div className="mt-3 font-meta text-[0.52rem] tracking-[0.14em] text-ink-black/35">
          {isActive ? `✓ ${t("YOUR STYLE")}` : t("CLICK TO SELECT")}
        </div>
      </EntityCard>
      <GenerationDetailsModal
        isOpen={isDetailsOpen}
        onClose={() => setIsDetailsOpen(false)}
        title={suggestion.label}
        imageUrl={`${sampleUrl}?t=${timestamp}`}
        prompt={meta?.prompt ?? fallbackPrompt}
        parameters={meta?.parameters ?? fallbackParameters}
        isFallback={!meta}
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
    return <RoomShell isLoading loadingText="MIXING PALETTES…" />;
  }

  if (!id) {
    return (
      <RoomShell
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
    if (styleNeedsApproval && styleSelected) {
      approveStage.mutate(
        { project: id, stage: "style" },
        {
          onSuccess: () => {
            if (!castStarted) handleRun(id, "cast", { actionLabel: "Cast characters & places" });
            navigate(`/project/${id}/cast`);
          },
        },
      );
    } else {
      navigate(`/project/${id}/cast`);
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

  return (
    <RoomShell>
      <RoomHeader
        kicker="STYLES"
        title="LOOK & STYLE"
        lead="Choose the visual style that defines your comic. Generate samples to compare, then select one to lock it in."
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
            {(isSuggesting || isStageGenerating) && <span className="h-2.5 w-2.5 animate-pulse bg-hero-red" />}
            <span className="font-meta text-[0.48rem] tracking-[0.16em]">
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
          <section className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {suggestions.map((s) => (
              <StyleCard
                key={s.index}
                suggestion={s}
                projectName={id}
                isGenerating={pendingSet.has(s.index)}
                actionsDisabled={styleActionsDisabled}
                queueState={
                  pendingSet.has(s.index)
                    ? styleJobStatuses[s.index] ?? "queued"
                    : null
                }
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
          </section>
          {suggestions.some((s) => s.has_sample) && (
            <p className="mt-4 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/45">
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
          ? "PULP casts your characters and places in this style"
          : "Pick a style — click the card that fits your story"}
        estimateCredits={styleSelected && styleNeedsApproval ? castEstimate?.estimate_credits : null}
        primaryLabel={styleNeedsApproval || !styleSelected ? "LOOKS RIGHT — CONTINUE →" : "GO TO CAST →"}
        onPrimary={handleContinueToCast}
        primaryDisabled={!styleSelected || approveStage.isPending || isPipelineRunning || isStageGenerating || isSuggesting}
        busy={approveStage.isPending}
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
