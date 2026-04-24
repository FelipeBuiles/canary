import { useState, useEffect } from "react";
import type { ImagePrompt } from "../types/api";
import { PromptLineageCard } from "./PromptLineageCard";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";
import { GenerationDetailsModal } from "./ui/GenerationDetailsModal";
import { LazyImage } from "./ui/LazyImage";
import { useUpdatePrompt, useRegenPanel, usePromptsForScene, useImageGenerationMeta, useProjectConfig } from "../api/queries";
import { useRegenStore } from "../store/regen";
import { useQueryClient } from "@tanstack/react-query";

interface PanelDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  onPrev: (() => void) | null;
  onNext: (() => void) | null;
  project: string;
  sceneId: string;
  panelNumber: number;
  imageUrl: string;
}

export function PanelDetailModal({
  isOpen,
  onClose,
  onPrev,
  onNext,
  project,
  sceneId,
  panelNumber,
  imageUrl,
}: PanelDetailModalProps) {
  const [draft, setDraft] = useState<ImagePrompt | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const queryClient = useQueryClient();
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const fail = useRegenStore((s) => s.fail);

  const { data: prompts } = usePromptsForScene(project, sceneId);
  const { data: projectConfig } = useProjectConfig(project);
  const originalPrompt = prompts?.find(
    (p) => p.scene_id === sceneId && p.panel_number === panelNumber
  );
  const panelRelPath = `images/${sceneId}/panel_${String(panelNumber).padStart(3, "0")}.png`;
  const { data: generationMeta } = useImageGenerationMeta(project, panelRelPath, isDetailsOpen);

  const updatePrompt = useUpdatePrompt();
  const regenPanel = useRegenPanel();

  useEffect(() => {
    if (originalPrompt) {
      setDraft({ ...originalPrompt });
    }
  }, [originalPrompt]);

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft" && onPrev) onPrev();
      if (e.key === "ArrowRight" && onNext) onNext();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onPrev, onNext]);

  if (!isOpen || !draft) return null;

  const handleSave = (patch: Partial<ImagePrompt>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  const handleQuickRedo = () => {
    const key = `${sceneId}-${panelNumber}`;
    begin(project, key);
    regenPanel.mutate(
      { project, sceneId, panelNumber },
      {
        onSuccess: (data) => attachJob(project, key, data.job),
        onError: (err) => fail(project, key, err instanceof Error ? err.message : "Regeneration failed"),
      }
    );
    onClose();
  };

  const handleGenerate = async () => {
    if (!draft) return;
    setIsGenerating(true);
    try {
      await updatePrompt.mutateAsync({
        project,
        sceneId,
        data: draft,
      });
      queryClient.invalidateQueries({ queryKey: ["project", project, "direct", sceneId] });

      const key = `${sceneId}-${panelNumber}`;
      begin(project, key);
      regenPanel.mutate(
        { project, sceneId, panelNumber },
        {
          onSuccess: (data) => attachJob(project, key, data.job),
          onError: (err) => fail(project, key, err instanceof Error ? err.message : "Regeneration failed"),
        }
      );
      onClose();
    } finally {
      setIsGenerating(false);
    }
  };

  const hasChanges = draft && originalPrompt
    ? JSON.stringify(draft) !== JSON.stringify(originalPrompt)
    : false;
  const fallbackBody = (draft.full_prompt || "").trim();
  const fallbackStyle = (projectConfig?.style_template ?? draft.style ?? "").trim();
  const fallbackPrompt = (draft.prompt_version ?? 1) >= 2
    ? (fallbackStyle ? `${fallbackStyle}\n\n${fallbackBody}` : fallbackBody)
    : (fallbackStyle ? `${fallbackStyle}\n\n${draft.full_prompt}` : draft.full_prompt);
  const fallbackPromptWithContinuity = draft.continuity_note
    ? `${fallbackPrompt}\n\n${draft.continuity_note}`
    : fallbackPrompt;
  const effectiveModel = projectConfig?.dev_mode && projectConfig?.image_model === "gemini-3-pro-image-preview"
    ? (projectConfig?.fallback_image_model || "gemini-3.1-flash-image-preview")
    : projectConfig?.image_model;
  const effectiveSteps = projectConfig?.dev_mode
    ? Math.min(draft.steps, projectConfig?.dev_image_steps ?? draft.steps)
    : draft.steps;
  const fallbackParams: Record<string, unknown> = {
    scene_id: sceneId,
    panel_number: panelNumber,
    image_model: effectiveModel,
    width: draft.width,
    height: draft.height,
    steps: effectiveSteps,
    guidance_scale: draft.guidance_scale,
    style_template: projectConfig?.style_template ?? draft.style,
    subject_refs: draft.reference_image_paths,
    style_refs: [],
    continuity_note: draft.continuity_note,
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-[90vh] w-[95vw] max-w-[1400px] flex-col bg-bristol border-[4px] border-ink-black"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b-[2px] border-ink-black p-4 min-h-[4.5rem]">
          <div className="flex items-center gap-3">
            {onPrev ? (
              <button
                onClick={onPrev}
                className="p-2 text-ink-black/50 hover:text-hero-red transition-colors"
              >
                <Icon name="chevron-left" size={20} />
              </button>
            ) : (
              <span className="w-9" />
            )}
            <div>
              <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">
                {sceneId.toUpperCase()}
              </div>
              <div className="font-display text-[1.25rem] font-bold tracking-[-0.04em]">
                PANEL {String(panelNumber).padStart(2, "0")}
              </div>
            </div>
            {onNext ? (
              <button
                onClick={onNext}
                className="p-2 text-ink-black/50 hover:text-hero-red transition-colors"
              >
                <Icon name="chevron-right" size={20} />
              </button>
            ) : (
              <span className="w-9" />
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 text-ink-black/50 hover:text-hero-red transition-colors"
          >
            <Icon name="x" size={20} />
          </button>
        </div>

        <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[1fr_1fr]">
          <div className="border-r-[2px] border-ink-black p-4 min-h-0">
            <div className="h-full w-full bg-ink-black flex items-center justify-center">
              <LazyImage
                src={imageUrl}
                alt={`Panel ${panelNumber}`}
                containerClassName="h-full w-full"
                className="object-contain"
              />
            </div>
          </div>

          <div className="p-4 overflow-y-auto min-h-0">
            <PromptLineageCard
              prompt={draft}
              onSave={handleSave}
              mode="edit"
              showAdvanced
              project={project}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 border-t-[2px] border-ink-black p-4">
          <Button
            variant="outline"
            onClick={() => setIsDetailsOpen(true)}
          >
            DETAILS
          </Button>
          <Button
            variant="outline"
            onClick={handleQuickRedo}
          >
            QUICK RE-DO
          </Button>
          <Button
            onClick={handleGenerate}
            disabled={isGenerating || !hasChanges}
          >
            {isGenerating ? "SAVING…" : "GENERATE"}
          </Button>
          <Button
            variant="outline"
            onClick={onClose}
          >
            CLOSE
          </Button>
        </div>
      </div>
      <GenerationDetailsModal
        isOpen={isDetailsOpen}
        onClose={() => setIsDetailsOpen(false)}
        title={`${sceneId.toUpperCase()} / PANEL ${String(panelNumber).padStart(2, "0")}`}
        imageUrl={imageUrl}
        prompt={generationMeta?.prompt ?? fallbackPromptWithContinuity}
        parameters={generationMeta?.parameters ?? fallbackParams}
        isFallback={!generationMeta}
      />
    </div>
  );
}
