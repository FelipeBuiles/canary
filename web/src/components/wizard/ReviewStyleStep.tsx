import { useEffect, useRef, useState } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { SectionLabel } from "../SectionLabel";
import { Tag } from "../ui/Tag";
import { ImageModal } from "../ui/ImageModal";
import {
  useGenerationJobs,
  useStyles,
  useSuggestStyles,
  useGenerateStyleSamples,
  useSetActiveStyle,
} from "../../api/queries";
import { usePipelineStore } from "../../store/pipeline";
import {
  useStyleGenStore,
  usePendingIndices,
  useStyleJobIds,
  useStyleJobStatuses,
} from "../../store/styleGen";
import type { StyleSuggestion } from "../../api/styles";

const autoSuggestedProjects = new Set<string>();

interface ReviewStyleStepProps {
  project: string;
  onApprove: () => void;
  isApproving: boolean;
}

function MiniStyleCard({
  suggestion,
  projectName,
  isGenerating,
  queueState,
}: {
  suggestion: StyleSuggestion;
  projectName: string;
  isGenerating: boolean;
  queueState: "queued" | "running" | null;
}) {
  const sampleUrl = `/api/projects/${encodeURIComponent(projectName)}/files/samples/style_${suggestion.index}.png`;
  const [imgFailed, setImgFailed] = useState(!suggestion.has_sample);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const wasGenerating = useRef(isGenerating);
  const generateSamples = useGenerateStyleSamples();
  const setActive = useSetActiveStyle();
  const { add, attachJobs, remove } = useStyleGenStore();

  useEffect(() => {
    if (suggestion.has_sample) setImgFailed(false);
  }, [suggestion.has_sample]);

  useEffect(() => {
    if (wasGenerating.current && !isGenerating) {
      setImgFailed(false);
      setTimestamp(Date.now());
    }
    wasGenerating.current = isGenerating;
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

  return (
    <>
    <Card className="overflow-hidden">
      <div className="relative border-b-[2px] border-ink-black bg-ink-black">
        {imgFailed ? (
          <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
            {isGenerating ? (
              <>
                <div className="font-display text-[1rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                  {queueState === "queued" ? "QUEUED" : "GENERATING…"}
                </div>
                <div className="font-meta text-[0.42rem] tracking-[0.16em] text-bristol/65">
                  {queueState === "queued" ? "WAITING" : "RUNNING"}
                </div>
              </>
            ) : (
              <Button size="xs" variant="secondary" onClick={handleGenerate}>
                GENERATE SAMPLE
              </Button>
            )}
          </div>
        ) : (
          <>
            <img
              src={`${sampleUrl}?t=${timestamp}`}
              alt={suggestion.label}
              loading="lazy"
              width={200}
              height={250}
              className="aspect-[4/5] w-full cursor-zoom-in object-cover"
              onClick={() => setIsModalOpen(true)}
              onError={() => setImgFailed(true)}
            />
            {isGenerating && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-ink-black/60">
                <div className="font-display text-[1rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                  {queueState === "queued" ? "QUEUED" : "GENERATING…"}
                </div>
                <div className="font-meta text-[0.42rem] tracking-[0.16em] text-bristol/65">
                  {queueState === "queued" ? "WAITING FOR GENERATOR" : "SAMPLE IN PROGRESS"}
                </div>
              </div>
            )}
          </>
        )}
        {suggestion.is_active && (
          <Tag className="absolute right-2 top-2 bg-archive-sage text-bristol">
            ACTIVE
          </Tag>
        )}
      </div>
      <div className="p-3">
        <div className="font-display text-[0.82rem] font-bold tracking-[-0.04em] text-ink-black">
          {suggestion.label}
        </div>
        <p className="mt-1.5 font-body text-[0.68rem] leading-relaxed text-ink-black/60 line-clamp-3">
          {suggestion.template}
        </p>
        <div className="mt-2.5 flex gap-2">
          {!suggestion.is_active && (
            <Button size="xs" variant="primary" onClick={() => setActive.mutate({ project: projectName, index: suggestion.index })}>
              SELECT
            </Button>
          )}
          {!imgFailed && (
            <Button size="xs" variant="secondary" onClick={handleGenerate} disabled={isGenerating}>
              {isGenerating ? (queueState === "queued" ? "QUEUED" : "RUNNING") : "REGEN"}
            </Button>
          )}
        </div>
      </div>
    </Card>
    <ImageModal
      isOpen={isModalOpen}
      onClose={() => setIsModalOpen(false)}
      src={`${sampleUrl}?t=${timestamp}`}
      alt={suggestion.label}
    />
    </>
  );
}

export function ReviewStyleStep({ project, onApprove, isApproving }: ReviewStyleStepProps) {
  const { data: stylesData, isLoading, refetch: refetchStyles } = useStyles(project);
  const suggestStyles = useSuggestStyles();
  const generateSamples = useGenerateStyleSamples();
  const events = usePipelineStore((s) => s.events);
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);
  const pendingSet = usePendingIndices(project);
  const styleJobIds = useStyleJobIds(project);
  const styleJobStatuses = useStyleJobStatuses(project);
  const { add, attachJobs, updateJob, remove } = useStyleGenStore();
  const [suggestionStatus, setSuggestionStatus] = useState<"idle" | "running" | "failed">("idle");
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const { data: generationJobs } = useGenerationJobs(
    project,
    Object.values(styleJobIds),
  );

  useEffect(() => {
    if (!generationJobs?.jobs.length) return;
    for (const job of generationJobs.jobs) {
      const index = Number(job.payload.index);
      if (!Number.isFinite(index)) continue;
      if (job.status === "complete" || job.status === "failed") remove(project, [index]);
      else updateJob(project, job);
    }
  }, [generationJobs, project, updateJob, remove]);

  const suggestions = stylesData?.suggestions ?? [];
  const isSuggesting = suggestionStatus === "running";

  function startSuggestions() {
    clearEvents();
    setSuggestionStatus("running");
    setSuggestionError(null);
    suggestStyles.mutate(
      { project },
      {
        onSuccess: () => connect(project),
        onError: (err) => {
          setSuggestionStatus("failed");
          setSuggestionError(err.message);
        },
      },
    );
  }

  useEffect(() => {
    if (isLoading || suggestions.length > 0 || isSuggesting) return;
    if (autoSuggestedProjects.has(project)) return;
    autoSuggestedProjects.add(project);
    startSuggestions();
  }, [isLoading, suggestions.length, isSuggesting, project]);

  useEffect(() => {
    if (!isSuggesting) return;
    for (let i = events.length - 1; i >= 0; i--) {
      const event = events[i];
      if (event.stage !== "style_suggest") continue;
      if (event.type === "stage_complete") {
        setSuggestionStatus("idle");
        setSuggestionError(null);
        refetchStyles();
        return;
      }
      if (event.type === "stage_fail") {
        setSuggestionStatus("failed");
        setSuggestionError(event.message ?? "Style suggestion failed");
        return;
      }
    }
  }, [events, isSuggesting, refetchStyles]);

  if (isLoading) {
    return (
      <Card className="flex min-h-[40vh] items-center justify-center p-5">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">LOADING STYLES…</p>
      </Card>
    );
  }

  function handleGenerateAll() {
    const indices = suggestions.map((s) => s.index);
    add(project, indices);
    generateSamples.mutate(
      { project, indices },
      {
        onSuccess: (data) => attachJobs(project, data.jobs),
        onError: () => remove(project, indices),
      },
    );
  }

  const anyGenerating = pendingSet.size > 0;
  const runningStyleCount = Object.values(styleJobStatuses).filter((status) => status === "running").length;
  const queuedStyleCount = Object.values(styleJobStatuses).filter((status) => status === "queued").length;

  return (
    <div className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="sage">STYLE PICK</SectionLabel>
        <h1 className="mt-4 display-headline">VISUAL STYLE</h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          Pick a visual style for your comic. Generate suggestions and samples to compare,
          then select one — or skip to use the default.
        </p>
        <div className="mt-4 flex gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={handleGenerateAll}
            disabled={suggestions.length === 0 || anyGenerating}
          >
            {anyGenerating
              ? `RUNNING ${runningStyleCount}${queuedStyleCount ? ` / QUEUED ${queuedStyleCount}` : ""}`
              : "GENERATE ALL"}
          </Button>
          <Button
            size="sm"
            variant="primary"
            onClick={startSuggestions}
            disabled={suggestStyles.isPending || isSuggesting}
          >
            {suggestStyles.isPending || isSuggesting ? "REFRESHING…" : "REFRESH SUGGESTIONS"}
          </Button>
        </div>

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
      </Card>

      {suggestions.length === 0 ? (
        <Card className="p-8 text-center">
          <div className="font-display text-[1rem] font-bold text-ink-black/50">
            {isSuggesting ? "GENERATING STYLE SUGGESTIONS" : "NO STYLE SUGGESTIONS YET"}
          </div>
          <div className="mt-2 font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/40">
            {isSuggesting ? "OPTIONS WILL APPEAR AUTOMATICALLY" : "CLICK REFRESH SUGGESTIONS TO GENERATE OPTIONS"}
          </div>
        </Card>
      ) : (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {suggestions.map((s) => (
            <MiniStyleCard
              key={s.index}
              suggestion={s}
              projectName={project}
              isGenerating={pendingSet.has(s.index)}
              queueState={
                pendingSet.has(s.index)
                  ? styleJobStatuses[s.index] ?? "queued"
                  : null
              }
            />
          ))}
        </section>
      )}

      <div className="flex items-center gap-4">
        <Button size="lg" onClick={onApprove} disabled={isApproving || isSuggesting}>
          {isApproving ? "APPROVING…" : "APPROVE & CONTINUE"}
        </Button>
        <span className="text-[0.72rem] text-ink-black/40">
          {stylesData?.active_index != null
            ? `Style #${stylesData.active_index} selected.`
            : "No style selected — default will be used."}
        </span>
      </div>
    </div>
  );
}
