import { useState, useEffect } from "react";
import type { ImagePrompt } from "../types/api";
import { PromptLineageCard } from "./PromptLineageCard";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";
import { GenerationDetailsModal } from "./ui/GenerationDetailsModal";
import { LazyImage } from "./ui/LazyImage";
import {
  useAcceptPanel,
  useCreditBalance,
  useImageGenerationMeta,
  usePanelImageVersions,
  useProjectConfig,
  usePromptsForScene,
  useRegenEstimate,
  useRegenPanel,
  useRegenPanelWithInstruction,
  useRestorePanelImageVersion,
  useUnacceptPanel,
  useUpdatePrompt,
} from "../api/queries";
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
  imageAvailable?: boolean;
  status?: "done" | "failed" | "pending" | "queued" | "running" | "stale";
  failureClassification?: string | null;
  errorMessage?: string | null;
  accepted?: boolean;
  versionCount?: number;
  onNextUnaccepted?: (() => void) | null;
}

function fileUrl(project: string, relativePath: string) {
  return `/api/projects/${encodeURIComponent(project)}/files/${relativePath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/")}`;
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
  imageAvailable = true,
  status,
  failureClassification,
  errorMessage,
  accepted = false,
  versionCount = 0,
  onNextUnaccepted,
}: PanelDetailModalProps) {
  const [draft, setDraft] = useState<ImagePrompt | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [footerMode, setFooterMode] = useState<"reviewing" | "writing" | "accepted">(
    accepted ? "accepted" : "reviewing",
  );
  const [pendingCreditAction, setPendingCreditAction] = useState<"quick" | "instruction" | "generate" | null>(null);
  const queryClient = useQueryClient();
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const bust = useRegenStore((s) => s.bust);
  const fail = useRegenStore((s) => s.fail);

  const { data: prompts } = usePromptsForScene(project, sceneId);
  const { data: projectConfig } = useProjectConfig(project);
  const originalPrompt = prompts?.find(
    (p) => p.scene_id === sceneId && p.panel_number === panelNumber
  );
  const panelRelPath = `draw/${sceneId}/panel_${String(panelNumber).padStart(3, "0")}.png`;
  const { data: generationMeta } = useImageGenerationMeta(project, panelRelPath, isDetailsOpen);
  const shouldLoadVersions = isOpen && versionCount > 0;
  const { data: versionData } = usePanelImageVersions(project, sceneId, panelNumber, shouldLoadVersions);

  const updatePrompt = useUpdatePrompt();
  const regenPanel = useRegenPanel();
  const instructedRegen = useRegenPanelWithInstruction();
  const restoreVersion = useRestorePanelImageVersion();
  const acceptPanel = useAcceptPanel();
  const unacceptPanel = useUnacceptPanel();
  const { data: creditBalance } = useCreditBalance();
  const { data: regenEstimate } = useRegenEstimate(project, sceneId, panelNumber, isOpen);
  const regenCredits = regenEstimate?.credits ?? "…";

  useEffect(() => {
    if (originalPrompt) {
      setDraft({ ...originalPrompt });
    }
  }, [originalPrompt]);

  useEffect(() => {
    setFooterMode(accepted ? "accepted" : "reviewing");
    setSelectedVersion(null);
  }, [accepted, sceneId, panelNumber]);

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

  const versionEntries = versionData?.versions ?? [];
  const hasVersionHistory = !!versionData?.has_history && versionEntries.some((version) => !version.current);
  const currentVersion = versionEntries.find((version) => version.current);
  const selectedVersionEntry = selectedVersion == null
    ? currentVersion
    : versionEntries.find((version) => version.version === selectedVersion) ?? currentVersion;
  const displayedImageUrl = selectedVersionEntry && !selectedVersionEntry.current
    ? fileUrl(project, selectedVersionEntry.image_path)
    : imageUrl;
  const displayedImageAvailable = selectedVersionEntry && !selectedVersionEntry.current
    ? true
    : imageAvailable;
  const versionLabel = hasVersionHistory && currentVersion
    ? `v${currentVersion.version} / ${versionEntries.length}`
    : null;

  const handleSave = (patch: Partial<ImagePrompt>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  const lowCredits = (creditBalance?.balance_credits ?? 0) < 20;

  function runCreditAction(action: "quick" | "instruction" | "generate") {
    if (lowCredits && pendingCreditAction !== action) {
      setPendingCreditAction(action);
      return;
    }
    setPendingCreditAction(null);
    if (action === "quick") handleQuickRedo();
    if (action === "instruction") handleInstructionRegen();
    if (action === "generate") void handleGenerate();
  }

  const handleQuickRedo = () => {
    const key = `${sceneId}-${panelNumber}`;
    begin(project, key);
    setFooterMode("reviewing");
    regenPanel.mutate(
      { project, sceneId, panelNumber },
      {
        onSuccess: (data) => attachJob(project, key, data.job),
        onError: (err) => fail(project, key, err instanceof Error ? err.message : "Regeneration failed"),
      }
    );
  };

  const handleInstructionRegen = () => {
    const trimmed = instruction.trim();
    if (!trimmed) {
      setInstructionError("Add a short visual instruction first.");
      return;
    }
    setInstructionError(null);
    const key = `${sceneId}-${panelNumber}`;
    begin(project, key);
    instructedRegen.mutate(
      { project, sceneId, panelNumber, instruction: trimmed },
      {
        onSuccess: (data) => {
          attachJob(project, key, data.job);
          queryClient.invalidateQueries({ queryKey: ["project", project, "direct", sceneId] });
          setInstruction("");
          setFooterMode("reviewing");
        },
        onError: (err) => {
          const message = err instanceof Error ? err.message : "Instruction regeneration failed";
          setInstructionError(message);
          fail(project, key, message);
        },
      },
    );
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
      setFooterMode("reviewing");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleAccept = () => {
    acceptPanel.mutate(
      { project, sceneId, panelNumber },
      { onSuccess: () => setFooterMode("accepted") },
    );
  };

  const handleUndoAccept = () => {
    unacceptPanel.mutate(
      { project, sceneId, panelNumber },
      { onSuccess: () => setFooterMode("reviewing") },
    );
  };

  const handleNextPanel = () => {
    const next = onNextUnaccepted ?? onNext;
    if (next) next();
    else onClose();
  };

  const handleRestoreVersion = () => {
    if (!selectedVersionEntry || selectedVersionEntry.current) return;
    const key = `${sceneId}-${panelNumber}`;
    restoreVersion.mutate(
      { project, sceneId, panelNumber, version: selectedVersionEntry.version },
      {
        onSuccess: () => {
          bust(project, key);
          setSelectedVersion(null);
          setFooterMode("reviewing");
        },
      },
    );
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
  const effectiveModel = projectConfig?.dev_mode && projectConfig?.image_model === "canary/image-primary"
    ? (projectConfig?.fallback_image_model || "canary/image-fast")
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
    style_template: projectConfig?.style_template ?? draft.style,
    subject_refs: draft.reference_image_paths,
    style_refs: [],
    continuity_note: draft.continuity_note,
  };
  const isFailed = status === "failed" || !!errorMessage || !!failureClassification;
  const isInstructionBusy = instructedRegen.isPending;
  const failureTitle = failureClassification === "provider_blocked"
    ? "PROVIDER BLOCKED"
    : "GENERATION FAILED";
  const failureMessage = errorMessage
    || (failureClassification === "provider_blocked"
      ? "The image provider blocked this panel. Edit the prompt and regenerate before composing."
      : "Image generation failed. Open Details for the raw model response, edit the prompt if needed, then regenerate.");

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
            <div className="flex h-full w-full flex-col gap-3">
              {isFailed && (
                <div className="border-[2px] border-hero-red bg-hero-red/8 p-3">
                  <div className="font-meta text-[0.58rem] tracking-[0.16em] text-hero-red">
                    {failureTitle}
                  </div>
                  <p className="mt-1 text-sm leading-6 text-ink-black/75">
                    {failureMessage}
                  </p>
                </div>
              )}
              <div className="flex min-h-0 flex-1 items-center justify-center bg-ink-black">
                {displayedImageAvailable ? (
                  <LazyImage
                    src={displayedImageUrl}
                    alt={`Panel ${panelNumber}`}
                    containerClassName="h-full w-full"
                    className="object-contain"
                  />
                ) : (
                  <div className="px-6 text-center font-meta text-[0.7rem] font-bold uppercase tracking-[0.18em] text-bristol/55">
                    No panel image generated
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="p-4 overflow-y-auto min-h-0">
            {hasVersionHistory && (
              <div className="mb-4 border-b-[2px] border-panel-line pb-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="font-meta text-[0.62rem] tracking-[0.22em] text-ink-black/48">
                    VERSION HISTORY
                  </div>
                  <div className="font-meta text-[0.62rem] font-bold tracking-[0.12em] text-ink-black/50">
                    {selectedVersionEntry
                      ? `v${selectedVersionEntry.version} of ${versionEntries.length}`
                      : versionLabel}
                  </div>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  {versionEntries.map((version) => {
                    const selected = selectedVersionEntry?.version === version.version;
                    return (
                      <button
                        key={`${version.version}-${version.image_path}`}
                        type="button"
                        onClick={() => setSelectedVersion(version.version)}
                        className={`group relative h-14 w-14 overflow-hidden border-[3px] transition-colors ${
                          selected
                            ? "border-hero-red"
                            : "border-pulp-paper shadow-[0_0_0_1px_var(--color-panel-line)] hover:border-ink-black/40"
                        }`}
                        title={version.current ? "Current version" : `Version ${version.version}`}
                      >
                        <img
                          src={fileUrl(project, version.image_path)}
                          alt={version.current ? "Current panel version" : `Panel version ${version.version}`}
                          className="h-full w-full object-cover"
                        />
                        {version.current && (
                          <span className="absolute bottom-0 right-0 bg-ink-black px-1.5 py-0.5 font-meta text-[0.46rem] font-bold text-bristol">
                            NOW
                          </span>
                        )}
                      </button>
                    );
                  })}
                  {selectedVersionEntry && !selectedVersionEntry.current && (
                    <Button
                      variant="outline"
                      className="ml-1 h-10"
                      onClick={handleRestoreVersion}
                      disabled={restoreVersion.isPending}
                    >
                      {restoreVersion.isPending ? "RESTORING..." : `RESTORE v${selectedVersionEntry.version}`}
                    </Button>
                  )}
                </div>
              </div>
            )}
            <PromptLineageCard
              prompt={draft}
              onSave={handleSave}
              mode="edit"
              showAdvanced
              project={project}
            />
          </div>
        </div>

        <div className="border-t-[2px] border-ink-black p-4">
          {pendingCreditAction ? (
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex min-h-12 flex-1 items-center gap-3 border-[2px] border-warn-orange bg-chip-gold px-4 font-body text-[0.9rem] font-bold text-warn-orange">
                <Icon name="alert" size={16} />
                Only {(creditBalance?.balance_credits ?? 0).toLocaleString()} credits remaining ·
                <a href="/credits" className="underline">Add credits</a>
              </div>
              <Button onClick={() => runCreditAction(pendingCreditAction)}>
                CONFIRM · {regenCredits} ◆
              </Button>
              <Button variant="outline" onClick={() => setPendingCreditAction(null)}>
                ✕
              </Button>
            </div>
          ) : footerMode === "writing" ? (
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-[18rem] flex-1">
                <textarea
                  value={instruction}
                  onChange={(event) => {
                    setInstruction(event.target.value);
                    if (instructionError) setInstructionError(null);
                  }}
                  maxLength={500}
                  rows={1}
                  className="min-h-14 w-full resize-none border-[3px] border-hero-red bg-bristol px-5 py-3 text-[1rem] font-semibold leading-7 text-ink-black outline-none"
                  placeholder="Describe what to fix..."
                />
                {instructionError && (
                  <p className="mt-2 text-sm leading-5 text-hero-red">
                    {instructionError}
                  </p>
                )}
              </div>
              <Button
                className="min-h-14 px-8"
                onClick={() => runCreditAction("instruction")}
                disabled={isInstructionBusy || !instruction.trim()}
              >
                {isInstructionBusy ? "APPLYING..." : `APPLY & REGEN · ${regenCredits} ◆`}
              </Button>
              <Button
                variant="outline"
                className="min-h-14"
                onClick={() => {
                  setFooterMode("reviewing");
                  setInstruction("");
                  setInstructionError(null);
                }}
              >
                CANCEL
              </Button>
            </div>
          ) : footerMode === "accepted" ? (
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex min-h-13 flex-1 items-center gap-3 bg-archive-sage px-5 font-meta text-[0.76rem] font-bold uppercase tracking-[0.18em] text-bristol">
                <Icon name="check" size={16} />
                Panel Accepted
                <span className="hidden font-body text-[0.82rem] normal-case tracking-normal text-bristol/70 sm:inline">
                  Locked into compose
                </span>
              </div>
              <Button variant="outline" onClick={handleUndoAccept} disabled={unacceptPanel.isPending}>
                ↩ Undo Accept
              </Button>
              <Button onClick={handleNextPanel}>
                Next Panel →
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <div className="mr-auto font-meta text-[0.7rem] font-bold tracking-[0.12em] text-ink-black/45">
                {versionLabel ? `${versionLabel} · ` : ""}{draft.width}×{draft.height}
              </div>
              <Button
                className="min-w-[14rem] flex-1 bg-archive-sage"
                onClick={handleAccept}
                disabled={acceptPanel.isPending || status !== "done"}
              >
                ✓ ACCEPT PANEL
              </Button>
              <Button
                variant="outline"
                className="min-w-[14rem] flex-1"
                onClick={() => setFooterMode("writing")}
              >
                FIX & REGENERATE...
              </Button>
              {hasChanges && (
                <Button onClick={() => runCreditAction("generate")} disabled={isGenerating}>
                  {isGenerating ? "SAVING..." : `GENERATE · ${regenCredits} ◆`}
                </Button>
              )}
              <Button variant="outline" onClick={() => runCreditAction("quick")}>
                ↺ RE-DO · {regenCredits} ◆
              </Button>
              <Button variant="outline" onClick={() => setIsDetailsOpen(true)}>
                DETAILS
              </Button>
              <Button variant="outline" onClick={onClose}>
                CLOSE
              </Button>
            </div>
          )}
        </div>
      </div>
      <GenerationDetailsModal
        isOpen={isDetailsOpen}
        onClose={() => setIsDetailsOpen(false)}
        title={`${sceneId.toUpperCase()} / PANEL ${String(panelNumber).padStart(2, "0")}`}
        imageUrl={imageUrl}
        imageAvailable={imageAvailable}
        prompt={generationMeta?.prompt ?? fallbackPromptWithContinuity}
        parameters={generationMeta?.parameters ?? fallbackParams}
        error={generationMeta?.error}
        classification={generationMeta?.classification}
        recoverable={generationMeta?.recoverable}
        userMessage={generationMeta?.user_message}
        recovery={generationMeta?.recovery}
        failedAt={generationMeta?.failed_at}
        isFallback={!generationMeta}
      />
    </div>
  );
}
