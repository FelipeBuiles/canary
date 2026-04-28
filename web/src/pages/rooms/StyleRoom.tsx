import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  useGenerationJobs,
  useStyles,
  useSuggestStyles,
  useGenerateStyleSamples,
  useSetActiveStyle,
  useImageGenerationMeta,
  useProjectConfig,
  useStoryBible,
} from "../../api/queries";
import { RoomHeader } from "../../components/ui/RoomHeader";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import { Button } from "../../components/ui/Button";
import { RoomShell } from "../../components/ui/RoomShell";
import { GenerationDetailsModal } from "../../components/ui/GenerationDetailsModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StateBlock } from "../../components/ui/StateBlock";
import { Surface } from "../../components/ui/Surface";
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
  queueState,
  fallbackPrompt,
  fallbackParameters,
}: {
  suggestion: StyleSuggestion;
  projectName: string;
  isGenerating: boolean;
  queueState: "queued" | "running" | null;
  fallbackPrompt: string;
  fallbackParameters: Record<string, unknown>;
}) {
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

  const isActive = suggestion.is_active;

  return (
    <>
      <article
        className={`flex min-h-[520px] flex-col bg-bristol transition-[box-shadow,border-color] duration-150 ${
          isActive
            ? "border-[3px] border-ink-black shadow-ink"
            : "border-[3px] border-ink-black/8 shadow-none"
        }`}
      >
        <div className="relative bg-surface-container">
          {imgFailed ? (
            <div className="flex aspect-[4/5] w-full flex-col items-center justify-center">
              {isGenerating && (
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 animate-pulse">
                  {queueState === "queued" ? "QUEUED" : "GENERATING…"}
                </div>
              )}
            </div>
          ) : (
            <div className="group cursor-pointer" onClick={() => setIsDetailsOpen(true)}>
              <LazyImage
                src={`${sampleUrl}?t=${timestamp}`}
                alt={suggestion.label}
                loading="lazy"
                width={320}
                height={400}
                aspect="4 / 5"
                containerClassName="w-full"
                className="object-cover object-center transition-opacity group-hover:opacity-90"
                onError={() => setImgFailed(true)}
              />
              {isGenerating && (
                <div className="absolute inset-0 flex items-center justify-center bg-ink-black/60">
                  <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/70 animate-pulse">
                    {queueState === "queued" ? "QUEUED" : "GENERATING…"}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ACTIVE badge */}
          {isActive && (
            <div className="absolute left-5 top-5 bg-hero-red px-4 py-2 font-meta text-[0.68rem] tracking-[0.18em] text-bristol">
              ACTIVE
            </div>
          )}

          {/* Generate / regenerate icon button */}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={isGenerating}
            title={suggestion.has_sample ? "Regenerate sample" : "Generate sample"}
            className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center bg-ink-black/55 text-bristol transition-colors hover:bg-ink-black disabled:opacity-40"
          >
            <span className="font-meta text-[0.78rem]">↺</span>
          </button>
        </div>

        <div className="flex flex-1 flex-col bg-bristol p-6">
          <div className="font-display text-[1.35rem] font-bold leading-tight tracking-[-0.04em] text-ink-black">
            {suggestion.label}
          </div>
          <p className="mt-3 flex-1 font-body text-[1rem] font-semibold leading-relaxed text-ink-black/68 line-clamp-4">
            {suggestion.template}
          </p>
          <div className="mt-8">
            {isActive ? (
              <button
                type="button"
                disabled
                className="inline-flex min-h-14 w-full items-center justify-center gap-2 bg-hero-red px-5 py-3 font-meta text-[0.9rem] tracking-[0.18em] text-bristol disabled:cursor-default"
              >
                ✓ SELECTED
              </button>
            ) : (
              <button
                type="button"
                className="inline-flex min-h-14 w-full items-center justify-center bg-hero-red px-5 py-3 font-meta text-[0.9rem] tracking-[0.18em] text-bristol transition-colors hover:bg-hero-red/90 disabled:cursor-not-allowed disabled:opacity-45"
                onClick={() => setActive.mutate({ project: projectName, index: suggestion.index })}
                disabled={isGenerating}
              >
                SELECT
              </button>
            )}
          </div>
        </div>
      </article>
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
  const { name } = useParams<{ name: string }>();
  const { isCompact, toggle } = useHeaderMode();
  const projectName = name ?? "";
  const { data: stylesData, isLoading, refetch: refetchStyles } = useStyles(name);
  const { data: projectConfig } = useProjectConfig(name);
  const { data: storyBible } = useStoryBible(name);
  const suggestStyles = useSuggestStyles();
  const generateSamples = useGenerateStyleSamples();
  const pendingSet = usePendingIndices(projectName);
  const styleJobIds = useStyleJobIds(projectName);
  const styleJobStatuses = useStyleJobStatuses(projectName);
  const { add, attachJobs, updateJob, remove } = useStyleGenStore();
  const [sampleError, setSampleError] = useState<string | null>(null);
  const { data: generationJobs } = useGenerationJobs(
    name,
    Object.values(styleJobIds),
  );
  const events = usePipelineStore((s) => s.events);
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);
  const [suggestionStatus, setSuggestionStatus] = useState<"idle" | "running" | "failed">("idle");
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const prevSuggestionCount = useRef(0);

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

  const isSuggesting = suggestionStatus === "running";

  // Listen for SSE events to detect suggestion completion
  useEffect(() => {
    if (!isSuggesting) return;
    for (let i = events.length - 1; i >= 0; i--) {
      const event = events[i];
      if (event.stage !== "style_suggest") continue;
      if (event.type === "stage_complete") {
        const timer = window.setTimeout(() => {
          setSuggestionStatus("idle");
          setSuggestionError(null);
          refetchStyles().then(({ data }) => {
            const all = data?.suggestions ?? [];
            const newIndices = all.slice(prevSuggestionCount.current).map((s) => s.index);
            if (newIndices.length === 0) return;
            add(projectName, newIndices);
            generateSamples.mutate(
              { project: projectName, indices: newIndices },
              {
                onSuccess: (d) => attachJobs(projectName, d.jobs),
                onError: () => remove(projectName, newIndices),
              },
            );
          });
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
  }, [events, isSuggesting, refetchStyles, add, attachJobs, generateSamples, projectName, remove]);

  // Auto-trigger suggestions on first visit when none exist yet
  const autoTriggered = useRef(false);
  useEffect(() => {
    if (autoTriggered.current) return;
    if (isLoading || !stylesData) return;
    if (stylesData.suggestions.length > 0) return;
    if (isSuggesting || suggestStyles.isPending) return;
    if (!storyBible) return;
    autoTriggered.current = true;
    prevSuggestionCount.current = 0;
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
  }, [isLoading, stylesData, storyBible, isSuggesting]);

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING STYLES…" />;
  }

  if (!name) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="STYLES NOT AVAILABLE"
        emptyDescription="Select a project first."
      />
    );
  }

  const suggestions = stylesData?.suggestions ?? [];

  function startSuggestions() {
    prevSuggestionCount.current = stylesData?.suggestions.length ?? 0;
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
  const effectiveModel = projectConfig?.dev_mode && projectConfig?.image_model === "gemini-3-pro-image-preview"
    ? (projectConfig?.fallback_image_model || "gemini-3.1-flash-image-preview")
    : projectConfig?.image_model;
  const effectiveSteps = projectConfig?.dev_mode
    ? Math.min(projectConfig?.image_steps ?? 0, projectConfig?.dev_image_steps ?? 0)
    : projectConfig?.image_steps;

  return (
    <RoomShell>
      <RoomHeader
        kicker="STYLES"
        compact={isCompact}
        onToggle={toggle}
        title="LOOK & FEEL"
        lead="Pick the visual style that defines your comic. Generate samples to compare, then select one to lock it in."
        actions={
          <div className="flex gap-2">
            {anyGenerating && (
              <span className="font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/50 self-center">
                {runningStyleCount > 0 && `${runningStyleCount} RUNNING`}{runningStyleCount > 0 && queuedStyleCount > 0 && " / "}{queuedStyleCount > 0 && `${queuedStyleCount} QUEUED`}
              </span>
            )}
            {sampleError && (
              <span className="font-meta text-[0.48rem] tracking-[0.16em] text-hero-red self-center">
                {sampleError}
              </span>
            )}
            <Button
              size="sm"
              variant="primary"
              onClick={startSuggestions}
              disabled={suggestStyles.isPending || isSuggesting}
            >
              {suggestStyles.isPending || isSuggesting ? "SUGGESTING…" : "SUGGEST MORE STYLES"}
            </Button>
          </div>
        }
      />

      {(isSuggesting || suggestionStatus === "failed") && (
        <div className={`mt-4 border-[2px] border-ink-black p-3 ${
          suggestionStatus === "failed" ? "bg-hero-red text-bristol" : "bg-narrator-gold text-ink-black"
        }`}>
          <div className="flex items-center gap-2">
            {isSuggesting && <span className="h-2.5 w-2.5 animate-pulse bg-hero-red" />}
            <span className="font-meta text-[0.48rem] tracking-[0.16em]">
              {suggestionStatus === "failed" ? "STYLE SUGGESTION FAILED" : "STYLE SUGGESTIONS RUNNING"}
            </span>
          </div>
          <div className="mt-1 font-body text-[0.78rem] leading-relaxed">
            {suggestionStatus === "failed"
              ? suggestionError
              : "Asking the art director for five visual directions. This usually takes a short model call."}
          </div>
        </div>
      )}

      {suggestions.length === 0 ? (
        <Surface padding="lg">
          <StateBlock
            minHeight="min-h-[22vh]"
            title={isSuggesting ? "GENERATING STYLE SUGGESTIONS" : "NO STYLE SUGGESTIONS YET"}
            description={isSuggesting ? "Options will appear automatically." : "Click \"Suggest More Styles\" to generate 5 options."}
            icon="styles"
          />
        </Surface>
      ) : (
        <section className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {suggestions.map((s) => (
            <StyleCard
              key={s.index}
              suggestion={s}
              projectName={name}
              isGenerating={pendingSet.has(s.index)}
              queueState={
                pendingSet.has(s.index)
                  ? styleJobStatuses[s.index] ?? "queued"
                  : null
              }
              fallbackPrompt={buildFallbackStyleSamplePrompt(s, storyBible)}
              fallbackParameters={{
                image_model: effectiveModel,
                width: projectConfig?.image_width,
                height: projectConfig?.image_height,
                steps: effectiveSteps,
                guidance_scale: projectConfig?.flux_guidance_scale,
                style_template: s.template,
              }}
            />
          ))}
        </section>
      )}
    </RoomShell>
  );
}
