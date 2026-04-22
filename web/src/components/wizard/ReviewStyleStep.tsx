import { useCallback, useEffect, useRef, useState } from "react";
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
import { useI18n } from "../../i18n";

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
  const { t } = useI18n();
  const sampleUrl = `/api/projects/${encodeURIComponent(projectName)}/files/samples/style_${suggestion.index}.png`;
  const [imgFailed, setImgFailed] = useState(!suggestion.has_sample);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const wasGenerating = useRef(isGenerating);
  const generateSamples = useGenerateStyleSamples();
  const setActive = useSetActiveStyle();
  const { add, attachJobs, remove } = useStyleGenStore();

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

  return (
    <>
    <Card className="flex flex-col overflow-hidden">
      <div className="relative border-b-[2px] border-ink-black bg-ink-black">
        {imgFailed ? (
          <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
            {isGenerating ? (
              <>
                <div className="font-display text-[1rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                  {queueState === "queued" ? t("QUEUED") : t("GENERATING…")}
                </div>
                <div className="font-meta text-[0.42rem] tracking-[0.16em] text-bristol/65">
                  {queueState === "queued" ? t("WAITING") : t("RUNNING")}
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
              className="block w-full aspect-[4/5] object-cover object-center cursor-zoom-in"
              onClick={() => setIsModalOpen(true)}
              onError={() => setImgFailed(true)}
            />
            {isGenerating && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-ink-black/60">
                <div className="font-display text-[1rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                  {queueState === "queued" ? t("QUEUED") : t("GENERATING…")}
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
            {t("ACTIVE")}
          </Tag>
        )}
      </div>
      <div className="flex flex-1 flex-col p-3">
        <div className="font-display text-[0.82rem] font-bold tracking-[-0.04em] text-ink-black">
          {suggestion.label}
        </div>
        <p className="mt-1.5 font-body text-[0.68rem] leading-relaxed text-ink-black/60 line-clamp-3">
          {suggestion.template}
        </p>
        <div className="mt-auto flex flex-wrap gap-2 pt-2.5">
          <Button
            size="sm"
            variant={suggestion.is_active ? "secondary" : "primary"}
            className="min-w-[min(7.5rem,100%)] flex-1 whitespace-nowrap"
            onClick={suggestion.is_active ? handleGenerate : () => setActive.mutate({ project: projectName, index: suggestion.index })}
            disabled={suggestion.is_active && isGenerating}
          >
            {suggestion.is_active
              ? (isGenerating ? (queueState === "queued" ? t("QUEUED") : t("GENERATING…")) : t("REGENERATE"))
              : t("SELECT")}
          </Button>
          {!suggestion.is_active && (
            <Button
              size="sm"
              variant="secondary"
              className="min-w-[min(7.5rem,100%)] flex-1 whitespace-nowrap"
              onClick={handleGenerate}
              disabled={isGenerating}
            >
              {isGenerating ? (queueState === "queued" ? t("QUEUED") : t("GENERATING…")) : t("REGENERATE")}
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
  const { t } = useI18n();
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
  const prevSuggestionCount = useRef(0);
  const { data: generationJobs } = useGenerationJobs(
    project,
    Object.values(styleJobIds),
  );

  useEffect(() => {
    if (!generationJobs?.jobs.length) return;
    const timer = window.setTimeout(() => {
      for (const job of generationJobs.jobs) {
        const index = Number(job.payload.index);
        if (!Number.isFinite(index)) continue;
        if (job.status === "complete" || job.status === "failed") remove(project, [index]);
        else updateJob(project, job);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs, project, updateJob, remove]);

  const suggestions = stylesData?.suggestions ?? [];
  const isSuggesting = suggestionStatus === "running";

  const startSuggestions = useCallback(() => {
    prevSuggestionCount.current = stylesData?.suggestions.length ?? 0;
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
  }, [clearEvents, connect, project, stylesData?.suggestions.length, suggestStyles]);

  useEffect(() => {
    if (isLoading || suggestions.length > 0 || isSuggesting) return;
    if (autoSuggestedProjects.has(project)) return;
    autoSuggestedProjects.add(project);
    const timer = window.setTimeout(startSuggestions, 0);
    return () => window.clearTimeout(timer);
  }, [isLoading, suggestions.length, isSuggesting, project, startSuggestions]);

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
            add(project, newIndices);
            generateSamples.mutate(
              { project, indices: newIndices },
              {
                onSuccess: (d) => attachJobs(project, d.jobs),
                onError: () => remove(project, newIndices),
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
  }, [events, isSuggesting, refetchStyles, add, attachJobs, generateSamples, project, remove]);

  if (isLoading) {
    return (
      <Card className="flex min-h-[40vh] items-center justify-center p-5">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">{t("LOADING STYLES…")}</p>
      </Card>
    );
  }

  const anyGenerating = pendingSet.size > 0;

  return (
    <div className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="sage">{t("STYLE PICK")}</SectionLabel>
        <h1 className="mt-4 display-headline">{t("VISUAL STYLE")}</h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          Pick a visual style for your comic. Generate suggestions and samples to compare,
          then select one — or skip to use the default.
        </p>
        <div className="mt-4 flex gap-2">
          {anyGenerating && (
            <span className="font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/50 self-center">
              {t("GENERATING SAMPLES…")}
            </span>
          )}
          <Button
            size="sm"
            variant="primary"
            onClick={startSuggestions}
            disabled={suggestStyles.isPending || isSuggesting}
          >
            {suggestStyles.isPending || isSuggesting ? t("SUGGESTING…") : t("SUGGEST MORE STYLES")}
          </Button>
        </div>

        {(isSuggesting || suggestionStatus === "failed") && (
          <div className={`mt-4 border-[2px] border-ink-black p-3 ${
            suggestionStatus === "failed" ? "bg-hero-red text-bristol" : "bg-narrator-gold text-ink-black"
          }`}>
            <div className="flex items-center gap-2">
              {isSuggesting && <span className="h-2.5 w-2.5 animate-pulse bg-hero-red" />}
              <span className="font-meta text-[0.48rem] tracking-[0.16em]">
                {suggestionStatus === "failed" ? t("STYLE SUGGESTION FAILED") : t("STYLE SUGGESTIONS RUNNING")}
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
            {isSuggesting ? t("GENERATING STYLE SUGGESTIONS") : t("NO STYLE SUGGESTIONS YET")}
          </div>
          <div className="mt-2 font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/40">
            {isSuggesting ? t("OPTIONS WILL APPEAR AUTOMATICALLY") : t("CLICK SUGGEST MORE STYLES TO GENERATE OPTIONS")}
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
          {isApproving ? t("APPROVING…") : t("APPROVE & CONTINUE")}
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
