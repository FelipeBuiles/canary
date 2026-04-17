import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  useGenerationJobs,
  useStyles,
  useSuggestStyles,
  useGenerateStyleSamples,
  useSetActiveStyle,
} from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { Button } from "../../components/ui/Button";
import { RoomShell } from "../../components/ui/RoomShell";
import { ImageModal } from "../../components/ui/ImageModal";
import {
  useStyleGenStore,
  usePendingIndices,
  useStyleJobIds,
  useStyleJobStatuses,
} from "../../store/styleGen";
import type { StyleSuggestion } from "../../api/styles";

function StyleCard({
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
      <Card>
        <div
          className="relative border-b-[2px] border-ink-black bg-ink-black cursor-pointer group"
          onClick={() => !imgFailed && setIsModalOpen(true)}
        >
          {imgFailed ? (
            <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
              {isGenerating ? (
                <>
                  <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                    {queueState === "queued" ? "QUEUED" : "GENERATING…"}
                  </div>
                  <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
                    {queueState === "queued" ? "WAITING FOR GENERATOR" : "STYLE SAMPLE IN PROGRESS"}
                  </div>
                </>
              ) : (
                <>
                  <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/40">NO SAMPLE YET</div>
                  <Button size="xs" variant="secondary" className="mt-2" onClick={handleGenerate}>
                    GENERATE SAMPLE
                  </Button>
                </>
              )}
            </div>
          ) : (
            <>
              <img
                src={`${sampleUrl}?t=${timestamp}`}
                alt={suggestion.label}
                loading="lazy"
                width={320}
                height={400}
                className="aspect-[4/5] w-full object-cover hover:opacity-90 transition-opacity"
                onError={() => setImgFailed(true)}
              />
              <div
                className={`absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/60 transition-opacity duration-150 ${
                  isGenerating ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                }`}
              >
                <Button size="md" variant="secondary" onClick={handleGenerate} disabled={isGenerating}>
                  {isGenerating ? (queueState === "queued" ? "QUEUED" : "GENERATING…") : "REGENERATE"}
                </Button>
                {isGenerating && (
                  <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/70">
                    {queueState === "queued" ? "WAITING FOR GENERATOR" : "SAMPLE IN PROGRESS"}
                  </div>
                )}
              </div>
            </>
          )}
          {suggestion.is_active && (
            <Tag className="absolute right-2 top-2 bg-archive-sage text-bristol">
              ACTIVE
            </Tag>
          )}
        </div>
        <div className="p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black">
              {suggestion.label}
            </div>
            <div className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/45 shrink-0">
              #{suggestion.index}
            </div>
          </div>
          <p className="mt-2 font-body text-[0.78rem] leading-relaxed text-ink-black/70 line-clamp-4">
            {suggestion.template}
          </p>
          <div className="mt-3 flex gap-2">
            {!suggestion.is_active && (
              <Button size="xs" variant="primary" onClick={() => setActive.mutate({ project: projectName, index: suggestion.index })}>
                SELECT
              </Button>
            )}
            {!imgFailed && (
              <Button size="xs" variant="secondary" onClick={handleGenerate} disabled={isGenerating}>
                {isGenerating ? (queueState === "queued" ? "QUEUED" : "GENERATING…") : "REGENERATE"}
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

export function StyleRoom() {
  const { name } = useParams<{ name: string }>();
  const projectName = name ?? "";
  const { data: stylesData, isLoading } = useStyles(name);
  const suggestStyles = useSuggestStyles();
  const generateSamples = useGenerateStyleSamples();
  const pendingSet = usePendingIndices(projectName);
  const styleJobIds = useStyleJobIds(projectName);
  const styleJobStatuses = useStyleJobStatuses(projectName);
  const { add, attachJobs, updateJob, remove } = useStyleGenStore();
  const { data: generationJobs } = useGenerationJobs(
    name,
    Object.values(styleJobIds),
  );

  useEffect(() => {
    if (!projectName || !generationJobs?.jobs.length) return;
    for (const job of generationJobs.jobs) {
      const index = Number(job.payload.index);
      if (!Number.isFinite(index)) continue;
      if (job.status === "complete" || job.status === "failed") remove(projectName, [index]);
      else updateJob(projectName, job);
    }
  }, [generationJobs, projectName, updateJob, remove]);

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

  function handleGenerateAll() {
    const indices = suggestions.map((s) => s.index);
    add(projectName, indices);
    generateSamples.mutate(
      { project: projectName, indices },
      {
        onSuccess: (data) => attachJobs(projectName, data.jobs),
        onError: () => remove(projectName, indices),
      },
    );
  }

  const anyGenerating = pendingSet.size > 0;
  const runningStyleCount = Object.values(styleJobStatuses).filter((status) => status === "running").length;
  const queuedStyleCount = Object.values(styleJobStatuses).filter((status) => status === "queued").length;

  return (
    <RoomShell>
      <ShowcaseHeader
        label="STYLES / VISUAL IDENTITY"
        title="LOOK & FEEL"
        lead="Pick the visual style that defines your comic. Generate samples to compare, then select one to lock it in."
        actions={
          <div className="flex gap-2">
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
              onClick={() => suggestStyles.mutate({ project: name })}
              disabled={suggestStyles.isPending}
            >
              {suggestStyles.isPending ? "GENERATING…" : "REFRESH SUGGESTIONS"}
            </Button>
          </div>
        }
      />

      {suggestions.length === 0 ? (
        <Card className="p-8 text-center">
          <div className="font-display text-[1.2rem] font-bold text-ink-black/60">
            NO STYLE SUGGESTIONS YET
          </div>
          <div className="mt-2 font-meta text-[0.52rem] tracking-[0.16em] text-ink-black/45">
            CLICK "REFRESH SUGGESTIONS" TO GENERATE 5 OPTIONS
          </div>
        </Card>
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
            />
          ))}
        </section>
      )}
    </RoomShell>
  );
}
