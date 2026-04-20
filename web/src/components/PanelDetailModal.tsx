import { useState, useEffect } from "react";
import type { ImagePrompt } from "../types/api";
import { PromptLineageCard } from "./PromptLineageCard";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";
import { useUpdatePrompt, useRegenPanel, usePromptsForScene } from "../api/queries";
import { useRegenStore } from "../store/regen";
import { useQueryClient } from "@tanstack/react-query";

interface PanelDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  project: string;
  sceneId: string;
  panelNumber: number;
  imageUrl: string;
}

export function PanelDetailModal({
  isOpen,
  onClose,
  project,
  sceneId,
  panelNumber,
  imageUrl,
}: PanelDetailModalProps) {
  const [draft, setDraft] = useState<ImagePrompt | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const queryClient = useQueryClient();
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const fail = useRegenStore((s) => s.fail);

  const { data: prompts } = usePromptsForScene(project, sceneId);
  const originalPrompt = prompts?.find(
    (p) => p.scene_id === sceneId && p.panel_number === panelNumber
  );

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
      queryClient.invalidateQueries({ queryKey: ["project", project, "prompts", sceneId] });

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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] max-w-[95vw] overflow-y-auto bg-bristol border-[4px] border-ink-black"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b-[2px] border-ink-black p-4">
          <div>
            <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">
              {sceneId.toUpperCase()}
            </div>
            <div className="font-display text-[1.25rem] font-bold tracking-[-0.04em]">
              PANEL {String(panelNumber).padStart(2, "0")}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-ink-black/50 hover:text-hero-red transition-colors"
          >
            <Icon name="x" size={20} />
          </button>
        </div>

        <div className="grid gap-0 lg:grid-cols-[1fr_1fr]">
          <div className="border-r-[2px] border-ink-black p-4">
            <img
              src={imageUrl}
              alt={`Panel ${panelNumber}`}
              className="w-full max-h-[60vh] object-contain bg-ink-black"
            />
          </div>

          <div className="p-4 overflow-y-auto max-h-[70vh]">
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
    </div>
  );
}
