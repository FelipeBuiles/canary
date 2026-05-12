import { useState, useEffect, useRef } from "react";
import type { ImagePrompt } from "../types/api";
import { PromptLineageCard } from "./PromptLineageCard";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";
import { ConfirmDrawer } from "./ui/ConfirmDrawer";
import { LazyImage } from "./ui/LazyImage";
import {
  useAcceptPanel,
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
import { redactDevText, useShowDevContent } from "../lib/devContent";
import { useRegenStore } from "../store/regen";
import { maybeShowInsufficientCredits } from "../store/insufficientCredits";
import { useQueryClient } from "@tanstack/react-query";

type TabId = "review" | "edit" | "prompt";

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
  errorDetail?: string | null;
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

// ── Tab: Review ───────────────────────────────────────────────────────────────

function ReviewTabContent({
  project,
  sceneId,
  panelNumber,
  imageUrl,
  status,
  accepted,
  versionCount,
  onNextUnaccepted,
  onNext,
  onClose,
  regenCredits,
  creditsLabel,
  onQuickRedo,
  onGoToEdit,
  onDisplayUrlChange,
}: {
  project: string;
  sceneId: string;
  panelNumber: number;
  imageUrl: string;
  status?: string;
  accepted: boolean;
  versionCount: number;
  onNextUnaccepted?: (() => void) | null;
  onNext: (() => void) | null;
  onClose: () => void;
  regenCredits: number | null;
  creditsLabel: string;
  onQuickRedo: () => void;
  onGoToEdit: () => void;
  onDisplayUrlChange: (url: string) => void;
}) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [confirmRedo, setConfirmRedo] = useState(false);

  const shouldLoadVersions = versionCount > 0;
  const { data: versionData } = usePanelImageVersions(project, sceneId, panelNumber, shouldLoadVersions);
  const restoreVersion = useRestorePanelImageVersion();
  const acceptPanel = useAcceptPanel();
  const unacceptPanel = useUnacceptPanel();
  const bust = useRegenStore((s) => s.bust);
  const queryClient = useQueryClient();

  const versionEntries = versionData?.versions ?? [];
  const hasVersionHistory = !!versionData?.has_history && versionEntries.some((v) => !v.current);
  const currentVersion = versionEntries.find((v) => v.current);
  const selectedVersionEntry = selectedVersion == null
    ? currentVersion
    : versionEntries.find((v) => v.version === selectedVersion) ?? currentVersion;
  const displayedImageUrl = selectedVersionEntry && !selectedVersionEntry.current
    ? fileUrl(project, selectedVersionEntry.image_path)
    : imageUrl;

  useEffect(() => {
    onDisplayUrlChange(displayedImageUrl);
  }, [displayedImageUrl, onDisplayUrlChange]);

  const versionLabel = hasVersionHistory && currentVersion
    ? `v${currentVersion.version} / ${versionEntries.length}`
    : null;

  const handleAccept = () => {
    acceptPanel.mutate(
      { project, sceneId, panelNumber },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: ["project", project, "images"] });
        },
      },
    );
  };

  const handleUndoAccept = () => {
    unacceptPanel.mutate({ project, sceneId, panelNumber });
  };

  const handleNextPanel = () => {
    const next = onNextUnaccepted ?? onNext;
    if (next) next(); else onClose();
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
        },
      },
    );
  };

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      {hasVersionHistory && (
        <div className="border-b-[2px] border-panel-line pb-4">
          <div className="mb-2 flex items-center justify-between">
            <div className="font-meta text-[0.58rem] tracking-[0.2em] text-ink-black/45">VERSION HISTORY</div>
            <div className="font-meta text-[0.58rem] text-ink-black/45">{versionLabel}</div>
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
                    selected ? "border-hero-red" : "border-pulp-paper shadow-[0_0_0_1px_var(--color-panel-line)] hover:border-ink-black/40"
                  }`}
                  title={version.current ? "Current version" : `Version ${version.version}`}
                >
                  <img
                    src={fileUrl(project, version.image_path)}
                    alt={version.current ? "Current" : `v${version.version}`}
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
              <Button variant="outline" className="ml-1 h-10" onClick={handleRestoreVersion} disabled={restoreVersion.isPending}>
                {restoreVersion.isPending ? "RESTORING..." : `RESTORE v${selectedVersionEntry.version}`}
              </Button>
            )}
          </div>
          {selectedVersionEntry && !selectedVersionEntry.current && (
            <div className="mt-3 flex min-h-[240px] items-center justify-center bg-ink-black">
              <img
                src={displayedImageUrl}
                alt={`Version ${selectedVersionEntry.version}`}
                className="max-h-[240px] object-contain"
              />
            </div>
          )}
        </div>
      )}

      <div className="space-y-2">
        {accepted ? (
          <>
            <div className="flex items-center gap-3 bg-archive-sage px-4 py-3 font-meta text-[0.7rem] font-bold uppercase tracking-[0.16em] text-bristol">
              <Icon name="check" size={14} />
              Panel Accepted
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={handleUndoAccept} disabled={unacceptPanel.isPending}>
                ↩ Undo Accept
              </Button>
              <Button onClick={handleNextPanel}>Next Panel →</Button>
            </div>
          </>
        ) : (
          <>
            <Button
              className="w-full bg-archive-sage"
              onClick={handleAccept}
              disabled={acceptPanel.isPending || status !== "done"}
            >
              ✓ ACCEPT PANEL
            </Button>
            {onNextUnaccepted && (
              <Button variant="outline" className="w-full" onClick={onNextUnaccepted}>
                Next Unaccepted →
              </Button>
            )}
          </>
        )}
      </div>

      <div className="border-t-[2px] border-panel-line pt-3">
        <div className="font-meta text-[0.55rem] tracking-[0.18em] text-ink-black/40 mb-2">QUICK ACTIONS</div>
        <div className="space-y-2">
          <Button
            variant="outline"
            className="w-full"
            onClick={onGoToEdit}
          >
            FIX &amp; REGENERATE…
          </Button>
          <Button
            variant="outline"
            className="w-full"
            onClick={() => setConfirmRedo(true)}
            disabled={status !== "done" && status !== "failed"}
          >
            ↺ Quick Re-Do · {creditsLabel}
          </Button>
        </div>
      </div>

      <ConfirmDrawer
        open={confirmRedo}
        title="Quick Re-Do"
        body="Regenerate this panel with the same prompt. The current image will be archived."
        cost={regenCredits != null ? { estimate_credits: regenCredits, reserved_credits: null, reservation_multiplier: 1, confidence: "low_variance" } : undefined}
        confirmLabel={`Re-Do · ${creditsLabel}`}
        onConfirm={() => { setConfirmRedo(false); onQuickRedo(); }}
        onClose={() => setConfirmRedo(false)}
      />
    </div>
  );
}

// ── Tab: Edit ─────────────────────────────────────────────────────────────────

function EditTabContent({
  project,
  sceneId,
  panelNumber,
  draft,
  originalPrompt,
  onDraftChange,
  regenCredits,
  creditsLabel,
  lastRewrittenPrompt,
  onInstructionRegen,
  onGenerateFromDraft,
  starterInstruction,
  onStarterConsumed,
}: {
  project: string;
  sceneId: string;
  panelNumber: number;
  draft: ImagePrompt;
  originalPrompt: ImagePrompt | undefined;
  onDraftChange: (patch: Partial<ImagePrompt>) => void;
  regenCredits: number | null;
  creditsLabel: string;
  lastRewrittenPrompt: ImagePrompt | null;
  onInstructionRegen: (instruction: string) => void;
  onGenerateFromDraft: () => void;
  starterInstruction: string | null;
  onStarterConsumed: () => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const instructionTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (starterInstruction === null) return;
    setInstruction(starterInstruction);
    setInstructionError(null);
    onStarterConsumed();
    const node = instructionTextareaRef.current;
    if (node) {
      node.focus();
      const end = node.value.length;
      node.setSelectionRange(end, end);
    }
  }, [starterInstruction, onStarterConsumed]);
  const [confirmInstruction, setConfirmInstruction] = useState(false);
  const [confirmGenerate, setConfirmGenerate] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const instructedRegen = useRegenPanelWithInstruction();
  const updatePrompt = useUpdatePrompt();
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const fail = useRegenStore((s) => s.fail);
  const regenPanel = useRegenPanel();
  const queryClient = useQueryClient();

  const hasChanges = originalPrompt ? JSON.stringify(draft) !== JSON.stringify(originalPrompt) : false;
  const isInstructionBusy = instructedRegen.isPending;

  const handleInstructionRegen = () => {
    const trimmed = instruction.trim();
    if (!trimmed) { setInstructionError("Add a short visual instruction first."); return; }
    setInstructionError(null);
    onInstructionRegen(trimmed);
    setInstruction("");
    setConfirmInstruction(false);
  };

  const handleGenerateFromDraft = async () => {
    setIsGenerating(true);
    const key = `${sceneId}-${panelNumber}`;
    let startedRegen = false;
    try {
      await updatePrompt.mutateAsync({ project, sceneId, data: draft });
      queryClient.invalidateQueries({ queryKey: ["project", project, "direct", sceneId] });
      begin(project, key);
      startedRegen = true;
      const data = await regenPanel.mutateAsync({ project, sceneId, panelNumber });
      attachJob(project, key, data.job);
      onGenerateFromDraft();
    } catch (err) {
      if (
        maybeShowInsufficientCredits(err, {
          actionLabel: "Regenerate panel",
          onRetry: handleGenerateFromDraft,
        })
      ) {
        if (startedRegen) fail(project, key, err instanceof Error ? err.message : "Regeneration failed");
        return;
      }
      if (startedRegen) fail(project, key, err instanceof Error ? err.message : "Regeneration failed");
    } finally {
      setIsGenerating(false);
      setConfirmGenerate(false);
    }
  };

  const costObj = regenCredits != null
    ? { estimate_credits: regenCredits, reserved_credits: null as null, reservation_multiplier: 1, confidence: "low_variance" as const }
    : undefined;

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      {lastRewrittenPrompt && (
        <details className="border-[2px] border-archive-sage/40 bg-archive-sage/8">
          <summary className="cursor-pointer px-3 py-2 font-meta text-[0.58rem] tracking-[0.16em] text-archive-sage">
            REWRITTEN BY LAST REGEN ↓
          </summary>
          <div className="px-3 pb-3 pt-1 space-y-1 text-[0.72rem] text-ink-black/70">
            {lastRewrittenPrompt.setting && (
              <p><span className="font-semibold">Setting:</span> {lastRewrittenPrompt.setting}</p>
            )}
            {lastRewrittenPrompt.composition && (
              <p><span className="font-semibold">Composition:</span> {lastRewrittenPrompt.composition}</p>
            )}
          </div>
        </details>
      )}

      <div>
        <label className="mb-1.5 block font-meta text-[0.58rem] tracking-[0.18em] text-ink-black/45">
          NATURAL-LANGUAGE INSTRUCTION
        </label>
        <textarea
          ref={instructionTextareaRef}
          value={instruction}
          onChange={(e) => { setInstruction(e.target.value); if (instructionError) setInstructionError(null); }}
          maxLength={500}
          rows={2}
          className="w-full resize-none border-[2px] border-ink-black/25 bg-bristol px-3 py-2.5 font-body text-[0.9rem] leading-6 text-ink-black outline-none focus:border-ink-black"
          placeholder="Describe what to change visually…"
        />
        {instructionError && (
          <p className="mt-1 text-sm text-hero-red">{instructionError}</p>
        )}
        <Button
          className="mt-2 w-full"
          onClick={() => {
            const trimmed = instruction.trim();
            if (!trimmed) { setInstructionError("Add a short visual instruction first."); return; }
            setInstructionError(null);
            setConfirmInstruction(true);
          }}
          disabled={isInstructionBusy || !instruction.trim()}
        >
          {isInstructionBusy ? "APPLYING..." : `APPLY & REGEN · ${creditsLabel}`}
        </Button>
      </div>

      <div className="border-t-[2px] border-panel-line pt-3">
        <PromptLineageCard
          prompt={draft}
          onSave={onDraftChange}
          mode="edit"
          showAdvanced
          project={project}
        />
        {hasChanges && (
          <Button className="mt-3 w-full" onClick={() => setConfirmGenerate(true)} disabled={isGenerating}>
            {isGenerating ? "SAVING..." : `GENERATE FROM EDITS · ${creditsLabel}`}
          </Button>
        )}
      </div>

      <ConfirmDrawer
        open={confirmInstruction}
        title="Apply & Regenerate"
        body={`Regenerate this panel using your instruction. Instruction: "${instruction.trim()}"`}
        cost={costObj}
        confirmLabel={`Apply & Regen · ${creditsLabel}`}
        onConfirm={handleInstructionRegen}
        onClose={() => setConfirmInstruction(false)}
        busy={isInstructionBusy}
      />
      <ConfirmDrawer
        open={confirmGenerate}
        title="Generate from Edits"
        body="Save your prompt edits and regenerate this panel."
        cost={costObj}
        confirmLabel={`Generate · ${creditsLabel}`}
        onConfirm={handleGenerateFromDraft}
        onClose={() => setConfirmGenerate(false)}
        busy={isGenerating}
      />
    </div>
  );
}

// ── Tab: Prompt ───────────────────────────────────────────────────────────────

function PromptTabContent({
  prompt,
  projectConfig,
  lastRewrittenPrompt,
}: {
  prompt: ImagePrompt;
  projectConfig: import("../api/config").ProjectConfig | undefined;
  lastRewrittenPrompt: ImagePrompt | null;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const [showDevContent] = useShowDevContent();

  const rawPrompt = (prompt.full_prompt || "").trim();
  const style = (projectConfig?.style_template ?? prompt.style ?? "").trim();
  const fullPromptWithStyle = (prompt.prompt_version ?? 1) >= 2
    ? (style ? `${style}\n\n${rawPrompt}` : rawPrompt)
    : (style ? `${style}\n\n${prompt.full_prompt}` : prompt.full_prompt);
  const visibleRaw = showDevContent ? fullPromptWithStyle : redactDevText(fullPromptWithStyle);

  return (
    <div className="overflow-y-auto p-4 space-y-4">
      {lastRewrittenPrompt && (
        <div className="border-[2px] border-archive-sage/40 bg-archive-sage/8 px-3 py-2">
          <div className="font-meta text-[0.56rem] tracking-[0.14em] text-archive-sage">UPDATED BY LAST REGEN</div>
        </div>
      )}

      <div className="space-y-3">
        {(prompt.composition || (lastRewrittenPrompt?.composition)) && (
          <div>
            <div className="font-meta text-[0.54rem] tracking-[0.18em] text-ink-black/40 mb-1">COMPOSITION</div>
            <p className="text-[0.82rem] leading-6 text-ink-black">
              {lastRewrittenPrompt?.composition ?? prompt.composition}
            </p>
          </div>
        )}
        {(prompt.setting || lastRewrittenPrompt?.setting) && (
          <div>
            <div className="font-meta text-[0.54rem] tracking-[0.18em] text-ink-black/40 mb-1">SETTING</div>
            <p className="text-[0.82rem] leading-6 text-ink-black">
              {lastRewrittenPrompt?.setting ?? prompt.setting}
            </p>
          </div>
        )}
        {prompt.subjects && prompt.subjects.length > 0 && (
          <div>
            <div className="font-meta text-[0.54rem] tracking-[0.18em] text-ink-black/40 mb-1">SUBJECTS</div>
            <ul className="space-y-1">
              {prompt.subjects.map((s, i) => (
                <li key={i} className="text-[0.82rem] leading-6 text-ink-black">
                  <span className="font-semibold">{s.name}</span>
                  {s.action && <span className="text-ink-black/60"> — {s.action}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {prompt.style && (
          <div>
            <div className="font-meta text-[0.54rem] tracking-[0.18em] text-ink-black/40 mb-1">STYLE</div>
            <p className="text-[0.82rem] leading-6 text-ink-black">{prompt.style}</p>
          </div>
        )}
      </div>

      <div className="border-t-[2px] border-panel-line pt-3">
        <button
          type="button"
          onClick={() => setShowRaw(!showRaw)}
          className="flex items-center gap-2 font-meta text-[0.58rem] tracking-[0.16em] text-ink-black/45 hover:text-ink-black"
        >
          {showRaw ? "▲" : "▼"} ASSEMBLED PROMPT
        </button>
        {showRaw && (
          <pre className="mt-2 whitespace-pre-wrap border-[2px] border-ink-black/15 bg-bristol p-3 font-mono text-xs leading-relaxed text-ink-black">
            {visibleRaw}
          </pre>
        )}
      </div>
    </div>
  );
}

// ── PanelDetailModal ──────────────────────────────────────────────────────────

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "review", label: "Review" },
  { id: "edit", label: "Edit" },
  { id: "prompt", label: "Prompt" },
];

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
  errorDetail,
  accepted = false,
  versionCount = 0,
  onNextUnaccepted,
}: PanelDetailModalProps) {
  const [activeTab, setActiveTab] = useState<TabId>("review");
  const [editStarterInstruction, setEditStarterInstruction] = useState<string | null>(null);
  const [draft, setDraft] = useState<ImagePrompt | null>(null);
  const [lastRewrittenPrompt, setLastRewrittenPrompt] = useState<ImagePrompt | null>(null);
  const [activeDisplayUrl, setActiveDisplayUrl] = useState<string>(imageUrl);

  useEffect(() => {
    setActiveDisplayUrl(imageUrl);
  }, [imageUrl, sceneId, panelNumber]);
  const queryClient = useQueryClient();
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const fail = useRegenStore((s) => s.fail);

  const { data: prompts } = usePromptsForScene(project, sceneId);
  const { data: projectConfig } = useProjectConfig(project);
  const originalPrompt = prompts?.find((p) => p.scene_id === sceneId && p.panel_number === panelNumber);
  const { data: regenEstimate } = useRegenEstimate(project, sceneId, panelNumber, isOpen);
  const regenCredits: number | null = regenEstimate?.estimate_credits ?? null;
  const creditsLabel = regenCredits !== null ? `Est. ${regenCredits.toLocaleString()} credits` : "…";
  const regenPanel = useRegenPanel();
  const instructedRegen = useRegenPanelWithInstruction();

  useEffect(() => {
    if (originalPrompt) setDraft({ ...originalPrompt });
  }, [originalPrompt]);

  useEffect(() => {
    setLastRewrittenPrompt(null);
    setActiveTab(versionCount > 0 ? "review" : "review");
  }, [sceneId, panelNumber, versionCount]);

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowLeft" && onPrev) onPrev();
      if (e.key === "ArrowRight" && onNext) onNext();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onPrev, onNext, onClose]);

  if (!isOpen || !draft) return null;

  const isFailed = status === "failed" || !!errorMessage || !!failureClassification;
  const failureTitle = failureClassification === "provider_blocked" ? "PROVIDER BLOCKED" : "GENERATION FAILED";
  const failureMessage = errorMessage
    || (failureClassification === "provider_blocked"
      ? "The image provider blocked this panel. Edit the prompt and regenerate before composing."
      : "Image generation failed. Check Metadata for the raw model response, edit the prompt if needed.");
  const failureStarter = failureClassification === "provider_blocked"
    ? "The safety filter blocked this image — soften or remove the element it flagged (violence, gore, nudity, etc.) while keeping the panel's intent."
    : "";

  const handleFixWithPrompt = () => {
    setEditStarterInstruction(failureStarter);
    setActiveTab("edit");
  };

  const handleQuickRedo = async () => {
    const key = `${sceneId}-${panelNumber}`;
    begin(project, key);
    try {
      const data = await regenPanel.mutateAsync({ project, sceneId, panelNumber });
      attachJob(project, key, data.job);
      onClose();
    } catch (err) {
      if (
        maybeShowInsufficientCredits(err, {
          actionLabel: "Regenerate panel",
          onRetry: handleQuickRedo,
        })
      ) {
        fail(project, key, err instanceof Error ? err.message : "Regeneration failed");
        return;
      }
      fail(project, key, err instanceof Error ? err.message : "Regeneration failed");
    }
  };

  const handleInstructionRegen = async (instruction: string) => {
    const key = `${sceneId}-${panelNumber}`;
    begin(project, key);
    try {
      const data = await instructedRegen.mutateAsync({ project, sceneId, panelNumber, instruction });
      attachJob(project, key, data.job);
      setLastRewrittenPrompt(data.prompt);
      queryClient.invalidateQueries({ queryKey: ["project", project, "direct", sceneId] });
      onClose();
    } catch (err) {
      if (
        maybeShowInsufficientCredits(err, {
          actionLabel: "Regenerate panel",
          onRetry: () => handleInstructionRegen(instruction),
        })
      ) {
        fail(project, key, err instanceof Error ? err.message : "Instruction regeneration failed");
        return;
      }
      fail(project, key, err instanceof Error ? err.message : "Instruction regeneration failed");
    }
  };

  const handleDraftChange = (patch: Partial<ImagePrompt>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Panel ${String(panelNumber).padStart(2, "0")} — ${sceneId.toUpperCase()}`}
    >
      <div
        className="flex h-[90vh] w-[95vw] max-w-[1400px] flex-col bg-bristol border-[4px] border-ink-black"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b-[2px] border-ink-black p-4 min-h-[4.5rem]">
          <div className="flex items-center gap-3">
            {onPrev ? (
              <button onClick={onPrev} className="p-2 text-ink-black/50 hover:text-hero-red transition-colors">
                <Icon name="chevron-left" size={20} />
              </button>
            ) : (
              <span className="w-9" />
            )}
            <div>
              <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">{sceneId.toUpperCase()}</div>
              <div className="font-display text-[1.25rem] font-bold tracking-[-0.04em]">
                PANEL {String(panelNumber).padStart(2, "0")}
              </div>
            </div>
            {onNext ? (
              <button onClick={onNext} className="p-2 text-ink-black/50 hover:text-hero-red transition-colors">
                <Icon name="chevron-right" size={20} />
              </button>
            ) : (
              <span className="w-9" />
            )}
          </div>
          <button onClick={onClose} className="p-2 text-ink-black/50 hover:text-hero-red transition-colors">
            <Icon name="x" size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.8fr)]">
          {/* Left: image */}
          <div className="border-r-[2px] border-ink-black p-4 min-h-0">
            <div className="flex h-full w-full flex-col gap-3">
              {isFailed && (
                <div className="border-[2px] border-hero-red bg-hero-red/8 p-3">
                  <div className="font-meta text-[0.58rem] tracking-[0.16em] text-hero-red">{failureTitle}</div>
                  <p className="mt-1 text-sm leading-6 text-ink-black/75">{failureMessage}</p>
                  {errorDetail && (
                    <details className="mt-2">
                      <summary className="cursor-pointer font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55 hover:text-hero-red">
                        SHOW PROVIDER ERROR
                      </summary>
                      <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap break-words border-[1px] border-ink-black/15 bg-bristol/60 p-2 font-mono text-[0.7rem] leading-5 text-ink-black/70">
                        {errorDetail}
                      </pre>
                    </details>
                  )}
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={handleQuickRedo}
                      className="border-[2px] border-hero-red bg-bristol px-3 py-1.5 font-meta text-[0.58rem] tracking-[0.14em] text-hero-red transition-colors hover:bg-hero-red hover:text-bristol"
                    >
                      QUICK RE-DO · {creditsLabel}
                    </button>
                    <button
                      type="button"
                      onClick={handleFixWithPrompt}
                      className="border-[2px] border-ink-black bg-ink-black px-3 py-1.5 font-meta text-[0.58rem] tracking-[0.14em] text-bristol transition-colors hover:bg-ink-black/85"
                    >
                      FIX WITH PROMPT →
                    </button>
                  </div>
                </div>
              )}
              <div className="flex min-h-0 flex-1 items-center justify-center bg-ink-black">
                {imageAvailable ? (
                  <LazyImage
                    src={activeDisplayUrl}
                    alt={`Panel ${panelNumber}`}
                    containerClassName="h-full w-full"
                    preserveAspectBox
                  />
                ) : (
                  <div className="px-6 text-center font-meta text-[0.7rem] font-bold uppercase tracking-[0.18em] text-bristol/55">
                    No panel image generated
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Right: tabs */}
          <div className="flex min-h-0 flex-col">
            {/* Tab bar */}
            <div className="flex border-b-[2px] border-ink-black/15 overflow-x-auto shrink-0">
              {TABS.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActiveTab(id)}
                  className={`shrink-0 border-r-[2px] border-ink-black/10 px-5 py-3 font-meta text-[0.6rem] tracking-[0.14em] transition-colors last:border-r-0 ${
                    activeTab === id
                      ? "bg-ink-black text-bristol"
                      : "bg-bristol text-ink-black/50 hover:text-ink-black"
                  }`}
                >
                  {label.toUpperCase()}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="min-h-0 flex-1 overflow-hidden">
              {activeTab === "review" && (
                <ReviewTabContent
                  project={project}
                  sceneId={sceneId}
                  panelNumber={panelNumber}
                  imageUrl={imageUrl}
                  status={status}
                  accepted={accepted}
                  versionCount={versionCount}
                  onNextUnaccepted={onNextUnaccepted}
                  onNext={onNext}
                  onClose={onClose}
                  regenCredits={regenCredits}
                  creditsLabel={creditsLabel}
                  onQuickRedo={handleQuickRedo}
                  onGoToEdit={() => setActiveTab("edit")}
                  onDisplayUrlChange={setActiveDisplayUrl}
                />
              )}
              {activeTab === "edit" && (
                <EditTabContent
                  project={project}
                  sceneId={sceneId}
                  panelNumber={panelNumber}
                  draft={draft}
                  originalPrompt={originalPrompt}
                  onDraftChange={handleDraftChange}
                  regenCredits={regenCredits}
                  creditsLabel={creditsLabel}
                  lastRewrittenPrompt={lastRewrittenPrompt}
                  onInstructionRegen={handleInstructionRegen}
                  onGenerateFromDraft={onClose}
                  starterInstruction={editStarterInstruction}
                  onStarterConsumed={() => setEditStarterInstruction(null)}
                />
              )}
              {activeTab === "prompt" && (
                <PromptTabContent
                  prompt={draft}
                  projectConfig={projectConfig}
                  lastRewrittenPrompt={lastRewrittenPrompt}
                />
              )}

            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
