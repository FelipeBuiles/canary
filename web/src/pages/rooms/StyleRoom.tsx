import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
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
} from "../../api/queries";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import { Button } from "../../components/ui/Button";
import { GenerationDetailsModal } from "../../components/ui/GenerationDetailsModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StateBlock } from "../../components/ui/StateBlock";
import { Surface } from "../../components/ui/Surface";
import { EntityCard, RoomHeader, ConfirmDrawer, RoomShell } from "../../components/composites";
import { useI18n } from "../../i18n";
import { FlowingDotsPlaceholder } from "../../components/ui/FlowingDotsPlaceholder";
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

  return (
    <>
      <EntityCard
        active={isActive}
        className="min-h-[520px]"
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
              </div>
            )}

            {isActive && (
              <div className="absolute left-5 top-5 bg-hero-red px-4 py-2 font-meta text-[0.68rem] tracking-[0.18em] text-bristol">
                {t("ACTIVE")}
              </div>
            )}

            <button
              type="button"
              onClick={handleGenerate}
              disabled={isGenerating || actionsDisabled}
              title={suggestion.has_sample ? "Regenerar muestra" : "Generar muestra"}
              className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center bg-ink-black/55 text-bristol transition-colors hover:bg-ink-black disabled:opacity-40"
            >
              <span className="font-meta text-[0.78rem]">↺</span>
            </button>
          </div>
        }
      >
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
              ✓ SELECCIONADO
            </button>
          ) : (
            <button
              type="button"
              className="inline-flex min-h-14 w-full items-center justify-center bg-hero-red px-5 py-3 font-meta text-[0.9rem] tracking-[0.18em] text-bristol transition-colors hover:bg-hero-red/90 disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => setActive.mutate({ project: projectName, index: suggestion.index })}
              disabled={isGenerating || actionsDisabled}
            >
              SELECCIONAR
            </button>
          )}
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
  const { isCompact, toggle } = useHeaderMode();
  const projectName = id ?? "";
  const { data: stylesData, isLoading, refetch: refetchStyles } = useStyles(id);
  const { data: projectConfig } = useProjectConfig(id);
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

  if (isLoading) {
    return <RoomShell isLoading loadingText="CARGANDO ESTILOS…" />;
  }

  if (!id) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="ESTILOS NO DISPONIBLES"
        emptyDescription="Seleccione un proyecto primero."
      />
    );
  }

  const suggestions = stylesData?.suggestions ?? [];

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
        kicker="ESTILOS"
        compact={isCompact}
        onToggle={toggle}
        title="APARIENCIA Y ESTILO"
        lead="Elija el estilo visual que define su cómic. Genere muestras para comparar y luego seleccione una para fijarla."
        actions={
          <div className="flex items-center gap-3">
            {anyGenerating && (
              <span className="font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/50">
                {runningStyleCount > 0 && `${runningStyleCount} EJECUTÁNDOSE`}{runningStyleCount > 0 && queuedStyleCount > 0 && " / "}{queuedStyleCount > 0 && `${queuedStyleCount} EN COLA`}
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
                  ? "SUGIRIENDO…"
                  : isStageGenerating
                    ? "GENERANDO…"
                    : "SUGERIR MÁS ESTILOS"}
              </Button>
              {suggestEstimate && suggestEstimate.estimate_credits > 0 && (
                <span className="font-meta text-[0.48rem] tracking-[0.14em] text-ink-black/45">
                  Est. {suggestEstimate.estimate_credits.toLocaleString()} créditos
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
                ? "FALLÓ LA SUGERENCIA DE ESTILO"
                : isStageGenerating
                  ? "GENERANDO OPCIONES DE ESTILO"
                  : "GENERANDO ESTILOS ADICIONALES"}
            </span>
          </div>
          <div className="mt-1 font-body text-[0.78rem] leading-relaxed">
            {suggestionStatus === "failed"
              ? suggestionError
              : "Pidiendo direcciones visuales al director de arte y renderizando una imagen de muestra por estilo. Las muestras aparecen a medida que se completan."}
          </div>
        </div>
      )}

      {suggestions.length === 0 ? (
        <Surface padding="lg">
          <StateBlock
            minHeight="min-h-[22vh]"
            title={isStageGenerating ? "GENERANDO OPCIONES DE ESTILO" : "AÚN NO HAY SUGERENCIAS DE ESTILO"}
            description={
              isStageGenerating
                ? "Cinco descripciones de estilo e imágenes de muestra están en camino."
                : "Apruebe la etapa de extracción para comenzar a generar opciones de estilo."
            }
            icon="styles"
          />
        </Surface>
      ) : (
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
      )}

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
