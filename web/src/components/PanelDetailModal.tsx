import { useState, useEffect } from "react";
import type { CostEstimate, ImagePrompt } from "../types/api";
import { PromptLineageCard } from "./PromptLineageCard";
import { LayoutSection } from "./LayoutRegionEditor";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";
import { LazyImage } from "./ui/LazyImage";
import { ConfirmDrawer, RegenAction } from "./composites";
import {
  usePanelImageVersions,
  useGenerationRequest,
  useGenerationRequestPreview,
  usePrepareGenerationRequest,
  useProjectConfig,
  usePromptsForScene,
  useRegenEstimate,
  useRegenPanel,
  useRegenPanelWithInstruction,
  useRestorePanelImageVersion,
  useSetPanelFlag,
  useUpdatePrompt,
} from "../api/queries";
import { redactDevText, useShowDevContent } from "../lib/devContent";
import { useRegenStore } from "../store/regen";
import { maybeShowInsufficientCredits } from "../store/insufficientCredits";
import { useQueryClient } from "@tanstack/react-query";
import { Select } from "./ui/Select";
import { useI18n } from "../i18n";
import { getImageFailureCopy } from "../lib/imageFailure";
import { PanelRegenerationOverlay } from "./PanelRegenerationOverlay";

type TabId = "panel" | "prompt";
const DEFAULT_IMAGE_MODEL_ALIASES = ["image-fast", "image-balanced", "image-quality"];

// Authoritative editable prompt fields (must mirror the backend
// AUTHORITATIVE_PROMPT_FIELDS ∪ {subjects, layout} in panel_store.py). Only
// these are sent to the server; derived/protected fields are rebuilt server-side.
const AUTHORITATIVE_PROMPT_FIELDS = [
  "composition",
  "setting",
  "lighting",
  "mood",
  "constraints",
  "continuity_note",
  "props",
  "subjects",
  "layout",
] as const;

// Compute a patch of only the authoritative fields that changed between the
// original prompt and the draft. The server rejects derived/protected keys, so
// the client must never send them.
function diffAuthoritativeFields(
  original: ImagePrompt | undefined,
  draft: ImagePrompt,
): Partial<ImagePrompt> {
  if (!original) return {};
  const patch: Partial<ImagePrompt> = {};
  for (const key of AUTHORITATIVE_PROMPT_FIELDS) {
    const oldVal = original[key] as unknown;
    const newVal = draft[key] as unknown;
    if (JSON.stringify(oldVal) !== JSON.stringify(newVal)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (patch as any)[key] = newVal;
    }
  }
  return patch;
}

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
  flagged?: boolean;
  versionCount?: number;
  onNextFlagged?: (() => void) | null;
}

function fileUrl(project: string, relativePath: string) {
  return `/api/projects/${encodeURIComponent(project)}/files/${relativePath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/")}`;
}

function ImageModelAliasSelector({
  aliases,
  value,
  onChange,
}: {
  aliases: string[] | undefined;
  value: string;
  onChange: (value: string) => void;
}) {
  const options = aliases && aliases.length > 0 ? aliases : DEFAULT_IMAGE_MODEL_ALIASES;
  return (
    <div className="border-b-[2px] border-ink-black/15 bg-pulp-paper px-4 py-3">
      <label className="mb-1.5 block font-meta text-[0.54rem] tracking-[0.18em] text-ink-black/45">
        IMAGE MODEL
      </label>
      <Select
        aria-label="Image model"
        size="sm"
        value={value}
        onValueChange={onChange}
        options={[
          { value: "", label: "Project default" },
          ...options.map((alias) => ({ value: alias, label: alias })),
        ]}
        className="w-full"
      />
    </div>
  );
}

// ── Tab: Panel ────────────────────────────────────────────────────────────────
// The review surface: flag for re-work, re-roll, or describe a fix.

function PanelTabContent({
  project,
  sceneId,
  panelNumber,
  imageUrl,
  status,
  flagged,
  versionCount,
  prompt,
  onNextFlagged,
  regenCredits,
  instructionCost,
  onQuickRedo,
  onInstructionRegen,
  isRegenerating,
  onDisplayUrlChange,
}: {
  project: string;
  sceneId: string;
  panelNumber: number;
  imageUrl: string;
  status?: string;
  flagged: boolean;
  versionCount: number;
  prompt: ImagePrompt;
  onNextFlagged?: (() => void) | null;
  regenCredits: number | null;
  instructionCost?: CostEstimate;
  onQuickRedo: () => void;
  onInstructionRegen: (instruction: string) => void;
  isRegenerating: boolean;
  onDisplayUrlChange: (url: string) => void;
}) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  const shouldLoadVersions = versionCount > 0;
  const { data: versionData } = usePanelImageVersions(project, sceneId, panelNumber, shouldLoadVersions);
  const restoreVersion = useRestorePanelImageVersion();
  const setPanelFlag = useSetPanelFlag();
  const bust = useRegenStore((s) => s.bust);

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

  const handleToggleFlag = () => {
    setPanelFlag.mutate({ project, sceneId, panelNumber, flagged: !flagged });
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

  const costObj = regenCredits != null
    ? { estimate_credits: regenCredits, reserved_credits: null as null, reservation_multiplier: 1, confidence: "low_variance" as const }
    : undefined;

  // Shot summary: one human line about this panel.
  const shotSummary = [prompt.composition, prompt.setting?.split("\n")[0]]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(" — ");

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      {shotSummary && (
        <p className="text-[0.82rem] leading-6 text-ink-black/70">{shotSummary}</p>
      )}

      <div className="space-y-2">
        <Button
          className={`w-full ${flagged ? "" : "!bg-bristol !bg-none !text-hero-red !shadow-paper-sm border-hero-red"}`}
          onClick={handleToggleFlag}
          disabled={setPanelFlag.isPending || status !== "done"}
        >
          {flagged ? "⚑ FLAGGED FOR RE-WORK — UNFLAG" : "⚑ FLAG FOR RE-WORK"}
        </Button>
        {onNextFlagged && (
          <Button variant="outline" className="w-full" onClick={onNextFlagged}>
            Next flagged ⚑ →
          </Button>
        )}
      </div>

      <div className="border-t-[2px] border-panel-line pt-3">
        <RegenAction
          assetLabel={`Panel ${panelNumber}`}
          cost={costObj}
          instructionCost={instructionCost}
          busy={isRegenerating}
          disabled={status !== "done" && status !== "failed"}
          onRegenerate={onQuickRedo}
          onRegenerateWithInstruction={onInstructionRegen}
        />
      </div>

      {hasVersionHistory && (
        <div className="border-t-[2px] border-panel-line pt-3">
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
                {restoreVersion.isPending ? "RESTORING…" : `RESTORE v${selectedVersionEntry.version}`}
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

    </div>
  );
}

// ── Tab: Prompt ───────────────────────────────────────────────────────────────
// The structured Shot / Characters / Setting / Lighting breakdown — this is
// where prompt editing lives (it replaced the old Prompt Review stage).

function PromptTabContent({
  project,
  sceneId,
  panelNumber,
  imageUrl,
  draft,
  originalPrompt,
  onDraftChange,
  projectConfig,
  lastRewrittenPrompt,
  regenCredits,
  creditsLabel,
  imageModelAlias,
  onGenerateFromDraft,
}: {
  project: string;
  sceneId: string;
  panelNumber: number;
  imageUrl: string | null;
  draft: ImagePrompt;
  originalPrompt: ImagePrompt | undefined;
  onDraftChange: (patch: Partial<ImagePrompt>) => void;
  projectConfig: import("../api/config").ProjectConfig | undefined;
  lastRewrittenPrompt: ImagePrompt | null;
  regenCredits: number | null;
  creditsLabel: string;
  imageModelAlias: string | null;
  onGenerateFromDraft: () => void;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const [confirmGenerate, setConfirmGenerate] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [showDevContent] = useShowDevContent();
  const [preparedRequestId, setPreparedRequestId] = useState<string | null>(null);
  const [submittedRequestId, setSubmittedRequestId] = useState<string | null>(null);
  const requestPreview = useGenerationRequestPreview(
    project,
    sceneId,
    panelNumber,
    imageModelAlias,
    showDevContent,
    preparedRequestId,
    true,
  );
  const submittedRequest = useGenerationRequest(project, submittedRequestId, showDevContent);
  const prepareRequest = usePrepareGenerationRequest();
  const updatePrompt = useUpdatePrompt();
  const regenPanel = useRegenPanel();
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const fail = useRegenStore((s) => s.fail);
  const queryClient = useQueryClient();

  const hasChanges = originalPrompt ? JSON.stringify(draft) !== JSON.stringify(originalPrompt) : false;

  const rawPrompt = (draft.distilled_prompt || draft.full_prompt || "").trim();
  const style = (projectConfig?.style_template ?? draft.style ?? "").trim();
  const fullPromptWithStyle = (draft.prompt_version ?? 1) >= 2
    ? (style ? `${style}\n\n${rawPrompt}` : rawPrompt)
    : (style ? `${style}\n\n${draft.full_prompt}` : draft.full_prompt);
  const visibleRaw = showDevContent ? fullPromptWithStyle : redactDevText(fullPromptWithStyle);

  const handleGenerateFromDraft = async () => {
    setIsGenerating(true);
    const key = `${sceneId}-${panelNumber}`;
    let startedRegen = false;
    try {
      const fields = diffAuthoritativeFields(originalPrompt, draft);
      const requestId = fields && Object.keys(fields).length === 0 ? preparedRequestId : null;
      setPreparedRequestId(null);
      if (Object.keys(fields).length > 0) {
        await updatePrompt.mutateAsync({ project, sceneId, panelNumber, fields });
      }
      queryClient.invalidateQueries({ queryKey: ["project", project, "direct", sceneId] });
      begin(project, key);
      startedRegen = true;
      const data = await regenPanel.mutateAsync({ project, sceneId, panelNumber, imageModelAlias, preparedRequestId: requestId });
      attachJob(project, key, data.job);
      setSubmittedRequestId(data.request_id ?? data.job.payload.frozen_request_id as string | undefined ?? null);
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
        <div className="border-[2px] border-archive-sage/40 bg-archive-sage/8 px-3 py-2">
          <div className="font-meta text-[0.56rem] tracking-[0.14em] text-archive-sage">UPDATED BY LAST REGEN</div>
        </div>
      )}

      <PromptLineageCard
        prompt={draft}
        onSave={onDraftChange}
        mode="edit"
        showAdvanced={showDevContent}
        project={project}
      />
      <LayoutSection
        layout={draft.layout}
        imageUrl={imageUrl}
        aspectRatio={draft.width && draft.height ? draft.width / draft.height : 1.5}
        onChange={(layout) => onDraftChange({ layout })}
      />
      {(hasChanges || preparedRequestId) && (
        <Button className="w-full" onClick={() => setConfirmGenerate(true)} disabled={isGenerating}>
          {isGenerating ? "SAVING…" : `${hasChanges ? "Generate from edits" : "Generate prepared request"} · ${creditsLabel}`}
        </Button>
      )}

      {showDevContent && (
        <div className="border-t-[2px] border-panel-line pt-3">
          <div className="font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/45">REQUEST INSPECTION</div>
          <div className="mt-2 text-xs">
            <span className="font-semibold">{submittedRequest.data?.state_label ?? requestPreview.data?.state_label ?? "Draft projection"}</span>
            <span className="ml-2 text-ink-black/55">
              {(submittedRequest.data ?? requestPreview.data)?.exact ? "exact frozen request" : "free projection — not exact"}
            </span>
          </div>
          {!submittedRequest.data && !requestPreview.data?.exact && (
            <Button
              className="mt-3 w-full"
              variant="secondary"
              disabled={prepareRequest.isPending}
              onClick={() => prepareRequest.mutate(
                { project, sceneId, panelNumber, imageModelAlias },
                { onSuccess: (data) => setPreparedRequestId(data.request_id ?? null) },
              )}
            >
              {prepareRequest.isPending ? "PREPARING…" : "Prepare exact request (no image call)"}
            </Button>
          )}
          {(submittedRequest.data ?? requestPreview.data)?.accounting && (
            <p className="mt-2 text-[0.68rem] text-ink-black/55">
              Estimated on submit: ~{(submittedRequest.data ?? requestPreview.data)?.accounting?.estimated_credits} credits. Preparation does not reserve or spend credits.
            </p>
          )}
          {(submittedRequest.data ?? requestPreview.data)?.provider_wire && (
            <details className="mt-3">
              <summary className="cursor-pointer font-meta text-[0.54rem] tracking-[0.12em] text-ink-black/55">
                EXACT REQUEST & PROVENANCE
              </summary>
              <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap bg-bristol p-3 font-mono text-[0.65rem] leading-relaxed">
                {JSON.stringify({
                  semantic_prompt: (submittedRequest.data ?? requestPreview.data)?.semantic_prompt,
                  provider_wire: (submittedRequest.data ?? requestPreview.data)?.provider_wire,
                  references: (submittedRequest.data ?? requestPreview.data)?.references,
                  dropped_references: (submittedRequest.data ?? requestPreview.data)?.dropped_references,
                  geometry: (submittedRequest.data ?? requestPreview.data)?.geometry,
                  controls: (submittedRequest.data ?? requestPreview.data)?.controls,
                  provenance: (submittedRequest.data ?? requestPreview.data)?.provenance,
                }, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      {showDevContent && (
      <div className="border-t-[2px] border-panel-line pt-3">
        <button
          type="button"
          onClick={() => setShowRaw(!showRaw)}
          className="flex items-center gap-2 font-meta text-[0.58rem] tracking-[0.16em] text-ink-black/45 hover:text-ink-black"
        >
          {showRaw ? "▲" : "▼"} DRAFT PROMPT PROJECTION
        </button>
        <p className="mt-1 text-[0.68rem] text-ink-black/45">Free projection from the current edit; it is not the submitted wire request.</p>
        {showRaw && (
          <pre className="mt-2 whitespace-pre-wrap border-[2px] border-ink-black/15 bg-bristol p-3 font-mono text-xs leading-relaxed text-ink-black">
            {visibleRaw}
          </pre>
        )}
      </div>
      )}

      <ConfirmDrawer
        open={confirmGenerate}
        title="Generate from edits"
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

// ── PanelDetailModal ──────────────────────────────────────────────────────────

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "panel", label: "Review" },
  { id: "prompt", label: "Image brief" },
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
  flagged = false,
  versionCount = 0,
  onNextFlagged,
}: PanelDetailModalProps) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<TabId>("panel");
  const [draft, setDraft] = useState<ImagePrompt | null>(null);
  const [lastRewrittenPrompt, setLastRewrittenPrompt] = useState<ImagePrompt | null>(null);
  const [activeDisplayUrl, setActiveDisplayUrl] = useState<string>(imageUrl);
  const [imageModelAlias, setImageModelAlias] = useState("");
  const [previousPanelKey, setPreviousPanelKey] = useState(`${sceneId}-${panelNumber}`);
  const [previousImageUrl, setPreviousImageUrl] = useState(imageUrl);
  const [previousOriginalPrompt, setPreviousOriginalPrompt] = useState<ImagePrompt | undefined>();
  const [showDevContent] = useShowDevContent();
  const queryClient = useQueryClient();
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const fail = useRegenStore((s) => s.fail);

  const { data: prompts } = usePromptsForScene(project, sceneId);
  const { data: projectConfig } = useProjectConfig(project);
  const originalPrompt = prompts?.find((p) => p.scene_id === sceneId && p.panel_number === panelNumber);
  const selectedImageModelAlias = imageModelAlias || null;
  const { data: regenEstimate } = useRegenEstimate(project, sceneId, panelNumber, selectedImageModelAlias, isOpen);
  const regenCredits: number | null = regenEstimate?.estimate_credits ?? null;
  const creditsLabel = regenCredits !== null ? `~${regenCredits.toLocaleString()} credits` : "…";
  const regenPanel = useRegenPanel();
  const instructedRegen = useRegenPanelWithInstruction();
  const isPreparingRegeneration = regenPanel.isPending || instructedRegen.isPending;

  const panelKey = `${sceneId}-${panelNumber}`;
  if (previousPanelKey !== panelKey) {
    setPreviousPanelKey(panelKey);
    setLastRewrittenPrompt(null);
    setActiveTab("panel");
    setImageModelAlias("");
  }
  if (previousImageUrl !== imageUrl) {
    setPreviousImageUrl(imageUrl);
    setActiveDisplayUrl(imageUrl);
  }
  if (previousOriginalPrompt !== originalPrompt) {
    setPreviousOriginalPrompt(originalPrompt);
    setDraft(originalPrompt ? { ...originalPrompt } : null);
  }

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
      if (e.key === "Escape" && !document.querySelector('[role="alertdialog"]')) { onClose(); return; }
      if (e.key === "ArrowLeft" && onPrev) onPrev();
      if (e.key === "ArrowRight" && onNext) onNext();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onPrev, onNext, onClose]);

  if (!isOpen || !draft) return null;

  const isFailed = status === "failed" || !!errorMessage || !!failureClassification;
  const failureCopy = getImageFailureCopy(t, failureClassification, errorMessage);

  const handleQuickRedo = async () => {
    const key = `${sceneId}-${panelNumber}`;
    begin(project, key);
    try {
      const data = await regenPanel.mutateAsync({
        project,
        sceneId,
        panelNumber,
        imageModelAlias: selectedImageModelAlias,
      });
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
      const data = await instructedRegen.mutateAsync({
        project,
        sceneId,
        panelNumber,
        instruction,
        imageModelAlias: selectedImageModelAlias,
      });
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-4"
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
              <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">{sceneId.replace(/_/g, " ").toUpperCase()}</div>
              <div className="font-display text-[1.25rem] font-bold tracking-[-0.04em]">
                PANEL {String(panelNumber).padStart(2, "0")}
                {flagged && (
                  <span className="ml-3 inline-flex translate-y-[-2px] items-center bg-hero-red px-2 py-0.5 font-meta text-[0.5rem] tracking-[0.14em] text-bristol">
                    ⚑ RE-WORK
                  </span>
                )}
              </div>
            </div>
            {onNext ? (
              <button onClick={onNext} className="p-2 text-ink-black/50 hover:text-hero-red transition-colors">
                <Icon name="chevron-right" size={20} />
              </button>
            ) : (
              <span className="w-9" />
            )}
            {onNextFlagged && (
              <button
                onClick={onNextFlagged}
                className="ml-1 font-meta text-[0.56rem] tracking-[0.12em] text-hero-red transition-colors hover:underline"
              >
                NEXT FLAGGED ⚑
              </button>
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
                  <div className="font-meta text-[0.58rem] tracking-[0.16em] text-hero-red">{failureCopy.title}</div>
                  <p className="mt-1 text-sm leading-6 text-ink-black/75">{failureCopy.message}</p>
                  {showDevContent && errorDetail && (
                    <details className="mt-2">
                      <summary className="cursor-pointer font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55 hover:text-hero-red">
                        SHOW PROVIDER ERROR
                      </summary>
                      <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap break-words border-[1px] border-ink-black/15 bg-bristol/60 p-2 font-mono text-[0.7rem] leading-5 text-ink-black/70">
                        {errorDetail}
                      </pre>
                    </details>
                  )}
                  <p className="mt-2 font-meta text-[0.52rem] tracking-[0.12em] text-ink-black/50">
                    {t("Use the regeneration controls under Review to try again.")}
                  </p>
                </div>
              )}
              <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-ink-black">
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
                {isPreparingRegeneration && <PanelRegenerationOverlay phase="preparing" />}
              </div>
            </div>
          </div>

          {/* Right: tabs */}
          <div className="flex min-h-0 flex-col">
            {showDevContent && (
              <ImageModelAliasSelector
                aliases={projectConfig?.image_model_aliases}
                value={imageModelAlias}
                onChange={setImageModelAlias}
              />
            )}
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
                  {t(label).toUpperCase()}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="min-h-0 flex-1 overflow-hidden">
              {activeTab === "panel" && (
                <PanelTabContent
                  project={project}
                  sceneId={sceneId}
                  panelNumber={panelNumber}
                  imageUrl={imageUrl}
                  status={status}
                  flagged={flagged}
                  versionCount={versionCount}
                  prompt={draft}
                  onNextFlagged={onNextFlagged}
                  regenCredits={regenCredits}
                  instructionCost={regenEstimate?.instruction_estimate}
                  onQuickRedo={handleQuickRedo}
                  onInstructionRegen={handleInstructionRegen}
                  isRegenerating={isPreparingRegeneration}
                  onDisplayUrlChange={setActiveDisplayUrl}
                />
              )}
              {activeTab === "prompt" && (
                <PromptTabContent
                  project={project}
                  sceneId={sceneId}
                  panelNumber={panelNumber}
                  imageUrl={imageAvailable === false ? null : activeDisplayUrl}
                  draft={draft}
                  originalPrompt={originalPrompt}
                  onDraftChange={handleDraftChange}
                  projectConfig={projectConfig}
                  lastRewrittenPrompt={lastRewrittenPrompt}
                  regenCredits={regenCredits}
                  creditsLabel={creditsLabel}
                  imageModelAlias={selectedImageModelAlias}
                  onGenerateFromDraft={onClose}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
