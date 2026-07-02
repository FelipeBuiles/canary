import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useGenerationJobs,
  useImages,
  useProjectStatus,
  usePromptSummaries,
  usePromptsForScene,
  useSetPanelFlag,
  useStageEstimate,
  useProjectConfig,
  useUpdateProjectConfig,
  useResetStale,
} from "../../api/queries";
import { useRunAction } from "../../hooks/useRunAction";
import { PanelCard } from "../../components/PanelCard";
import { Select } from "../../components/ui/Select";
import { PanelDetailModal } from "../../components/PanelDetailModal";
import {
  ApprovalBar,
  RoomHeader,
  RoomShell,
  StagePlaceholder,
  ConfirmDrawer,
} from "../../components/composites";
import { StyleCallout } from "../../components/wizard/StyleCallout";
import { useActiveRegens, useRegenStore } from "../../store/regen";
import { getPanelDisplayState, getPanelFilterBucket, type PanelFilterBucket } from "../../lib/panelState";
import {
  useDrawProgressStore,
  useInFlightSet,
  useRecentFinishes,
} from "../../store/drawProgress";
import {
  StaleStripe,
  isAllInkedTransition,
} from "../../components/draw/LiveCockpit";
import type { ImageStatus, StageCostEstimate } from "../../types/api";

// ── Quality preset (rendered inside ConfirmDrawer) ────────────────────────────

const QUALITY_OPTIONS: Array<{ value: "fast" | "balanced" | "quality"; label: string }> = [
  { value: "quality", label: "Quality" },
  { value: "balanced", label: "Balanced" },
  { value: "fast", label: "Fast" },
];

function QualityPresetField({ project }: { project: string }) {
  const { data: config } = useProjectConfig(project);
  const { mutate: updateConfig } = useUpdateProjectConfig();
  if (!config || config.quality_preset === undefined) return null;
  return (
    <div>
      <label className="mb-1 block font-meta text-[0.56rem] tracking-[0.18em] text-ink-black/45">
        GENERATION QUALITY
      </label>
      <Select
        aria-label="Generation quality"
        value={config.quality_preset ?? "balanced"}
        onValueChange={(value) => updateConfig({ project, data: { quality_preset: value as "fast" | "balanced" | "quality" } })}
        options={QUALITY_OPTIONS}
        className="w-full"
      />
    </div>
  );
}

// ── Status strip: ONE progress representation — a sentence and a thin bar ────

function StatusStrip({
  running,
  itemsDone,
  itemsTotal,
  generated,
  total,
  flagged,
  failed,
  allInked,
}: {
  running: boolean;
  itemsDone: number;
  itemsTotal: number;
  generated: number;
  total: number;
  flagged: number;
  failed: number;
  allInked: boolean;
}) {
  const pct = running
    ? (itemsTotal > 0 ? Math.round((itemsDone / itemsTotal) * 100) : 0)
    : (total > 0 ? Math.round((generated / total) * 100) : 0);
  const sentence = running
    ? `Drawing panel ${Math.min(itemsDone + 1, itemsTotal)}/${itemsTotal}…`
    : [
        `${generated}/${total} generated`,
        flagged > 0 ? `${flagged} flagged by you` : null,
        failed > 0 ? `${failed} failed` : null,
      ].filter(Boolean).join(" · ");

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <span className="font-body text-[0.9rem] font-bold text-ink-black">{sentence}</span>
        {allInked && (
          <span className="animate-comic-pop inline-flex border-[2px] border-ink-black bg-narrator-gold px-2.5 py-1 font-meta text-[0.56rem] tracking-[0.18em] text-ink-black shadow-ink-sm">
            ALL PANELS INKED
          </span>
        )}
      </div>
      <div className="h-[3px] w-full bg-ink-black/10">
        <div
          className={`h-full transition-[width] duration-300 ${running ? "bg-narrator-gold" : "bg-archive-sage"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── DrawRoom ──────────────────────────────────────────────────────────────────

function panelImageUrl(project: string, img: Pick<ImageStatus, "scene_id" | "panel_number" | "image_revision">, bust?: number) {
  const baseUrl = `/api/projects/${encodeURIComponent(project)}/files/draw/${img.scene_id}/panel_${String(img.panel_number).padStart(3, "0")}.png`;
  const revision = bust ?? img.image_revision;
  return revision ? `${baseUrl}?v=${encodeURIComponent(String(revision))}` : baseUrl;
}

export function DrawRoom() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const projectRegens = useActiveRegens(id ?? "");
  const bustTimestamps = useRegenStore((s) => s.bustTimestamps);
  const errors = useRegenStore((s) => s.errors);
  const updateJob = useRegenStore((s) => s.updateJob);
  const complete = useRegenStore((s) => s.complete);
  const fail = useRegenStore((s) => s.fail);

  const [statusFilter, setStatusFilter] = useState<PanelFilterBucket>("all");
  const [sceneFilter, setSceneFilter] = useState<string | "all">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "list">(() => {
    try { return (localStorage.getItem("drawRoom.viewMode") as "grid" | "list") ?? "grid"; } catch { return "grid"; }
  });
  const [selectedPanel, setSelectedPanel] = useState<{ sceneId: string; panelNumber: number } | null>(null);
  const [confirmAction, setConfirmAction] = useState<"draw_all" | "retry_failed" | null>(null);
  const [retryFailedActive, setRetryFailedActive] = useState(false);

  const regeningKeys = Object.keys(projectRegens);
  const regenJobIds = Object.values(projectRegens)
    .map((r) => r.jobId)
    .filter((jobId): jobId is string => !!jobId);
  const { data: generationJobs } = useGenerationJobs(id, regenJobIds);
  const regenModes = new Map(
    regeningKeys.map((key) => [key, projectRegens[key]?.status ?? "queued"] as const),
  );

  const { data: status } = useProjectStatus(id);
  const { data: images, isLoading } = useImages(
    id,
    regeningKeys.length > 0 || status?.stages?.draw?.status === "running" ? 2000 : undefined,
  );
  const { data: promptSummaries } = usePromptSummaries(id);

  const isDrawRunning = status?.stages?.draw?.status === "running";
  const activeSceneId = sceneFilter !== "all" ? sceneFilter : null;
  const { data: scenePrompts } = usePromptsForScene(id, activeSceneId);

  // Hydrate drawProgress in-flight from /status whenever it changes.
  // SSE owns updates after this; hydration covers fresh page loads.
  const drawStage = status?.stages?.draw;
  const hydrateDrawProgress = useDrawProgressStore((s) => s.hydrate);
  useEffect(() => {
    if (!id) return;
    hydrateDrawProgress(id, drawStage);
  }, [id, drawStage, hydrateDrawProgress]);

  const inFlightSet = useInFlightSet(id ?? "");
  const recentFinishes = useRecentFinishes(id ?? "");

  // Per-panel finishFlash: derive {key → most recent finish at} from store.
  const finishFlashByKey = useMemo(() => {
    const m = new Map<string, { at: number; status: "ok" | "failed" }>();
    for (const f of recentFinishes) {
      const k = `${f.sceneId}-${f.panelNumber}`;
      if (!m.has(k)) m.set(k, { at: f.finishedAt, status: f.status });
    }
    return m;
  }, [recentFinishes]);

  const promptDescByKey = useMemo(() => {
    if (!scenePrompts) return new Map<string, { title: string; description: string }>();
    const map = new Map<string, { title: string; description: string }>();
    for (const p of scenePrompts) {
      const key = `${p.scene_id}-${p.panel_number}`;
      const title = (p.setting ?? "").split("\n")[0].trim() || undefined;
      const description = p.composition ?? undefined;
      const firstSubject = p.subjects?.[0];
      const subjectDesc = firstSubject
        ? `${firstSubject.name ?? ""} — ${firstSubject.action ?? ""}`.trim().replace(/^—\s*/, "")
        : undefined;
      map.set(key, {
        title: title ?? `PANEL ${String(p.panel_number).padStart(2, "0")}`,
        description: subjectDesc ?? description ?? "",
      });
    }
    return map;
  }, [scenePrompts]);

  const { handleRun, isPending: isPipelineRunning } = useRunAction();
  const { mutate: resetStale, isPending: isResetting } = useResetStale();
  const approveStage = useApproveStage();
  const setPanelFlag = useSetPanelFlag();
  const { data: drawEstimate } = useStageEstimate(id, "draw");
  const { data: composeEstimate } = useStageEstimate(id, "compose");

  const generateStage = drawStage;
  const failedItems = generateStage?.items_failed ?? [];
  const isStageStuck = !!generateStage?.stale;
  const lastProgressAt = generateStage?.last_progress_at ?? null;

  const imageByKey = useMemo(
    () => new Map<string, ImageStatus>(
      (images ?? []).map((img) => [`${img.scene_id}-${img.panel_number}`, img] as const),
    ),
    [images],
  );

  const baseImages = (sceneFilter !== "all"
    ? images?.filter((img) => img.scene_id === sceneFilter)
    : images) ?? [];

  const allDisplayImages: ImageStatus[] = [...baseImages];

  for (const failedItem of failedItems) {
    const parts = failedItem.split("/");
    const sceneIdx = parts.findLastIndex((p) => /^scene_/.test(p));
    const failedSceneId = sceneIdx >= 0 ? parts[sceneIdx] : parts[0];
    const panelPart = sceneIdx >= 0 ? parts[sceneIdx + 1] : parts[1];
    const panelMatch = panelPart?.match(/panel_(\d+)/);
    if (!panelMatch || !failedSceneId) continue;
    const failedPanelNum = parseInt(panelMatch[1], 10);
    const alreadyPresent = allDisplayImages.some(
      (img) => img.scene_id === failedSceneId && img.panel_number === failedPanelNum,
    );
    if (!alreadyPresent && (sceneFilter === "all" || sceneFilter === failedSceneId)) {
      const synth: ImageStatus = {
        scene_id: failedSceneId, panel_number: failedPanelNum, status: "failed",
        image_available: false, accepted: false,
      };
      const idx = allDisplayImages.findIndex(
        (img) => img.scene_id > failedSceneId || (img.scene_id === failedSceneId && img.panel_number > failedPanelNum),
      );
      if (idx === -1) allDisplayImages.push(synth);
      else allDisplayImages.splice(idx, 0, synth);
    }
  }

  for (const summary of promptSummaries ?? []) {
    if (sceneFilter !== "all" && sceneFilter !== summary.scene_id) continue;
    for (let panelNum = 1; panelNum <= summary.prompt_count; panelNum++) {
      const alreadyPresent = allDisplayImages.some(
        (img) => img.scene_id === summary.scene_id && img.panel_number === panelNum,
      );
      if (!alreadyPresent) {
        const idx = allDisplayImages.findIndex(
          (img) => img.scene_id > summary.scene_id || (img.scene_id === summary.scene_id && img.panel_number > panelNum),
        );
        const synth: ImageStatus = {
          scene_id: summary.scene_id, panel_number: panelNum,
          status: "pending", image_available: false, accepted: false,
        };
        if (idx === -1) allDisplayImages.push(synth);
        else allDisplayImages.splice(idx, 0, synth);
      }
    }
  }

  for (const regeningKey of regeningKeys) {
    const lastDash = regeningKey.lastIndexOf("-");
    const regenSceneId = regeningKey.slice(0, lastDash);
    const regenPanelNum = parseInt(regeningKey.slice(lastDash + 1), 10);
    const alreadyPresent = allDisplayImages.some(
      (img) => img.scene_id === regenSceneId && img.panel_number === regenPanelNum,
    );
    if (!alreadyPresent && (sceneFilter === "all" || sceneFilter === regenSceneId)) {
      const synth: ImageStatus = {
        scene_id: regenSceneId, panel_number: regenPanelNum,
        status: "pending", image_available: false, accepted: false,
      };
      const idx = allDisplayImages.findIndex(
        (img) => img.scene_id > regenSceneId || (img.scene_id === regenSceneId && img.panel_number > regenPanelNum),
      );
      if (idx === -1) allDisplayImages.push(synth);
      else allDisplayImages.splice(idx, 0, synth);
    }
  }

  useEffect(() => {
    if (!id || !generationJobs?.jobs.length) return;
    const activeByJobId = new Map(
      Object.values(projectRegens)
        .filter((r) => r.jobId)
        .map((r) => [r.jobId, r] as const),
    );
    for (const job of generationJobs.jobs) {
      const regen = activeByJobId.get(job.id);
      if (!regen) continue;
      if (job.status === "complete") complete(id, regen.key);
      else if (job.status === "failed") fail(id, regen.key, job.error ?? "Regeneration failed");
      else updateJob(id, regen.key, job);
    }
  }, [generationJobs, projectRegens, id, updateJob, complete, fail]);

  useEffect(() => {
    if (!id || !generationJobs) return;
    const reportedIds = new Set(generationJobs.jobs.map((job) => job.id));
    for (const regen of Object.values(projectRegens)) {
      if (!regen.jobId || reportedIds.has(regen.jobId)) continue;
      const image = imageByKey.get(regen.key);
      if (image?.status === "done") { complete(id, regen.key); continue; }
      if (image?.status === "failed") { fail(id, regen.key, "Generation failed"); continue; }
      fail(id, regen.key, "Generation job tracking was lost (server restart/interruption). Re-roll the panel.");
    }
  }, [generationJobs, imageByKey, projectRegens, id, complete, fail]);

  const panelInputsFor = (img: ImageStatus) => {
    const key = `${img.scene_id}-${img.panel_number}`;
    return {
      inFlight: inFlightSet.has(key),
      queuedInRun: !!isDrawRunning
        && img.status === "pending"
        && !inFlightSet.has(key),
      regenMode: regenModes.get(key) ?? null,
      isRetryFailedRunning: retryFailedActive,
    };
  };

  const panelCounts = useMemo(() => {
    let generated = 0, pending = 0, failed = 0, flagged = 0;
    for (const img of allDisplayImages) {
      const state = getPanelDisplayState(img, panelInputsFor(img));
      const bucket = getPanelFilterBucket(state);
      if (bucket === "generated") generated++;
      else if (bucket === "flagged") { flagged++; generated++; }
      else if (bucket === "pending") pending++;
      else if (bucket === "failed") failed++;
    }
    return { generated, pending, failed, flagged, total: allDisplayImages.length };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allDisplayImages, regenModes, isDrawRunning, retryFailedActive, inFlightSet]);

  // One-shot "all panels inked" milestone — fires only on the transition into
  // a failure-free completion, never on remount of an already-complete stage.
  const [allInked, setAllInked] = useState(false);
  const prevGeneratedRef = useRef<number | null>(null);
  useEffect(() => {
    if (isAllInkedTransition(prevGeneratedRef.current, panelCounts)) {
      setAllInked(true);
    }
    prevGeneratedRef.current = panelCounts.generated;
  }, [panelCounts]);

  const displayImages = useMemo(() => {
    let filtered = allDisplayImages;
    if (statusFilter !== "all") {
      filtered = filtered.filter((img) => {
        const state = getPanelDisplayState(img, panelInputsFor(img));
        return getPanelFilterBucket(state) === statusFilter;
      });
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      filtered = filtered.filter(
        (img) =>
          img.scene_id.toLowerCase().includes(q) ||
          String(img.panel_number).includes(q),
      );
    }
    return filtered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allDisplayImages, statusFilter, searchQuery, regenModes, isDrawRunning, retryFailedActive, inFlightSet]);

  const flaggedImages = useMemo(
    () => allDisplayImages.filter((img) => img.status === "done" && img.flagged),
    [allDisplayImages],
  );

  const scenes = useMemo(
    () => [...new Set([...images?.map((img) => img.scene_id) ?? [], ...(promptSummaries?.map((s) => s.scene_id) ?? [])])],
    [images, promptSummaries],
  );

  const drawStageStatus = generateStage?.status ?? "pending";

  useEffect(() => {
    if (retryFailedActive && drawStageStatus !== "running" && !isPipelineRunning) {
      setRetryFailedActive(false);
    }
  }, [retryFailedActive, drawStageStatus, isPipelineRunning]);

  // Reset the flagged filter if it empties out (e.g. last flag removed).
  useEffect(() => {
    if (statusFilter === "flagged" && panelCounts.flagged === 0) setStatusFilter("all");
    if (statusFilter === "failed" && panelCounts.failed === 0) setStatusFilter("all");
  }, [statusFilter, panelCounts.flagged, panelCounts.failed]);

  function handleSetViewMode(mode: "grid" | "list") {
    setViewMode(mode);
    try { localStorage.setItem("drawRoom.viewMode", mode); } catch { /* localStorage may be unavailable */ }
  }

  function handleDrawAll() {
    if (!id) return;
    handleRun(id, "draw", { actionLabel: "Draw all panels" });
    setConfirmAction(null);
  }

  function handleRetryFailed() {
    if (!id) return;
    setRetryFailedActive(true);
    handleRun(id, "draw", {
      retryFailed: true,
      actionLabel: "Retry failed panels",
      onError: () => setRetryFailedActive(false),
    });
    setConfirmAction(null);
  }

  function handleResetStale() {
    if (!id) return;
    resetStale({ project: id });
  }

  function handleContinueStale() {
    if (!id) return;
    handleRun(id, "draw", { actionLabel: "Continue DRAW" });
  }

  function handleToggleFlag(img: ImageStatus) {
    if (!id) return;
    setPanelFlag.mutate({
      project: id,
      sceneId: img.scene_id,
      panelNumber: img.panel_number,
      flagged: !img.flagged,
    });
  }

  function handleAcceptAllContinue() {
    if (!id) return;
    if (drawStageStatus === "awaiting_review") {
      approveStage.mutate(
        { project: id, stage: "draw" },
        {
          onSuccess: () => {
            handleRun(id, "compose", { actionLabel: "Assemble book" });
            navigate(`/project/${id}/compose`);
          },
        },
      );
    } else {
      navigate(`/project/${id}/compose`);
    }
  }

  function handleReviewFlagged() {
    const first = flaggedImages[0];
    if (first) setSelectedPanel({ sceneId: first.scene_id, panelNumber: first.panel_number });
  }

  if (isLoading || ((!images?.length && !promptSummaries?.length) && drawStageStatus !== "pending")) {
    return (
      <RoomShell
        isLoading
        loadingText="LOADING PANEL GALLERY…"
        loadingStage="draw"
        loadingStageStatus={drawStageStatus}
        loadingStageItemsDone={generateStage?.items_done}
        loadingStageItemsTotal={generateStage?.items_total}
      />
    );
  }

  // Pre-generation: a short explainer and one way forward.
  const nothingGeneratedYet =
    (!images?.length && regeningKeys.length === 0) || !id;
  const upstreamReady = status?.stages?.direct?.status === "complete";
  if (nothingGeneratedYet) {
    return (
      <RoomShell>
        <StagePlaceholder
          stage="draw"
          status={drawStageStatus}
          itemsDone={generateStage?.items_done}
          itemsTotal={generateStage?.items_total}
        />
        {id && !isDrawRunning && upstreamReady && (
          <ApprovalBar
            next="Scenewright draws every planned panel in your selected style"
            estimateCredits={drawEstimate?.estimate_credits}
            primaryLabel="▶ DRAW ALL PANELS"
            onPrimary={() => setConfirmAction("draw_all")}
            primaryDisabled={isPipelineRunning}
            busy={isPipelineRunning}
          />
        )}
        {id && !isDrawRunning && !upstreamReady && (
          <ApprovalBar
            next="Waiting for shot plan and prompts — open SHOT PLAN above to retry"
            primaryLabel="▶ DRAW ALL PANELS"
            onPrimary={() => {}}
            primaryDisabled
          />
        )}
        {id && (
          <ConfirmDrawer
            open={confirmAction === "draw_all"}
            title="Draw all panels"
            body="Scenewright draws every planned panel in your selected style. You review by exception afterwards — flag anything that needs re-work."
            cost={drawEstimate as StageCostEstimate | undefined}
            extraBody={<QualityPresetField project={id} />}
            confirmLabel="Draw all panels"
            onConfirm={handleDrawAll}
            onClose={() => setConfirmAction(null)}
            busy={isPipelineRunning}
          />
        )}
      </RoomShell>
    );
  }

  const selectedPanelIndex = selectedPanel
    ? displayImages.findIndex(
        (img) => img.scene_id === selectedPanel.sceneId && img.panel_number === selectedPanel.panelNumber,
      )
    : -1;
  const selectedPanelImage = selectedPanelIndex >= 0 ? displayImages[selectedPanelIndex] : null;
  const prevPanel = selectedPanelIndex > 0 ? displayImages[selectedPanelIndex - 1] : null;
  const nextPanel = selectedPanelIndex >= 0 && selectedPanelIndex < displayImages.length - 1
    ? displayImages[selectedPanelIndex + 1]
    : null;
  const nextFlaggedPanel = selectedPanelIndex >= 0
    ? displayImages
        .slice(selectedPanelIndex + 1)
        .find((img) => img.status === "done" && img.flagged)
      ?? displayImages.find((img, idx) => idx !== selectedPanelIndex && img.status === "done" && img.flagged)
    : null;
  const selectedPanelKey = selectedPanel ? `${selectedPanel.sceneId}-${selectedPanel.panelNumber}` : null;
  const selectedPanelBust = selectedPanelKey && id ? bustTimestamps[`${id}/${selectedPanelKey}`] : undefined;
  const selectedPanelImageUrl = selectedPanelImage
    ? panelImageUrl(id!, selectedPanelImage, selectedPanelBust)
    : "";

  // Filter chips: All always; other chips only when their count is non-zero.
  const filterChips: Array<{ key: PanelFilterBucket; label: string; count: number }> = [
    { key: "all", label: "ALL", count: panelCounts.total },
    ...(panelCounts.flagged > 0 ? [{ key: "flagged" as const, label: "⚑ FLAGGED", count: panelCounts.flagged }] : []),
    ...(panelCounts.failed > 0 ? [{ key: "failed" as const, label: "FAILED", count: panelCounts.failed }] : []),
    ...(panelCounts.pending > 0 && panelCounts.pending < panelCounts.total
      ? [{ key: "pending" as const, label: "PENDING", count: panelCounts.pending }] : []),
  ];

  const drawApproved = drawStageStatus === "complete";

  const approvalBar = isDrawRunning ? (
    <ApprovalBar
      next="Scenewright is drawing your panels"
      note={`Drawing panel ${Math.min((generateStage?.items_done ?? 0) + 1, generateStage?.items_total ?? 0)}/${generateStage?.items_total ?? 0}…`}
      primaryLabel="DRAWING…"
      onPrimary={() => {}}
      primaryDisabled
    />
  ) : panelCounts.pending > 0 ? (
    <ApprovalBar
      next={panelCounts.generated > 0
        ? `Scenewright draws the ${panelCounts.pending} remaining panel${panelCounts.pending === 1 ? "" : "s"}`
        : "Scenewright draws every planned panel in your selected style"}
      estimateCredits={drawEstimate?.estimate_credits}
      primaryLabel="▶ DRAW ALL PANELS"
      onPrimary={() => setConfirmAction("draw_all")}
      primaryDisabled={isPipelineRunning}
      busy={isPipelineRunning}
      secondary={panelCounts.failed > 0 ? (
        <button
          type="button"
          onClick={() => setConfirmAction("retry_failed")}
          className="font-meta text-[0.62rem] tracking-[0.14em] text-hero-red transition-colors hover:underline"
        >
          ↺ RETRY {panelCounts.failed} FAILED
        </button>
      ) : undefined}
    />
  ) : panelCounts.failed > 0 ? (
    <ApprovalBar
      next={`${panelCounts.failed} panel${panelCounts.failed === 1 ? "" : "s"} failed — retry before assembling the book`}
      estimateCredits={drawEstimate?.estimate_credits}
      primaryLabel={`↺ RETRY ${panelCounts.failed} FAILED`}
      onPrimary={() => setConfirmAction("retry_failed")}
      primaryDisabled={isPipelineRunning}
      busy={isPipelineRunning}
    />
  ) : (
    <ApprovalBar
      next={drawApproved ? "Letter and export your book" : "Scenewright assembles your comic-book pages"}
      estimateCredits={drawApproved ? null : composeEstimate?.estimate_credits}
      primaryLabel={drawApproved ? "GO TO BOOK →" : "ACCEPT ALL — CONTINUE →"}
      onPrimary={handleAcceptAllContinue}
      primaryDisabled={approveStage.isPending || isPipelineRunning}
      busy={approveStage.isPending}
      secondary={panelCounts.flagged > 0 ? (
        <button
          type="button"
          onClick={handleReviewFlagged}
          className="font-meta text-[0.62rem] tracking-[0.14em] text-hero-red transition-colors hover:underline"
        >
          ⚑ REVIEW {panelCounts.flagged} FLAGGED
        </button>
      ) : undefined}
    />
  );

  return (
    <RoomShell>
      <RoomHeader
        kicker="PANELS"
        title="DRAW PANELS"
        lead="Panels are accepted by default — flag the ones that need re-work."
      />
      <StyleCallout project={id} />

      {isStageStuck && (
        <StaleStripe
          lastProgressAt={lastProgressAt}
          onContinue={handleContinueStale}
          onReset={handleResetStale}
          continuing={isPipelineRunning}
          resetting={isResetting}
        />
      )}

      <StatusStrip
        running={!!isDrawRunning}
        itemsDone={generateStage?.items_done ?? 0}
        itemsTotal={generateStage?.items_total ?? panelCounts.total}
        generated={panelCounts.generated}
        total={panelCounts.total}
        flagged={panelCounts.flagged}
        failed={panelCounts.failed}
        allInked={allInked}
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5" role="tablist" aria-label="Panel filter">
          {filterChips.map(({ key, label, count }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={statusFilter === key}
              onClick={() => setStatusFilter(key)}
              className={`inline-flex h-8 items-center gap-1.5 border-[2px] px-3 font-meta text-[0.6rem] tracking-[0.12em] transition-colors ${
                statusFilter === key
                  ? key === "flagged" || key === "failed"
                    ? "border-hero-red bg-hero-red text-bristol"
                    : "border-ink-black bg-ink-black text-bristol"
                  : "border-ink-black/20 bg-bristol text-ink-black/60 hover:text-ink-black"
              }`}
            >
              {label} · {count}
            </button>
          ))}
        </div>

        <div className="flex w-full flex-1 items-center justify-end gap-2 sm:w-auto sm:min-w-[14rem]">
          {scenes.length > 1 && (
            <Select
              aria-label="Scene filter"
              size="sm"
              value={sceneFilter}
              onValueChange={setSceneFilter}
              className="shrink-0"
              options={[
                { value: "all", label: "All scenes" },
                ...scenes.map((s) => ({ value: s, label: s.replace(/_/g, " ").toUpperCase() })),
              ]}
            />
          )}
          <input
            type="search"
            placeholder="Search panels…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="min-w-0 flex-1 border-[2px] border-ink-black/20 bg-bristol px-3 py-1.5 font-body text-[0.78rem] text-ink-black placeholder:text-ink-black/35 focus:border-ink-black focus:outline-none sm:w-40 sm:flex-none"
          />
          <div className="flex border-[2px] border-ink-black/20 overflow-hidden">
            {(["grid", "list"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => handleSetViewMode(mode)}
                className={`px-3 py-1.5 font-meta text-[0.6rem] tracking-[0.12em] transition-colors ${
                  viewMode === mode ? "bg-ink-black text-bristol" : "bg-bristol text-ink-black/50 hover:text-ink-black"
                }`}
              >
                {mode === "grid" ? "⊞" : "≡"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <p className="font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/40">
        CLICK A PANEL TO OPEN IT · ⚑ TO FLAG FOR RE-WORK
      </p>

      {viewMode === "grid" ? (
        <div className="grid gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {displayImages.map((img) => {
            const key = `${img.scene_id}-${img.panel_number}`;
            const bust = id ? bustTimestamps[`${id}/${key}`] : undefined;
            const imageUrl = panelImageUrl(id!, img, bust);
            const regenError = id ? errors[`${id}/${key}`] : undefined;
            const prompts = promptDescByKey.get(key);
            const flash = finishFlashByKey.get(key) ?? null;
            const inputs = panelInputsFor(img);
            return (
              <PanelCard
                key={key}
                sceneId={img.scene_id}
                panelNumber={img.panel_number}
                status={img.status}
                imageUrl={imageUrl}
                imageAvailable={img.image_available ?? img.status === "done"}
                failureClassification={img.failure_classification}
                errorMessage={img.failure_message ?? undefined}
                flagged={!!img.flagged}
                onToggleFlag={() => handleToggleFlag(img)}
                versionCount={img.version_count}
                regenMode={inputs.regenMode}
                regenError={regenError}
                inFlight={inputs.inFlight}
                queuedInRun={inputs.queuedInRun}
                isRetryFailedRunning={retryFailedActive}
                finishFlashAt={flash?.at ?? null}
                finishFlashStatus={flash?.status ?? null}
                title={prompts?.title}
                description={prompts?.description}
                onPanelClick={() => setSelectedPanel({ sceneId: img.scene_id, panelNumber: img.panel_number })}
              />
            );
          })}
        </div>
      ) : (
        <div className="divide-y-[2px] divide-ink-black/10 border-[2px] border-ink-black/10">
          {displayImages.map((img) => {
            const key = `${img.scene_id}-${img.panel_number}`;
            const bust = id ? bustTimestamps[`${id}/${key}`] : undefined;
            const imageUrl = panelImageUrl(id!, img, bust);
            const state = getPanelDisplayState(img, panelInputsFor(img));
            const prompts = promptDescByKey.get(key);
            return (
              <div
                key={key}
                className="flex cursor-pointer items-center gap-4 px-4 py-3 hover:bg-bristol/60 transition-colors"
                onClick={() => setSelectedPanel({ sceneId: img.scene_id, panelNumber: img.panel_number })}
              >
                <div className="h-14 w-14 shrink-0 overflow-hidden bg-ink-black/10">
                  {img.image_available && (
                    <img src={imageUrl} alt={`Panel ${img.panel_number}`} className="h-full w-full object-cover" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="font-meta text-[0.52rem] tracking-[0.14em] text-ink-black/40">
                    {img.scene_id.replace(/_/g, " ").toUpperCase()} · PANEL {String(img.panel_number).padStart(2, "0")}
                  </div>
                  <div className="truncate font-body text-[0.82rem] font-semibold text-ink-black">
                    {prompts?.title ?? `Panel ${String(img.panel_number).padStart(2, "0")}`}
                  </div>
                </div>
                {img.status === "done" && (
                  <button
                    type="button"
                    aria-pressed={!!img.flagged}
                    title={img.flagged ? "Unflag" : "Flag for re-work"}
                    className={`shrink-0 inline-flex h-6 items-center px-1.5 font-meta text-[0.66rem] transition-colors ${
                      img.flagged ? "bg-hero-red text-bristol" : "text-ink-black/30 hover:text-hero-red"
                    }`}
                    onClick={(e) => { e.stopPropagation(); handleToggleFlag(img); }}
                  >
                    ⚑
                  </button>
                )}
                {(state === "failed" || state === "generating" || state === "queued" || state === "pending") && (
                  <span className={`shrink-0 inline-flex h-5 items-center px-2 font-meta text-[0.52rem] tracking-[0.1em] ${
                    state === "failed" ? "bg-hero-red text-bristol"
                    : state === "generating" ? "bg-narrator-gold text-ink-black animate-pulse"
                    : state === "queued" ? "bg-narrator-gold/30 text-ink-black"
                    : "bg-ink-black/15 text-ink-black"
                  }`}>
                    {state.toUpperCase()}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {selectedPanel && selectedPanelImage && id && (
        <PanelDetailModal
          isOpen={!!selectedPanel}
          onClose={() => setSelectedPanel(null)}
          onPrev={prevPanel ? () => setSelectedPanel({ sceneId: prevPanel.scene_id, panelNumber: prevPanel.panel_number }) : null}
          onNext={nextPanel ? () => setSelectedPanel({ sceneId: nextPanel.scene_id, panelNumber: nextPanel.panel_number }) : null}
          onNextFlagged={nextFlaggedPanel ? () => setSelectedPanel({ sceneId: nextFlaggedPanel.scene_id, panelNumber: nextFlaggedPanel.panel_number }) : null}
          project={id}
          sceneId={selectedPanel.sceneId}
          panelNumber={selectedPanel.panelNumber}
          imageUrl={selectedPanelImageUrl}
          imageAvailable={selectedPanelImage.image_available ?? selectedPanelImage.status === "done"}
          status={selectedPanelImage.status}
          failureClassification={selectedPanelImage.failure_classification}
          errorMessage={selectedPanelImage.failure_message}
          errorDetail={selectedPanelImage.failure_detail}
          flagged={!!selectedPanelImage.flagged}
          versionCount={selectedPanelImage.version_count ?? 0}
        />
      )}

      {approvalBar}

      <ConfirmDrawer
        open={confirmAction === "draw_all"}
        title="Draw all panels"
        body={`Scenewright draws ${panelCounts.pending} pending panel${panelCounts.pending === 1 ? "" : "s"} in your selected style.`}
        cost={drawEstimate as StageCostEstimate | undefined}
        extraBody={<QualityPresetField project={id} />}
        confirmLabel="Draw all panels"
        onConfirm={handleDrawAll}
        onClose={() => setConfirmAction(null)}
        busy={isPipelineRunning}
      />
      <ConfirmDrawer
        open={confirmAction === "retry_failed"}
        title="Retry failed panels"
        body={`This will retry ${panelCounts.failed} failed panel${panelCounts.failed === 1 ? "" : "s"}.`}
        cost={drawEstimate as StageCostEstimate | undefined}
        extraBody={<QualityPresetField project={id} />}
        confirmLabel="Retry failed"
        onConfirm={handleRetryFailed}
        onClose={() => setConfirmAction(null)}
        busy={isPipelineRunning}
      />
    </RoomShell>
  );
}
