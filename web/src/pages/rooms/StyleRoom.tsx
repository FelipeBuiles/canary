import { isInsufficientCreditsError } from "../../api/client";
import { useGenerationTracking } from "../../hooks/useGenerationTracking";
import { isGenerationActive } from "../../lib/generationTracking";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
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
import { ArrowDownRight, Columns2, X } from "lucide-react";
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
import { cn } from "../../lib/cn";
import { StyleDirectionComposer, type StyleDirectionMode } from "../../components/style/StyleDirectionComposer";
import { usePipelineStore } from "../../store/pipeline";
import { isAuthorDirection, styleName, type StyleSuggestion } from "../../api/styles";
import type { CostEstimate, StoryBible } from "../../types/api";
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

const SEGMENT = "flex h-8 items-center gap-1.5 px-3 font-meta text-[0.8125rem] font-medium transition-colors [&+&]:shadow-[inset_1px_0_0_rgb(27_28_21/0.12)]";
const SEGMENT_ON = "bg-ink-black text-pulp-paper";
const SEGMENT_OFF = "text-ink-muted hover:bg-sidebar-tint hover:text-ink-black";

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
  const tracking = useGenerationTracking(id);
  const { data: generationJobs } = tracking;
  const proofJobs = (stylesData?.suggestions ?? []).map(suggestion => tracking.status({ kind: "style_sample", identity: "index", value: suggestion.index }));
  const validationJobs = Object.fromEntries((stylesData?.suggestions ?? []).map(suggestion => [suggestion.id,
    tracking.status({ kind: "style_validation", identity: "id", value: suggestion.id }),
  ]));
  const pendingSet = new Set(proofJobs.filter(isGenerationActive).map(job => Number(job!.payload.index)));
  const styleJobStatuses = Object.fromEntries(proofJobs.filter(isGenerationActive).map(job => [Number(job!.payload.index), job!.status]));
  const events = usePipelineStore((s) => s.events);
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);
  const [letteringOpen, setLetteringOpen] = useState(false);
  const [sampleError, setSampleError] = useState<Error | string | null>(null);
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

  const latestSuggestionJob = tracking.status({ kind: "style_suggest" });
  // A suggestion batch, or an author direction that also curates neighbors.
  const activeBatchJob = generationJobs?.jobs
    .filter((job) => (job.kind === "style_suggest" || (job.kind === "style_sample" && !!job.payload.with_neighbors))
      && (isGenerationActive(job)))
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

  function startSuggestions(directionId?: string) {
    clearEvents();
    setSuggestionStatus("running");
    setSuggestionError(null);
    setSampleError(null);
    void tracking.start({ kind: "style_suggest" }, () => suggestStyles.mutateAsync({ project: projectName, directionId }), {
      actionLabel: t("CREATE SIX DIRECTIONS"),
    }).then(() => { setSuggestionStatus("idle"); connect(projectName); }).catch((error: Error) => {
      setSuggestionStatus("failed");
      setSuggestionError(error);
    });
  }

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
        void tracking.start({ kind: "project_cover" }, () => generateCover.mutateAsync({ project: id }), {
          actionLabel: t("Create project cover"),
        }).catch(() => {});
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
    void tracking.start({ kind: "style_sample" }, () => createStyleDirection.mutateAsync({
      project: projectName, direction: input.direction, image: input.image, withNeighbors: input.mode === "neighbors",
    }), { actionLabel: t("ADD A DIRECTION") }).then(data => {
      if (data.direction.has_image && !data.direction.image_supported) {
        setSampleError(t("The uploaded image was saved, but this image model used your text description for the proof."));
      }
      setShowDirectionComposer(false);
    }).catch((error: Error) => {
      setSuggestionStatus("failed");
      setSuggestionError(error);
    });
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
      queueState={suggestion.generation_status === "queued" || suggestion.generation_status === "running" ? suggestion.generation_status : pendingSet.has(suggestion.index) ? styleJobStatuses[suggestion.index] as "queued" | "running" : null}
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
      validationBusy={isGenerationActive(validationJobs[suggestion.id])}
      onValidate={() => setPendingValidation(suggestion)}
      onRefresh={() => setPendingProofs({ kind: "refresh", suggestions: [suggestion] })}
      onRetry={() => setPendingProofs({ kind: "retry", suggestions: [suggestion] })}
    />
  );

  return (
    <RoomShell project={id}>
      <RoomHeader
        title={t("Look")}
        lead={[
          suggestions.length > 0 ? t("{count, plural, one {# proof} other {# proofs}}", { count: suggestions.length }) : undefined,
          activeSuggestion ? proofName(activeSuggestion) : undefined,
          projectConfig?.lettering_mode === "integrated" ? t("Integrated lettering") : undefined,
        ].filter(Boolean).join(" · ")}
        actions={suggestions.length > 0 || batchInFlight ? (
          <div className="flex items-center gap-3">
            {anyGenerating && (
              <span role="status" aria-live="polite" className="font-meta text-xs text-ink-soft">
                {runningStyleCount > 0 && `${runningStyleCount} ${t("RUNNING")}`}{runningStyleCount > 0 && queuedStyleCount > 0 && " / "}{queuedStyleCount > 0 && `${queuedStyleCount} ${t("QUEUED")}`}
              </span>
            )}
            {(sampleError || [...proofJobs, ...Object.values(validationJobs)].find(job => job?.status === "failed")?.error) && (
              <ErrorNotice error={sampleError ?? [...proofJobs, ...Object.values(validationJobs)].find(job => job?.status === "failed")?.error} operation="generate" />
            )}
            <div className="flex flex-col items-end gap-1">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowDirectionComposer((visible) => !visible)}
                disabled={letteringOpen}
              >
                {showDirectionComposer ? t("CLOSE ART DIRECTION") : t("ADD A DIRECTION")}
              </Button>
            </div>
          </div>
        ) : undefined}
      />

      {projectConfig?.lettering_mode === "integrated" && !styleSelected && <p className="text-xs leading-5 text-ink-soft">{t("Integrated lettering: these proofs draw text, balloons, and sound effects into the artwork, just like your pages. Text changes require an image correction.")}</p>}
      {projectConfig?.lettering_mode !== "integrated" && styleSelected && !letteringOpen && <div><Button variant="outline" size="sm" disabled={styleActionsDisabled} onClick={() => setLetteringOpen(true)}>{t("Edit book lettering")}</Button></div>}
      {letteringOpen && <div><BookLetteringPanel project={projectName} disabled={isStageGenerating} onClose={() => setLetteringOpen(false)} /></div>}

      {suggestionStatus === "failed" || latestSuggestionJob?.status === "failed" ? (
        <ErrorNotice error={suggestionError ?? latestSuggestionJob?.user_message ?? latestSuggestionJob?.error} operation="generate" />
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
          {showDirectionComposer && (
            <div>
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
            <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
            {yoursCount > 0 && suggestedCount > 0 && (
              <div role="group" aria-label={t("Filter proofs")} className="inline-flex border border-ink-black/55 bg-bristol">
                {([
                  ["all", t("All"), shownSuggestions.length],
                  ["yours", t("Yours"), yoursCount],
                  ["suggested", t("Suggested"), suggestedCount],
                ] as const).map(([value, label, count]) => (
                  <button key={value} type="button" aria-pressed={effectiveFilter === value} onClick={() => setProofFilter(value)}
                    className={cn(SEGMENT, effectiveFilter === value ? SEGMENT_ON : SEGMENT_OFF)}>
                    {label} <span className="tabular-nums opacity-70">{count}</span>
                  </button>
                ))}
              </div>
            )}
              {viewableSuggestions.length > 1 && (
                <div role="group" aria-label={t("Proof view")} className="ml-auto inline-flex border border-ink-black/55 bg-bristol">
                  {([["grid", t("Grid")], ["flip", t("Flip")], ["wall", t("Wall")]] as const).map(([value, label]) => (
                    <button key={value} type="button" aria-pressed={proofView === value} onClick={() => setProofView(value)}
                      className={cn(SEGMENT, proofView === value ? SEGMENT_ON : SEGMENT_OFF)}>
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {comparedSuggestions.length > 0 && (
              // The compare tray exists only while something is in it.
              <div className="mb-5 flex flex-wrap items-center gap-2 border border-ink-black/12 bg-bristol px-3 py-2">
                <Columns2 size={15} aria-hidden="true" className="text-ink-soft" />
                <p role="status" className="font-meta text-xs text-ink-muted">{t(comparedSuggestions.length === 1 ? "One proof added. Choose another to start comparing." : comparedSuggestions.length === 3 ? "Three proofs added. Remove one to compare another." : "Two proofs ready to compare. You can add one more.")}</p>
                {comparedSuggestions.map((suggestion) => <Button key={suggestion.id} variant="outline" size="xs" onClick={() => toggleCompare(suggestion.id)} aria-label={`${t("Remove from comparison")} · ${proofName(suggestion)}`}><span className="text-left">{proofName(suggestion)}</span><X size={13} className="shrink-0" aria-hidden="true" /></Button>)}
                {comparedSuggestions.length >= 2 && <a href="#style-comparison" className="ml-auto inline-flex min-h-8 items-center gap-1.5 font-meta text-xs font-semibold text-ink-black underline decoration-ink-black/30 underline-offset-4 hover:text-hero-red">{t("View comparison")}<ArrowDownRight size={15} aria-hidden="true" /></a>}
              </div>
            )}
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
              <div data-testid="style-proof-grid" className="grid grid-cols-1 gap-x-5 @min-[584px]/style-proofs:grid-cols-2 @min-[888px]/style-proofs:grid-cols-3">
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
          void tracking.start({ kind: "style_sample" }, () => generateSamples.mutateAsync({
            project: projectName, ids: pending.suggestions.map(suggestion => suggestion.id),
          }), {
            actionLabel: pending.kind === "retry" ? "Retry style proofs" : "Refresh style proof",
            onRetry: () => setPendingProofs(pending),
          }).then(() => {
            if (pending.kind === "retry") setSampleError(null);
            setPendingProofs(null);
          }).catch((error: Error) => {
            if (isInsufficientCreditsError(error)) return;
            setSampleError(error);
            setPendingProofs(null);
          });
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
          void tracking.start({ kind: "style_validation", identity: "id", value: suggestion.id },
            () => generateValidation.mutateAsync({ project: projectName, id: suggestion.id }), {
              actionLabel: "Generate action audition",
              onRetry: () => setPendingValidation(suggestion),
            }).then(() => setPendingValidation(null)).catch((error: Error) => {
              if (isInsufficientCreditsError(error)) return;
              setSampleError(error);
              setPendingValidation(null);
            });
        }}
        onClose={() => setPendingValidation(null)}
      />
    </RoomShell>
  );
}
import { ErrorNotice } from "../../components/composites/ErrorNotice";
