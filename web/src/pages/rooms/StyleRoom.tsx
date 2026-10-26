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
import { Columns2, Eye, EyeOff, Plus, RotateCcw, TriangleAlert, X } from "lucide-react";
import { BookLetteringPanel } from "../../components/lettering/BookLetteringPanel";
import { StyleGenerationProgress } from "../../components/style/StyleGenerationProgress";
import { ProofStage } from "../../components/style/ProofStage";
import { ProofInspector } from "../../components/style/ProofInspector";
import { ProofFilmstrip, ProofSheet } from "../../components/style/ProofBrowse";
import { ProofComparison } from "../../components/style/ProofComparison";
import { Button } from "../../components/ui/Button";
import { StateBlock } from "../../components/ui/StateBlock";
import { Surface } from "../../components/ui/Surface";
import { ApprovalBar, RoomHeader, ConfirmDrawer, RerunStageAction, RoomNoticeRow, RoomShell } from "../../components/composites";
import { Sheet } from "../../components/composites/Sheet";
import { useApproveStage, useStageEstimate } from "../../api/queries";
import { useRunAction } from "../../hooks/useRunAction";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { StyleDirectionComposer, type StyleDirectionMode } from "../../components/style/StyleDirectionComposer";
import { usePipelineStore } from "../../store/pipeline";
import { isAuthorDirection, proofImageUrl, styleName, type StyleSuggestion } from "../../api/styles";
import type { CostEstimate, StoryBible } from "../../types/api";
import { splitProjectKey } from "../../api/projectScope";

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

const SEGMENT = "flex h-8 items-center gap-1.5 px-3 font-meta text-[0.8125rem] font-medium transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-narrator-gold";
const DARK_BUTTON = "inline-flex h-8 items-center gap-2 border border-pulp-paper/22 px-3 font-meta text-[0.8125rem] font-medium text-pulp-paper transition-colors hover:bg-pulp-paper/8 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold";

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
  const [proofFilter, setProofFilter] = useState<"all" | "yours" | "suggested">("all");
  const [proofView, setProofView] = useState<"table" | "sheet" | "compare">("table");
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
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
  const activeSuggestion = suggestions.find((suggestion) => suggestion.is_active);
  const proofQueued = (suggestion: StyleSuggestion) => pendingSet.has(suggestion.index)
    || suggestion.generation_status === "queued" || suggestion.generation_status === "running";
  const proofBusy = (suggestion: StyleSuggestion) => proofQueued(suggestion)
    || (!suggestion.has_sample && batchInFlight && suggestion.generation_status !== "failed");
  const staleSuggestions = suggestions.filter((suggestion) => suggestion.sample_stale && !proofQueued(suggestion));
  // Hidden proofs were set aside on purpose; retry them from their own stage.
  const missingSuggestions = batchInFlight ? [] : suggestions.filter(
    (suggestion) => !suggestion.has_sample && !suggestion.hidden && !proofQueued(suggestion),
  );
  const pendingProofCount = pendingProofs?.suggestions.length ?? 0;
  const pendingProofEstimate = multiplyEstimate(sampleEstimate, pendingProofCount);
  const retryingProofs = pendingProofs?.kind === "retry";
  const proofName = (suggestion: StyleSuggestion) => isAuthorDirection(suggestion)
    ? `${t("Yours")} · ${styleName(suggestion)}`
    : styleName(suggestion);
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
  const stripSuggestions = showHidden && hiddenSuggestions.length > 0
    ? [...filteredSuggestions, ...hiddenSuggestions]
    : filteredSuggestions;
  const current = stripSuggestions.find((suggestion) => suggestion.id === currentId)
    ?? stripSuggestions.find((suggestion) => suggestion.is_active)
    ?? stripSuggestions[0];
  const currentPosition = current ? stripSuggestions.indexOf(current) : -1;
  const drawn = stripSuggestions.filter((suggestion) => suggestion.has_sample);
  const inspectImages = drawn.map((suggestion) => ({ src: proofImageUrl(id, suggestion), alt: proofName(suggestion) }));
  const comparing = proofView === "compare" && comparedSuggestions.length >= 2;
  const view = comparing ? "compare" : proofView === "sheet" ? "sheet" : "table";
  const step = (delta: number) => {
    if (stripSuggestions.length === 0) return;
    const next = (currentPosition + delta + stripSuggestions.length) % stripSuggestions.length;
    setCurrentId(stripSuggestions[next].id);
  };
  const queueStateOf = (suggestion: StyleSuggestion) => suggestion.generation_status === "queued" || suggestion.generation_status === "running"
    ? suggestion.generation_status
    : pendingSet.has(suggestion.index) ? styleJobStatuses[suggestion.index] as "queued" | "running" : null;
  const suggestionFailure = suggestionStatus === "failed" || latestSuggestionJob?.status === "failed"
    ? suggestionError ?? latestSuggestionJob?.user_message ?? latestSuggestionJob?.error ?? null
    : null;
  // With proofs on the table, a failed attempt is evidence behind one toolbar control.
  const attention = sampleError ?? (suggestions.length > 0 ? suggestionFailure : null)
    ?? [...proofJobs, ...Object.values(validationJobs)].find(job => job?.status === "failed")?.error;
  const darkSegment = (on: boolean) => cn(SEGMENT, on ? "bg-pulp-paper text-ink-black" : "text-pulp-paper/85 hover:bg-pulp-paper/8 hover:text-pulp-paper");
  const composer = (
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
  );
  const notices = (
    <>
      {suggestionFailure && suggestions.length === 0 ? (
        <ErrorNotice error={suggestionFailure} operation="generate" />
      ) : (isSuggesting || isStageGenerating) && (
        <StyleGenerationProgress
          job={activeBatchJob}
          // Existing proofs belong to earlier batches, not this new suggestion run.
          fallbackPhase={isStageGenerating && suggestions.length > 0 ? "proofs" : "directions"}
          title={isStageGenerating ? t("Drawing style options") : t("Drawing more styles")}
          // With proofs on the table, progress is one line; before the first proof it is the room.
          compact={suggestions.length > 0}
        />
      )}
    </>
  );
  const hasNotices = (!!suggestionFailure && suggestions.length === 0) || isSuggesting || isStageGenerating;
  // Proof upkeep sits in the table's toolbar so it never shrinks the proof.
  const upkeep = (
    <>
      {missingSuggestions.length > 0 && (
        <span role="status" className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 font-meta text-[0.8125rem] font-medium text-narrator-gold">
            <TriangleAlert size={14} aria-hidden="true" />
            {t("{count, plural, one {# proof didn't finish} other {# proofs didn't finish}}", { count: missingSuggestions.length })}
          </span>
          <button type="button" className={DARK_BUTTON} disabled={proofQueueDisabled}
            onClick={() => setPendingProofs({ kind: "retry", suggestions: missingSuggestions })}>
            {missingSuggestions.length === 1 ? t("Try it again") : t("Retry all ({count})", { count: String(missingSuggestions.length) })}
          </button>
        </span>
      )}
      {staleSuggestions.length > 0 && (
        <button type="button" className={DARK_BUTTON} disabled={proofQueueDisabled} title={t("Some proofs were drawn with older rendering rules.")}
          onClick={() => setPendingProofs({ kind: "refresh", suggestions: staleSuggestions })}>
          <RotateCcw size={14} aria-hidden="true" />{t("Refresh all ({count})", { count: String(staleSuggestions.length) })}
        </button>
      )}
      {attention && (
        <details className="relative">
          <summary className={cn(DARK_BUTTON, "cursor-pointer list-none text-narrator-gold! [&::-webkit-details-marker]:hidden")}>
            <TriangleAlert size={14} aria-hidden="true" />{t("Needs attention")}
          </summary>
          <div className="absolute right-0 top-full z-20 mt-2 w-[22rem] border border-ink-black bg-bristol px-4 py-1 text-ink-black shadow-float">
            <ErrorNotice error={attention} operation="generate" />
          </div>
        </details>
      )}
    </>
  );

  return (
    <RoomShell project={id} bleed>
      <RoomHeader
        title={t("Look")}
        lead={[
          suggestions.length > 0 ? t("{count, plural, one {# proof} other {# proofs}}", { count: suggestions.length }) : t("No proofs yet"),
          activeSuggestion ? proofName(activeSuggestion) : undefined,
          projectConfig?.lettering_mode === "integrated" ? t("Integrated lettering") : undefined,
        ].filter(Boolean).join(" · ")}
      />

      {hasNotices && suggestions.length > 0 && <RoomNoticeRow>{notices}</RoomNoticeRow>}
      {letteringOpen && (
        <div className="px-4 pt-4 sm:px-6 studio-desktop:px-5">
          <BookLetteringPanel project={projectName} disabled={isStageGenerating} onClose={() => setLetteringOpen(false)} />
        </div>
      )}

      {stylesLoadFailed ? (
        <div className="p-4 sm:p-6">
          <Surface padding="lg">
            <StateBlock
              minHeight="min-h-[22vh]"
              title={t("WE COULDN'T LOAD THE PROOFS")}
              description={t("The style room could not reach the project. Your existing work is unchanged.")}
              icon="styles"
              tone="danger"
              action={<Button size="sm" onClick={() => refetchStyles()}>{t("TRY AGAIN")}</Button>}
            />
          </Surface>
        </div>
      ) : suggestions.length === 0 && !isStageGenerating && !isSuggesting ? (
        <section aria-labelledby="find-the-look" className="benday-ink flex flex-1 flex-col justify-center px-4 py-8 text-pulp-paper sm:px-8 xl:px-12">
          <div className="mx-auto w-full max-w-[68rem]">
            <h2 id="find-the-look" className="font-display text-[2.5rem] font-black uppercase leading-[0.9] tracking-[-0.04em] sm:text-[3.25rem]">{t("Find the look")}</h2>
            <p className="mt-3 max-w-[40rem] font-body text-base leading-6 text-pulp-paper/80">{t("Every proof draws the same scene from your story, so you compare styles, not scenes.")}</p>
            {suggestionFailure && <div className="mt-6 bg-bristol px-4 py-1 text-ink-black">{notices}</div>}
            <div className="mt-7">{composer}</div>
          </div>
        </section>
      ) : suggestions.length === 0 ? (
        <section aria-label={t("Style proofs")} className="benday-ink flex flex-1 items-center justify-center px-4 py-8 sm:px-8">
          {notices}
        </section>
      ) : !letteringOpen && (
        <div className="flex min-h-[34rem] flex-1 flex-col studio-desktop:min-h-0 studio-desktop:flex-row">
          <section aria-label={t("Style proofs")} className="benday-ink flex min-w-0 flex-1 flex-col text-pulp-paper">
            <div className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 px-5 py-2.5">
              {drawn.length > 1 && (
                <div role="group" aria-label={t("Proof view")} className="inline-flex border border-pulp-paper/22">
                  <button type="button" aria-pressed={view === "table"} onClick={() => setProofView("table")} className={darkSegment(view === "table")}>{t("Table")}</button>
                  <button type="button" aria-pressed={view === "sheet"} onClick={() => setProofView("sheet")} className={darkSegment(view === "sheet")}>{t("Sheet")}</button>
                </div>
              )}
              {yoursCount > 0 && suggestedCount > 0 && (
                <div role="group" aria-label={t("Filter proofs")} className="inline-flex border border-pulp-paper/22">
                  {([
                    ["all", t("All"), shownSuggestions.length],
                    ["yours", t("Yours"), yoursCount],
                    ["suggested", t("Suggested"), suggestedCount],
                  ] as const).map(([value, label, count]) => (
                    <button key={value} type="button" aria-pressed={effectiveFilter === value} onClick={() => setProofFilter(value)} className={darkSegment(effectiveFilter === value)}>
                      {label} <span className="tabular-nums opacity-70">{count}</span>
                    </button>
                  ))}
                </div>
              )}
              {view === "table" && current && (
                <span className="font-meta text-[0.8125rem] text-on-chrome-muted">{t("{position} of {count}", { position: String(currentPosition + 1), count: String(stripSuggestions.length) })}</span>
              )}
              {anyGenerating && (
                <span role="status" aria-live="polite" className="flex items-center gap-2 font-meta text-[0.8125rem] text-on-chrome-muted">
                  <span aria-hidden="true" className="size-2 animate-pulse bg-narrator-gold" />
                  {[runningStyleCount > 0 && t("{count} drawing", { count: String(runningStyleCount) }), queuedStyleCount > 0 && t("{count} queued", { count: String(queuedStyleCount) })].filter(Boolean).join(" · ")}
                </span>
              )}
              <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
                {upkeep}
                {hiddenSuggestions.length > 0 && (
                  <button type="button" aria-pressed={showHidden} onClick={() => setShowHidden((shown) => !shown)} className={cn(DARK_BUTTON, showHidden && "bg-pulp-paper/10!")}>
                    {showHidden ? <Eye size={15} aria-hidden="true" /> : <EyeOff size={15} aria-hidden="true" />}{t("Hidden")} <span className="tabular-nums opacity-70">{hiddenSuggestions.length}</span>
                  </button>
                )}
                {comparedSuggestions.length > 0 && (
                  <>
                    <button type="button" disabled={comparedSuggestions.length < 2} aria-pressed={comparing}
                      onClick={() => setProofView(comparing ? "table" : "compare")}
                      className={cn(DARK_BUTTON, comparing && "border-ink-black! bg-narrator-gold! text-ink-black!")}>
                      <Columns2 size={15} aria-hidden="true" />
                      {comparedSuggestions.length < 2 ? t("Compare · add one more") : comparing ? t("Comparing {count}", { count: String(comparedSuggestions.length) }) : t("Compare {count}", { count: String(comparedSuggestions.length) })}
                    </button>
                    <button type="button" onClick={() => { setCompareIds([]); setProofView((current) => current === "compare" ? "table" : current); }}
                      aria-label={t("Clear comparison")} title={t("Clear comparison")} className={cn(DARK_BUTTON, "px-2")}>
                      <X size={14} aria-hidden="true" />
                    </button>
                  </>
                )}
                {projectConfig?.lettering_mode !== "integrated" && styleSelected && (
                  <button type="button" disabled={styleActionsDisabled} onClick={() => setLetteringOpen(true)} className={DARK_BUTTON}>{t("Edit book lettering")}</button>
                )}
                <button type="button" onClick={() => setShowDirectionComposer(true)} disabled={letteringOpen} className={DARK_BUTTON}>
                  <Plus size={15} aria-hidden="true" />{t("New direction")}
                </button>
              </div>
            </div>

            {view === "compare" ? (
              <ProofComparison
                projectName={id}
                suggestions={comparedSuggestions}
                proofName={proofName}
                selectionDisabled={letteringOpen}
                onRemove={(removed) => toggleCompare(removed)}
              />
            ) : view === "sheet" ? (
              <ProofSheet projectName={id} suggestions={stripSuggestions} isBusy={proofBusy}
                onOpen={(opened) => { setCurrentId(opened); setProofView("table"); }} />
            ) : current && (
              <ProofStage
                key={current.id}
                projectName={id}
                suggestion={current}
                position={currentPosition + 1}
                count={stripSuggestions.length}
                isGenerating={proofQueued(current)}
                awaitingBatch={batchInFlight}
                queueState={queueStateOf(current)}
                retryDisabled={proofQueueDisabled}
                onRetry={() => setPendingProofs({ kind: "retry", suggestions: [current] })}
                onStep={step}
                inspectImages={inspectImages}
                inspectIndex={Math.max(drawn.indexOf(current), 0)}
                onInspectIndexChange={(next) => setCurrentId(drawn[next]?.id ?? null)}
              />
            )}

            {view !== "sheet" && (
              <ProofFilmstrip
                projectName={id}
                suggestions={stripSuggestions}
                currentId={view === "table" ? current?.id ?? null : null}
                compareIds={compareIds}
                isBusy={proofBusy}
                onPick={(picked) => { setCurrentId(picked); setProofView("table"); }}
                onNew={() => setShowDirectionComposer(true)}
                newDisabled={letteringOpen}
              />
            )}
          </section>

          {view !== "compare" && current && (
            <ProofInspector
              key={current.id}
              suggestion={current}
              projectName={id}
              imageSrc={proofImageUrl(id, current)}
              imageAvailable={current.has_sample}
              isGenerating={proofQueued(current)}
              generationDisabled={letteringOpen}
              retryDisabled={proofQueueDisabled}
              selectionDisabled={letteringOpen}
              isCompared={compareIds.includes(current.id)}
              compareDisabled={comparedSuggestions.length >= 3}
              onToggleCompare={() => toggleCompare(current.id)}
              validationBusy={isGenerationActive(validationJobs[current.id])}
              onValidate={() => setPendingValidation(current)}
              onRefresh={() => setPendingProofs({ kind: "refresh", suggestions: [current] })}
              fallbackPrompt={buildFallbackStyleSamplePrompt(current, storyBible)}
              fallbackParameters={{
                width: projectConfig?.image_width,
                height: projectConfig?.image_height,
                steps: effectiveSteps,
                guidance_scale: projectConfig?.flux_guidance_scale,
                style_template: current.template,
              }}
            />
          )}
        </div>
      )}

      <Sheet open={showDirectionComposer && suggestions.length > 0} title={t("New direction")} onClose={() => setShowDirectionComposer(false)} wide>
        {composer}
      </Sheet>

      {!isPipelineRunning && !isStageGenerating && !isSuggesting && <ApprovalBar
        next={styleSelected
          ? needsCover
            ? t("Scenewright casts your characters and places, and draws your project cover")
            : t("Scenewright casts your characters and places in this style")
          : t("Choose a style, then cast your characters and places in it")}
        estimateCredits={continueEstimateCredits}
        primaryLabel={t("Continue to Cast")}
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
          ? pendingProofCount > 1 ? t("Retry all ({count})", { count: String(pendingProofCount) }) : t("Try it again")
          : pendingProofCount > 1 ? t("Refresh all ({count})", { count: String(pendingProofCount) }) : t("Refresh proof")}
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
