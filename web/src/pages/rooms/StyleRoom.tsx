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
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Card } from "../../components/ui/Card";
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
      <Card
        shadow="lg"
        className={`flex flex-col ${isActive ? "border-[3px]" : ""}`}
      >
        <div className="relative border-b-[2px] border-ink-black">
          {imgFailed ? (
            <div className="flex aspect-[4/3] w-full flex-col items-center justify-center bg-surface-container">
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
                height={240}
                aspect="4 / 3"
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
            <div className="absolute left-0 top-0 bg-hero-red px-2 py-1 font-meta text-[0.5rem] tracking-[0.18em] text-bristol">
              ACTIVE
            </div>
          )}

          {/* Generate / regenerate icon button */}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={isGenerating}
            title={suggestion.has_sample ? "Regenerate sample" : "Generate sample"}
            className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center bg-ink-black/55 text-bristol transition-opacity hover:bg-ink-black disabled:opacity-40"
          >
            <span className="font-meta text-[0.5rem]">↺</span>
          </button>
        </div>

        <div className="flex flex-1 flex-col p-3">
          <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black">
            {suggestion.label}
          </div>
          <p className="mt-2 flex-1 font-body text-[0.78rem] leading-relaxed text-ink-black/70 line-clamp-3">
            {suggestion.template}
          </p>
          <div className="mt-3 border-t-[2px] border-ink-black pt-3">
            {isActive ? (
              <button
                type="button"
                disabled
                className="inline-flex w-full items-center justify-center gap-1.5 bg-hero-red px-3 py-2 font-meta text-[0.62rem] tracking-[0.14em] text-bristol disabled:cursor-default"
              >
                ✓ SELECTED
              </button>
            ) : (
              <Button
                size="sm"
                variant="primary"
                className="w-full"
                onClick={() => setActive.mutate({ project: projectName, index: suggestion.index })}
                disabled={isGenerating}
              >
                SELECT
              </Button>
            )}
          </div>
        </div>
      </Card>
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
      <ShowcaseHeader
        label="STYLES / VISUAL IDENTITY"
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
