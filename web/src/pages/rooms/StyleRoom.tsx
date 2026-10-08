import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useGenerationJobs,
  useStyles,
  useSuggestStyles,
  useCreateStyleDirection,
  useGenerateStyleSamples,
  useSuggestStylesEstimate,
  useStyleSampleEstimate,
  useGenerateStyleValidation,
  useProjectConfig,
  useStoryBible,
  useProjectStatus,
  useStyleDirectionEstimate,
  useGenerateProjectCover,
  useProjectCoverEstimate,
  useProjects,
} from "../../api/queries";
import { Check, ArrowDownRight, Columns2, X } from "lucide-react";
import { BookLetteringPanel } from "../../components/lettering/BookLetteringPanel";
import { StyleProofCard } from "../../components/style/StyleProofCard";
import { StyleGenerationProgress } from "../../components/style/StyleGenerationProgress";
import { ProofFlipViewer, ProofWall } from "../../components/style/ProofFlipViewer";
import { Button } from "../../components/ui/Button";
import { LazyImage } from "../../components/ui/LazyImage";
import { InspectButton } from "../../components/ui/InspectButton";
import { StateBlock } from "../../components/ui/StateBlock";
import { Surface } from "../../components/ui/Surface";
import { ApprovalBar, RoomHeader, ConfirmDrawer, RerunStageAction, RoomShell } from "../../components/composites";
import { useApproveStage, useStageEstimate } from "../../api/queries";
import { useRunAction } from "../../hooks/useRunAction";
import { useI18n } from "../../i18n";
import { StyleDirectionComposer, type StyleDirectionMode } from "../../components/style/StyleDirectionComposer";
import {
  useStyleGenStore,
  usePendingIndices,
  useStyleJobIds,
  useStyleJobStatuses,
} from "../../store/styleGen";
import { usePipelineStore } from "../../store/pipeline";
import { isAuthorDirection, styleName, type StyleSuggestion } from "../../api/styles";
import type { CostEstimate, StoryBible } from "../../types/api";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { seriesPath, splitProjectKey } from "../../api/projectScope";

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
    "No text. No speech balloons. No captions. Single illustration only."
  );
}

function multiplyEstimate(estimate: CostEstimate | undefined, count: number): CostEstimate | undefined {
  if (!estimate || count < 1) return undefined;
  return {
    ...estimate,
    estimate_credits: estimate.estimate_credits * count,
    reserved_credits: estimate.reserved_credits === null
      ? null
      : estimate.reserved_credits * count,
  };
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
  const { data: storyBible } = useStoryBible(id);
  const { data: status } = useProjectStatus(id);
  const suggestStyles = useSuggestStyles();
  const createStyleDirection = useCreateStyleDirection();
  const generateSamples = useGenerateStyleSamples();
  const generateValidation = useGenerateStyleValidation();
  const { data: generationJobs } = useGenerationJobs(
    id,
    [], true,
  );
  const [validationJobs, setValidationJobs] = useState<Record<string, string>>({});
  const { data: validationJobResults } = useGenerationJobs(id, Object.values(validationJobs));
  const trackedJobIds = useStyleJobIds(projectName);
  const pendingSet = usePendingIndices(projectName);
  const styleJobStatuses = useStyleJobStatuses(projectName);
  const { add, attachJobs, updateJob, remove } = useStyleGenStore();
  const events = usePipelineStore((s) => s.events);
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);
  const [letteringOpen, setLetteringOpen] = useState(false);
  const [sampleError, setSampleError] = useState<Error | string | null>(null);
  const [suggestionJobId, setSuggestionJobId] = useState<string | null>(null);
  const [suggestionStatus, setSuggestionStatus] = useState<"idle" | "running" | "failed">("idle");
  const [suggestionError, setSuggestionError] = useState<Error | string | null>(null);
  const [showSuggestConfirm, setShowSuggestConfirm] = useState(false);
  const [showDirectionComposer, setShowDirectionComposer] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparisonView, setComparisonView] = useState<"proof" | "action">("proof");
  const [proofFilter, setProofFilter] = useState<"all" | "yours" | "suggested">("all");
  const [proofView, setProofView] = useState<"grid" | "flip" | "wall">("grid");
  const [flipIndex, setFlipIndex] = useState(0);
  const [pendingCustomInput, setPendingCustomInput] = useState<{
    direction: string;
    image: File | null;
    mode: StyleDirectionMode;
  } | null>(null);
  const [pendingValidation, setPendingValidation] = useState<StyleSuggestion | null>(null);
  // Proofs awaiting confirmation to be queued again: outdated ones to refresh,
  // or missing ones (failed or never drawn) to retry.
  const [pendingProofs, setPendingProofs] = useState<{ kind: "refresh" | "retry"; suggestions: StyleSuggestion[] } | null>(null);

  const styleStage = status?.stages.style;
  const isStageGenerating = styleStage?.status === "running";
  const approveStage = useApproveStage();
  const { handleRun, isPending: isPipelineRunning } = useRunAction();
  const { data: castEstimate } = useStageEstimate(id, "cast");
  const styleSelected = !!status?.style_selected;
  const castStarted = status?.stages.cast?.status != null && status.stages.cast.status !== "pending";
  const castReady = ["complete", "awaiting_review"].includes(status?.stages.cast.status ?? "");
  const { data: projectSummaries } = useProjects();
  const projectSummary = projectSummaries?.find((project) => project.id === splitProjectKey(id ?? "").id);
  const coverJobActive = projectSummary?.cover_job?.status === "queued"
    || projectSummary?.cover_job?.status === "running";
  const needsCover = !!status && !status.has_cover && !projectSummary?.has_cover && !coverJobActive;
  const generateCover = useGenerateProjectCover();
  const { data: coverEstimate } = useProjectCoverEstimate(id, styleSelected && castReady && needsCover);

  const latestSuggestionJob = generationJobs?.jobs.filter((job) => job.kind === "style_suggest")
    .sort((a, b) => a.queued_at.localeCompare(b.queued_at)).at(-1);
  // A suggestion batch, or an author direction that also curates neighbors.
  const activeBatchJob = generationJobs?.jobs
    .filter((job) => (job.kind === "style_suggest" || (job.kind === "style_sample" && !!job.payload.with_neighbors))
      && (job.status === "queued" || job.status === "running"))
    .sort((a, b) => a.queued_at.localeCompare(b.queued_at)).at(-1);
  const isSuggesting = !!stylesData?.is_suggesting || latestSuggestionJob?.status === "running"
    || latestSuggestionJob?.status === "queued" || suggestionStatus === "running";
  // Review work queues behind active generation. Selection and stage restarts
  // still wait because they change the authority used by that generation.
  const proofsInFlight = !!stylesData?.is_generating;
  const batchInFlight = isStageGenerating || isSuggesting || suggestStyles.isPending;
  const directionActionsDisabled = letteringOpen || createStyleDirection.isPending;
  const proofQueueDisabled = directionActionsDisabled || generateSamples.isPending;
  const styleActionsDisabled = directionActionsDisabled || batchInFlight || proofsInFlight;
  const { data: suggestEstimate, error: suggestEstimateError, refetch: refetchSuggestEstimate } = useSuggestStylesEstimate(id, !isSuggesting);
  const { data: directionEstimate, error: directionEstimateError, refetch: refetchDirectionEstimate } = useStyleDirectionEstimate(id, !createStyleDirection.isPending);
  const { data: sampleEstimate } = useStyleSampleEstimate(id, !!pendingProofs);

  const estimateError = suggestEstimateError ?? directionEstimateError;
  const estimatesMissing = !suggestEstimate || !directionEstimate;
  const retryEstimates = () => {
    void refetchSuggestEstimate();
    void refetchDirectionEstimate();
  };

  const startSuggestions = useCallback((directionId?: string) => {
    clearEvents();
    setSuggestionStatus("running");
    setSuggestionError(null);
    setSampleError(null);
    suggestStyles.mutate(
      { project: projectName, directionId },
      {
        onSuccess: (data) => { setSuggestionJobId(data.job?.id ?? null); connect(projectName); },
        onError: (err) => {
          setSuggestionStatus("failed");
          setSuggestionError(err);
        },
      },
    );
  }, [clearEvents, connect, projectName, suggestStyles]);

  useEffect(() => {
    if (!projectName || !generationJobs?.jobs.length) return;
    const timer = window.setTimeout(() => {
      for (const job of generationJobs.jobs) {
        if (!Object.values(trackedJobIds).includes(job.id)) continue;
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
  }, [generationJobs, projectName, refetchStyles, remove, updateJob, trackedJobIds]);

  useEffect(() => {
    const trackedIds = new Set(Object.values(validationJobs));
    if (!trackedIds.size || !validationJobResults?.jobs.length) return;
    const terminalJobs = validationJobResults.jobs.filter(
      (job) => trackedIds.has(job.id) && job.kind === "style_validation"
        && (job.status === "complete" || job.status === "failed"),
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
  }, [refetchStyles, t, validationJobResults, validationJobs]);

  useEffect(() => {
    const job = generationJobs?.jobs.find((item) => item.id === suggestionJobId);
    if (!job || (job.status !== "complete" && job.status !== "failed")) return;
    const timer = window.setTimeout(() => {
      setSuggestionStatus(job.status === "complete" ? "idle" : "failed");
      setSuggestionError(job.status === "failed" ? job.user_message ?? job.error : null);
      refetchStyles();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs, suggestionJobId, refetchStyles]);

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
  const continueEstimateCredits = styleSelected
    && (castStarted || castEstimate != null)
    && (!castReady || !needsCover || coverEstimate != null)
    ? (castStarted ? 0 : castEstimate?.estimate_credits ?? 0)
      + (castReady && needsCover ? coverEstimate?.estimate_credits ?? 0 : 0)
    : null;

  function handleContinueToCast() {
    if (!id) return;
    const startCastIfNeeded = () => {
      // A new Cast run queues its cover on the server after references exist.
      if (castReady && needsCover) {
        generateCover.mutate(
          { project: id },
          {
            onError: (error) => {
              maybeShowInsufficientCredits(error, { actionLabel: t("Create project cover") });
            },
          },
        );
      }
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
          setSuggestionError(error);
        },
      },
    );
  }

  function toggleCompare(idToToggle: string) {
    setCompareIds((current) => {
      const available = current.filter((id) => suggestions.some((suggestion) => suggestion.id === id));
      if (available.includes(idToToggle)) return available.filter((id) => id !== idToToggle);
      if (available.length >= 3) return available;
      return [...available, idToToggle];
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
  const actionComparisonAvailable = comparedSuggestions.length >= 2
    && comparedSuggestions.every((style) => style.has_validation && style.validation_url);
  const comparingAction = comparisonView === "action" && actionComparisonAvailable;
  const activeSuggestion = suggestions.find((suggestion) => suggestion.is_active);
  const proofQueued = (suggestion: StyleSuggestion) => pendingSet.has(suggestion.index)
    || suggestion.generation_status === "queued" || suggestion.generation_status === "running";
  const staleSuggestions = suggestions.filter((suggestion) => suggestion.sample_stale && !proofQueued(suggestion));
  // Hidden proofs were set aside on purpose; retry them from their own card.
  const missingSuggestions = batchInFlight ? [] : suggestions.filter(
    (suggestion) => !suggestion.has_sample && !suggestion.hidden && !proofQueued(suggestion),
  );
  const pendingProofCount = pendingProofs?.suggestions.length ?? 0;
  const pendingProofEstimate = multiplyEstimate(sampleEstimate, pendingProofCount);
  const retryingProofs = pendingProofs?.kind === "retry";
  const proofName = (suggestion: StyleSuggestion) => isAuthorDirection(suggestion)
    ? `${t("Yours")} · ${styleName(suggestion)}`
    : styleName(suggestion);
  const comparedImages = comparedSuggestions.map((suggestion) => ({
    src: comparingAction
      ? suggestion.validation_url!
      : suggestion.sample_preview_url ?? `/api${seriesPath(id)}/files/samples/style_${suggestion.index}.png`,
    alt: proofName(suggestion),
  }));
  const shownSuggestions = suggestions.filter((suggestion) => !suggestion.hidden);
  const hiddenSuggestions = suggestions.filter((suggestion) => suggestion.hidden);
  const yoursCount = shownSuggestions.filter(isAuthorDirection).length;
  const suggestedCount = shownSuggestions.length - yoursCount;
  const effectiveFilter = yoursCount > 0 && suggestedCount > 0 ? proofFilter : "all";
  const filteredSuggestions = effectiveFilter === "yours"
    // Newest first: directions are appended, so a higher index is more recent.
    ? shownSuggestions.filter(isAuthorDirection).sort((a, b) => b.index - a.index)
    : effectiveFilter === "suggested"
      ? shownSuggestions.filter((suggestion) => !isAuthorDirection(suggestion))
      : shownSuggestions;
  const viewableSuggestions = filteredSuggestions.filter((suggestion) => suggestion.has_sample);
  const renderProofCard = (suggestion: StyleSuggestion) => (
    <StyleProofCard
      key={suggestion.id}
      suggestion={suggestion}
      projectName={id}
      isGenerating={proofQueued(suggestion)}
      generationDisabled={letteringOpen}
      retryDisabled={proofQueueDisabled}
      awaitingBatch={batchInFlight}
      selectionDisabled={letteringOpen}
      queueState={suggestion.generation_status === "queued" || suggestion.generation_status === "running" ? suggestion.generation_status : pendingSet.has(suggestion.index) ? styleJobStatuses[suggestion.index] ?? "queued" : null}
      fallbackPrompt={buildFallbackStyleSamplePrompt(suggestion, storyBible)}
      fallbackParameters={{
        width: projectConfig?.image_width,
        height: projectConfig?.image_height,
        steps: effectiveSteps,
        guidance_scale: projectConfig?.flux_guidance_scale,
        style_template: suggestion.template,
      }}
      isCompared={compareIds.includes(suggestion.id)}
      compareDisabled={comparedSuggestions.length >= 3 && !compareIds.includes(suggestion.id)}
      onToggleCompare={() => toggleCompare(suggestion.id)}
      validationBusy={suggestion.id in validationJobs}
      onValidate={() => setPendingValidation(suggestion)}
      onRefresh={() => setPendingProofs({ kind: "refresh", suggestions: [suggestion] })}
      onRetry={() => setPendingProofs({ kind: "retry", suggestions: [suggestion] })}
    />
  );

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker="LOOK"
        title="CHOOSE THE LOOK"
        lead="Choose one visual direction. Scenewright carries it through characters, places, and panels."
        actions={suggestions.length > 0 || batchInFlight ? (
          <div className="flex items-center gap-3">
            {anyGenerating && (
              <span role="status" aria-live="polite" className="font-meta text-[0.68rem] font-bold tracking-[0.08em] text-ink-black/65">
                {runningStyleCount > 0 && `${runningStyleCount} ${t("RUNNING")}`}{runningStyleCount > 0 && queuedStyleCount > 0 && " / "}{queuedStyleCount > 0 && `${queuedStyleCount} ${t("QUEUED")}`}
              </span>
            )}
            {sampleError && (
              <ErrorNotice error={sampleError} operation="generate" />
            )}
            <div className="flex flex-col items-end gap-1">
              <Button
                size="sm"
                variant="primary"
                onClick={() => setShowDirectionComposer((visible) => !visible)}
                disabled={letteringOpen}
              >
                {showDirectionComposer ? t("CLOSE ART DIRECTION") : t("ADD A DIRECTION")}
              </Button>
            </div>
          </div>
        ) : undefined}
      />

      {projectConfig?.lettering_mode === "integrated" && <p className="mt-5 text-sm leading-relaxed text-ink-muted">{t("Integrated lettering: these proofs draw text, balloons, and sound effects into the artwork, just like your pages. Text changes require an image correction.")}</p>}
      {projectConfig?.lettering_mode !== "integrated" && styleSelected && !letteringOpen && <div className="mt-5"><Button variant="outline" disabled={styleActionsDisabled} onClick={() => setLetteringOpen(true)}>{t("Edit book lettering")}</Button></div>}
      {letteringOpen && <div className="mt-5"><BookLetteringPanel project={projectName} disabled={isStageGenerating} onClose={() => setLetteringOpen(false)} /></div>}

      {suggestionStatus === "failed" ? (
        <ErrorNotice error={suggestionError} operation="generate" />
      ) : (isSuggesting || isStageGenerating) && (
        <StyleGenerationProgress
          job={activeBatchJob}
          // Existing proofs belong to earlier batches, not this new suggestion run.
          fallbackPhase={isStageGenerating && suggestions.length > 0 ? "proofs" : "directions"}
          title={isStageGenerating ? t("GENERATING STYLE OPTIONS") : t("GENERATING ADDITIONAL STYLES")}
        />
      )}

      {missingSuggestions.length > 0 && (
        <div role="status" className="mt-6 flex flex-wrap items-center justify-between gap-4 border-[2px] border-hero-red/35 bg-hero-red/10 p-4">
          <div>
            <div className="font-meta text-[0.68rem] font-bold tracking-[0.1em] text-hero-red">
              {missingSuggestions.length === 1 ? t("ONE PROOF DIDN'T FINISH") : `${missingSuggestions.length} ${t("PROOFS DIDN'T FINISH")}`}
            </div>
            <p className="mt-1 max-w-3xl text-[0.84rem] leading-6 text-ink-black/72">
              {t("Queue them all at once. Finished proofs stay as they are, and each new one appears as soon as it's ready.")}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={proofQueueDisabled}
            onClick={() => setPendingProofs({ kind: "retry", suggestions: missingSuggestions })}
          >
            {missingSuggestions.length === 1 ? t("TRY SAMPLE AGAIN") : `${t("RETRY ALL")} (${missingSuggestions.length})`}
          </Button>
        </div>
      )}

      {staleSuggestions.length > 0 && (
        <Surface border="soft" shadow="none" padding="md" className="mt-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="font-meta text-[0.68rem] font-bold tracking-[0.1em] text-ink-black">
                {t("REFRESH AVAILABLE")}
              </div>
              <p className="mt-1 max-w-3xl text-[0.84rem] leading-6 text-ink-black/72">
                {t("Some proofs were generated with earlier rendering rules. They remain visible and usable until you choose to refresh them.")}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={proofQueueDisabled}
              onClick={() => setPendingProofs({ kind: "refresh", suggestions: staleSuggestions })}
            >
              {t("REFRESH ALL")} ({staleSuggestions.length})
            </Button>
          </div>
        </Surface>
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
            busy={directionActionsDisabled || (estimatesMissing && !estimateError)}
            automaticDisabled={batchInFlight || proofsInFlight}
            disabled={estimatesMissing || !!estimateError}
            onRetry={estimateError ? retryEstimates : undefined}
            error={suggestionError ?? estimateError}
            onAutomatic={() => setShowSuggestConfirm(true)}
            onCustom={setPendingCustomInput}
          />
        </div>
      ) : suggestions.length === 0 ? null : (
        <>
          <section className="grid gap-6 bg-ink-black p-6 text-pulp-paper shadow-paper md:grid-cols-[minmax(0,1fr)_minmax(0,0.55fr)] md:p-8">
            <div>
              <h2 className="font-display text-3xl font-black uppercase leading-tight tracking-[-0.03em] md:text-4xl">{t("STYLE PROOFS")}</h2>
              <p className="mt-3 font-body text-sm leading-7 text-pulp-paper/85">{t("One story, different visual directions. Explore the artwork, compare your favorites, then choose the look your comic will carry.")}</p>
              {storyBible?.title && <p className="mt-4 font-meta text-xs text-narrator-gold">{storyBible.title}</p>}
            </div>
            <div className="flex flex-col justify-center bg-pulp-paper/10 p-5">
              <div className="flex items-center gap-2 font-meta text-xs font-bold text-narrator-gold">{activeSuggestion && <Check size={16} aria-hidden="true" />}{t(activeSuggestion ? "YOUR STYLE" : "YOUR CHOICE")}</div>
              <p className="mt-3 break-words font-display text-xl font-bold leading-tight">{activeSuggestion ? proofName(activeSuggestion) : t("Which world feels like your story?")}</p>
              <p className="mt-2 font-body text-xs leading-6 text-pulp-paper/85">{t(activeSuggestion ? "Selected for your comic. You can still explore the other proofs." : "Use Select this style beneath your favorite proof.")}</p>
            </div>
          </section>
          {showDirectionComposer && (
            <div className="mt-6">
              <StyleDirectionComposer
                automaticCost={suggestEstimate?.estimate_credits}
                customSingleCost={directionEstimate?.estimates.faithful.estimate_credits}
                customNeighborsCost={directionEstimate?.estimates.faithful_with_neighbors.estimate_credits}
                customSingleReferenceCost={directionEstimate?.estimates_with_reference.faithful.estimate_credits}
                customNeighborsReferenceCost={directionEstimate?.estimates_with_reference.faithful_with_neighbors.estimate_credits}
                imageReferenceSupported={directionEstimate?.image_reference_supported}
                busy={directionActionsDisabled || (estimatesMissing && !estimateError)}
                automaticDisabled={batchInFlight || proofsInFlight}
                disabled={estimatesMissing || !!estimateError}
                onRetry={estimateError ? retryEstimates : undefined}
                error={suggestionError ?? estimateError}
                onAutomatic={() => setShowSuggestConfirm(true)}
                onCustom={setPendingCustomInput}
              />
            </div>
          )}

          {comparedSuggestions.length >= 2 && (
            <section id="style-comparison" tabIndex={-1} aria-label={t("COMPARE PROOFS")} className="scroll-mt-6 bg-ink-black p-4 text-bristol md:p-6">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <h2 className="font-display text-2xl font-black text-narrator-gold">{t("COMPARE PROOFS")}</h2>
                  <p className="mt-1 text-sm leading-6 text-bristol/80">{t("Equal-size proofs make palette, finish, and story fit easier to judge.")}</p>
                </div>
                <Button variant="onInk" size="xs" onClick={() => setCompareIds([])}>{t("CLEAR")}</Button>
              </div>
              <div role="group" aria-label={t("Comparison images")} className="mt-4 flex flex-wrap gap-3">
                <Button variant={!comparingAction ? "secondary" : "outline"} size="sm" aria-pressed={!comparingAction} onClick={() => setComparisonView("proof")}>{t("STORY PROOFS")}</Button>
                <Button variant={comparingAction ? "secondary" : "outline"} size="sm" aria-pressed={comparingAction} disabled={!actionComparisonAvailable} onClick={() => setComparisonView("action")}>{t("ACTION AUDITIONS")}</Button>
              </div>
              {!actionComparisonAvailable && <p className="mt-2 text-sm text-bristol/80">{t("Action comparison becomes available when each compared direction has a completed action audition.")}</p>}
              <div className={`mt-4 grid gap-4 md:grid-cols-2 ${comparedSuggestions.length === 3 ? "xl:grid-cols-3" : ""}`}>
                {comparedSuggestions.map((suggestion, position) => (
                  <div key={suggestion.id} className="bg-bristol p-3 text-ink-black">
                    <div className="relative">
                      <LazyImage
                        src={comparedImages[position].src}
                        alt={proofName(suggestion)}
                        width={320}
                        height={400}
                        aspect="4 / 5"
                        className="object-contain object-center"
                      />
                      <InspectButton images={comparedImages} index={position} />
                    </div>
                    <div className="mt-3 font-display text-[1.1rem] font-black uppercase tracking-[-0.025em]">{proofName(suggestion)}</div>
                    <dl className="mt-3 space-y-3 text-sm leading-6">
                      <div><dt className="font-bold">{t("Palette")}</dt><dd>{suggestion.palette}</dd></div>
                      <div><dt className="font-bold">{t("Line and finish")}</dt><dd>{suggestion.line_rendering}</dd></div>
                      <div><dt className="font-bold">{t("Story fit")}</dt><dd>{suggestion.story_fit}</dd></div>
                    </dl>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section aria-label={t("STYLE PROOFS")} className="@container/style-proofs">
            <div className="mb-6 flex flex-wrap items-center justify-between gap-4 bg-surface-container p-4">
              <div className="min-w-0">
                <p className="flex items-center gap-2 font-meta text-xs font-bold"><Columns2 size={17} aria-hidden="true" />{t("Compare your favorites")}</p>
                <p role="status" className="mt-2 font-body text-xs leading-6 text-ink-muted">{t(comparedSuggestions.length === 0 ? "Choose up to three proofs to see them side by side." : comparedSuggestions.length === 1 ? "One proof added. Choose another to start comparing." : comparedSuggestions.length === 3 ? "Three proofs added. Remove one to compare another." : "Two proofs ready to compare. You can add one more.")}</p>
              </div>
              {comparedSuggestions.length >= 2 && <a href="#style-comparison" className="inline-flex min-h-11 items-center gap-2 font-meta text-xs font-bold text-hero-red underline underline-offset-4">{t("View comparison")}<ArrowDownRight size={17} aria-hidden="true" /></a>}
              {comparedSuggestions.length > 0 && <div className="flex w-full flex-wrap gap-2">
                {comparedSuggestions.map((suggestion) => <Button key={suggestion.id} variant="outline" size="xs" onClick={() => toggleCompare(suggestion.id)} aria-label={`${t("Remove from comparison")} · ${proofName(suggestion)}`}><span className="text-left">{proofName(suggestion)}</span><X size={14} className="shrink-0" aria-hidden="true" /></Button>)}
              </div>}
            </div>
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            {yoursCount > 0 && suggestedCount > 0 ? (
              <div role="group" aria-label={t("Filter proofs")} className="flex flex-wrap gap-2">
                {([
                  ["all", t("All"), shownSuggestions.length],
                  ["yours", t("Yours"), yoursCount],
                  ["suggested", t("Suggested"), suggestedCount],
                ] as const).map(([value, label, count]) => (
                  <Button
                    key={value}
                    size="xs"
                    variant={effectiveFilter === value ? "secondary" : "outline"}
                    aria-pressed={effectiveFilter === value}
                    onClick={() => setProofFilter(value)}
                  >
                    {label} · {count}
                  </Button>
                ))}
              </div>
            ) : <span />}
              {viewableSuggestions.length > 1 && (
                <div role="group" aria-label={t("Proof view")} className="flex gap-2">
                  {([["grid", t("Grid")], ["flip", t("Flip")], ["wall", t("Wall")]] as const).map(([value, label]) => (
                    <Button key={value} size="xs" variant={proofView === value ? "secondary" : "outline"} aria-pressed={proofView === value} onClick={() => setProofView(value)}>
                      {label}
                    </Button>
                  ))}
                </div>
              )}
            </div>
            {proofView === "flip" && viewableSuggestions.length > 1 ? (
              <ProofFlipViewer
                projectName={id}
                suggestions={viewableSuggestions}
                index={flipIndex}
                onIndexChange={setFlipIndex}
                selectionDisabled={letteringOpen}
              />
            ) : proofView === "wall" && viewableSuggestions.length > 1 ? (
              <ProofWall
                projectName={id}
                suggestions={viewableSuggestions}
                onOpen={(index) => { setFlipIndex(index); setProofView("flip"); }}
              />
            ) : (
              // Fit 280px cards plus 24px gaps, with at most three columns.
              <div data-testid="style-proof-grid" className="grid grid-cols-1 gap-x-6 @min-[584px]/style-proofs:grid-cols-2 @min-[888px]/style-proofs:grid-cols-3">
                {filteredSuggestions.map(renderProofCard)}
              </div>
            )}
            {hiddenSuggestions.length > 0 && (
              <details className="mt-8 bg-surface-container px-4">
                <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold text-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
                  {t("Hidden")} ({hiddenSuggestions.length})
                </summary>
                <div data-testid="style-proof-hidden-grid" className="grid grid-cols-1 gap-x-6 pb-4 md:grid-cols-2 lg:grid-cols-3">
                  {hiddenSuggestions.map(renderProofCard)}
                </div>
              </details>
            )}
          </section>

          {suggestions.length > 0 && suggestions.every((suggestion) => suggestion.has_sample) && (
            <p className="mt-4 font-meta text-[0.68rem] font-bold tracking-[0.08em] text-ink-black/60">
              {t("EVERY COMPLETED PROOF USES THE SAME STORY-SPECIFIC AUDITION")}
            </p>
          )}

        </>
      )}

      {!isPipelineRunning && !isStageGenerating && !isSuggesting && <ApprovalBar
        next={styleSelected
          ? needsCover
            ? t("Scenewright casts your characters and places, and draws your project cover")
            : t("Scenewright casts your characters and places in this style")
          : t("Pick your favorite proof with Select this style")}
        estimateCredits={continueEstimateCredits}
        primaryLabel={styleNeedsApproval || !styleSelected ? t("LOOKS RIGHT — CONTINUE →") : t("GO TO CAST →")}
        onPrimary={handleContinueToCast}
        primaryDisabled={
          !styleSelected
          || letteringOpen
          || approveStage.isPending
          || isPipelineRunning
          || isStageGenerating
          || isSuggesting
          || (!castStarted && castEstimate == null)
          || (castReady && needsCover && coverEstimate == null)
        }
        busy={approveStage.isPending}
        secondary={suggestions.length > 0 && (styleStage?.status === "complete" || styleStage?.status === "awaiting_review") ? (
          <RerunStageAction
            project={id}
            stage="style"
            label="styles"
            disabled={letteringOpen || isPipelineRunning || isStageGenerating || isSuggesting}
          />
        ) : undefined}
      />}

      <ConfirmDrawer
        open={!!pendingProofs}
        title={retryingProofs
          ? pendingProofCount > 1 ? t("Retry the missing proofs?") : t("Retry this proof?")
          : pendingProofCount > 1 ? t("Refresh outdated proofs?") : t("Refresh this proof?")}
        body={retryingProofs
          ? t("Queues a new proof for each direction that didn't finish. Proofs already drawing keep going.")
          : t("Regenerates the selected proof using the current rendering rules. The existing image remains available unless generation succeeds.")}
        cost={pendingProofEstimate}
        confirmLabel={retryingProofs
          ? pendingProofCount > 1 ? `${t("RETRY ALL")} (${pendingProofCount})` : t("TRY SAMPLE AGAIN")
          : pendingProofCount > 1 ? t("REFRESH ALL") : t("REFRESH PROOF")}
        busy={generateSamples.isPending || !pendingProofEstimate}
        onConfirm={() => {
          if (!pendingProofs) return;
          const pending = pendingProofs;
          generateSamples.mutate(
            { project: projectName, ids: pending.suggestions.map((suggestion) => suggestion.id) },
            {
              onSuccess: (data) => {
                if (pending.kind === "retry") setSampleError(null);
                add(projectName, data.indices);
                attachJobs(projectName, data.jobs);
                setPendingProofs(null);
              },
              onError: (error) => {
                if (maybeShowInsufficientCredits(error, {
                  actionLabel: pending.kind === "retry" ? "Retry style proofs" : "Refresh style proof",
                  onRetry: () => setPendingProofs(pending),
                })) return;
                setSampleError(error);
                setPendingProofs(null);
              },
            },
          );
        }}
        onClose={() => setPendingProofs(null)}
      />
      <ConfirmDrawer
        open={showSuggestConfirm}
        title="Suggest more styles?"
        body="Generates six additional style descriptions and sample images. Credits are reserved now and settled to actual usage."
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
        title={pendingCustomInput?.mode === "neighbors" ? t("Create six directed proofs?") : t("Create this proof?")}
        body={pendingCustomInput?.mode === "neighbors"
          ? t("Creates one faithful proof and five deliberately varied neighbors around your direction.")
          : t("Creates one story-specific proof from your text, visual reference, or both.")}
        cost={pendingCustomInput?.mode === "neighbors"
          ? pendingCustomInput.image && directionEstimate?.image_reference_supported
            ? directionEstimate.estimates_with_reference.faithful_with_neighbors
            : directionEstimate?.estimates_without_reference.faithful_with_neighbors
          : pendingCustomInput?.image && directionEstimate?.image_reference_supported
            ? directionEstimate.estimates_with_reference.faithful
            : directionEstimate?.estimates_without_reference.faithful}
        confirmLabel={pendingCustomInput?.mode === "neighbors" ? t("CREATE SIX DIRECTIONS") : t("CREATE MY PROOF")}
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
                setSampleError(error);
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
import { ErrorNotice } from "../../components/composites/ErrorNotice";
