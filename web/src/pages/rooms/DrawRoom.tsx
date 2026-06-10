import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  useGenerationJobs,
  useImages,
  useProjectStatus,
  usePromptSummaries,
  usePromptsForScene,
  useStageEstimate,
  useProjectConfig,
  useUpdateProjectConfig,
  useRunPipeline,
  useResetStale,
} from "../../api/queries";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import { PanelCard } from "../../components/PanelCard";
import { PanelDetailModal } from "../../components/PanelDetailModal";
import { Surface } from "../../components/ui/Surface";
import {
  Toolbar,
  RoomTabs,
  type RoomTab,
  RoomHeader,
  RoomShell,
  StagePlaceholder,
  ConfirmDrawer,
} from "../../components/composites";
import { StyleCallout } from "../../components/wizard/StyleCallout";
import { useActiveRegens, useRegenStore } from "../../store/regen";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { getPanelDisplayState, getPanelFilterBucket, type PanelFilterBucket } from "../../lib/panelState";
import {
  useDrawProgressStore,
  useInFlightSet,
  useRecentFinishes,
} from "../../store/drawProgress";
import {
  PanelProgressDonut,
  StaleStripe,
  LiveProgressStrip,
  InFlightCard,
  RecentFinishesCard,
  BySceneCard,
  isAllInkedTransition,
  type SceneProgress,
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
      <select
        value={config.quality_preset ?? "balanced"}
        onChange={(e) => updateConfig({ project, data: { quality_preset: e.target.value as "fast" | "balanced" | "quality" } })}
        className="w-full border-[2px] border-ink-black/20 bg-bristol px-3 py-2 font-body text-[0.85rem] text-ink-black focus:border-ink-black focus:outline-none"
      >
        {QUALITY_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}

// ── DrawRoom ──────────────────────────────────────────────────────────────────

const FILTER_TABS: Array<{ key: PanelFilterBucket | "all"; label: string }> = [
  { key: "all", label: "ALL PANELS" },
  { key: "generated", label: "GENERATED" },
  { key: "pending", label: "PENDING" },
  { key: "failed", label: "FAILED" },
];

function panelImageUrl(project: string, img: Pick<ImageStatus, "scene_id" | "panel_number" | "image_revision">, bust?: number) {
  const baseUrl = `/api/projects/${encodeURIComponent(project)}/files/draw/${img.scene_id}/panel_${String(img.panel_number).padStart(3, "0")}.png`;
  const revision = bust ?? img.image_revision;
  return revision ? `${baseUrl}?v=${encodeURIComponent(String(revision))}` : baseUrl;
}

export function DrawRoom() {
  const { id } = useParams<{ id: string }>();
  const { isCompact, toggle } = useHeaderMode();
  const projectRegens = useActiveRegens(id ?? "");
  const bustTimestamps = useRegenStore((s) => s.bustTimestamps);
  const errors = useRegenStore((s) => s.errors);
  const updateJob = useRegenStore((s) => s.updateJob);
  const complete = useRegenStore((s) => s.complete);
  const fail = useRegenStore((s) => s.fail);

  const [statusFilter, setStatusFilter] = useState<PanelFilterBucket | "all">("all");
  const [sceneFilter, setSceneFilter] = useState<string | "all">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "list">(() => {
    try { return (localStorage.getItem("drawRoom.viewMode") as "grid" | "list") ?? "grid"; } catch { return "grid"; }
  });
  const [selectedPanel, setSelectedPanel] = useState<{ sceneId: string; panelNumber: number } | null>(null);
  const [confirmAction, setConfirmAction] = useState<"generate_all" | "retry_failed" | null>(null);
  const [retryFailedActive, setRetryFailedActive] = useState(false);

  const regeningKeys = Object.keys(projectRegens);
  const regenJobIds = Object.values(projectRegens)
    .map((r) => r.jobId)
    .filter((jobId): jobId is string => !!jobId);
  const { data: generationJobs } = useGenerationJobs(id, regenJobIds);
  const regenModes = new Map(
    regeningKeys.map((key) => [key, projectRegens[key]?.status ?? "queued"] as const),
  );
  const runningRegenCount = Object.values(projectRegens).filter((r) => r.status === "running").length;
  const queuedRegenCount = Object.values(projectRegens).filter((r) => r.status === "queued").length;

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

  // Subscriptions to drawProgress for live-cockpit + per-panel state.
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

  const { mutate: runPipeline, isPending: isPipelineRunning } = useRunPipeline();
  const { mutate: resetStale, isPending: isResetting } = useResetStale();
  const { data: drawEstimate } = useStageEstimate(id, "draw");

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
      fail(id, regen.key, "Generation job tracking was lost (server restart/interruption). Use Quick Re-Do.");
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
    let generated = 0, pending = 0, failed = 0;
    for (const img of allDisplayImages) {
      const state = getPanelDisplayState(img, panelInputsFor(img));
      const bucket = getPanelFilterBucket(state);
      if (bucket === "generated") generated++;
      else if (bucket === "pending") pending++;
      else if (bucket === "failed") failed++;
    }
    return { generated, pending, failed, total: allDisplayImages.length };
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

  const sceneProgress: SceneProgress[] = useMemo(() => {
    const acc = new Map<string, SceneProgress>();
    for (const img of allDisplayImages) {
      const sp = acc.get(img.scene_id) ?? { sceneId: img.scene_id, generated: 0, failed: 0, total: 0 };
      sp.total++;
      const state = getPanelDisplayState(img, panelInputsFor(img));
      const bucket = getPanelFilterBucket(state);
      if (bucket === "generated") sp.generated++;
      else if (bucket === "failed") sp.failed++;
      acc.set(img.scene_id, sp);
    }
    return Array.from(acc.values()).sort((a, b) => a.sceneId.localeCompare(b.sceneId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allDisplayImages, regenModes, isDrawRunning, retryFailedActive, inFlightSet]);

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

  function handleSetViewMode(mode: "grid" | "list") {
    setViewMode(mode);
    try { localStorage.setItem("drawRoom.viewMode", mode); } catch { /* localStorage may be unavailable */ }
  }

  function handleGenerateAllPending() {
    if (!id) return;
    runPipeline(
      { project: id, stage: "draw", rerun: false },
      {
        onError: (err) =>
          maybeShowInsufficientCredits(err, {
            actionLabel: "Run DRAW",
            onRetry: handleGenerateAllPending,
          }),
      },
    );
    setConfirmAction(null);
  }

  function handleRetryFailed() {
    if (!id) return;
    setRetryFailedActive(true);
    runPipeline(
      { project: id, stage: "draw", retryFailed: true },
      {
        onError: (err) => {
          setRetryFailedActive(false);
          maybeShowInsufficientCredits(err, {
            actionLabel: "Retry failed panels",
            onRetry: handleRetryFailed,
          });
        },
      },
    );
    setConfirmAction(null);
  }

  function handleResetStale() {
    if (!id) return;
    resetStale({ project: id });
  }

  function handleContinueStale() {
    if (!id) return;
    runPipeline(
      { project: id, stage: "draw", rerun: false },
      {
        onError: (err) =>
          maybeShowInsufficientCredits(err, {
            actionLabel: "Continue DRAW",
            onRetry: handleContinueStale,
          }),
      },
    );
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

  if ((!images?.length && !promptSummaries?.length && regeningKeys.length === 0) || !id) {
    return (
      <RoomShell>
        <StagePlaceholder
          stage="draw"
          status={drawStageStatus}
          itemsDone={generateStage?.items_done}
          itemsTotal={generateStage?.items_total}
        />
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
  const nextUnacceptedPanel = selectedPanelIndex >= 0
    ? displayImages
        .slice(selectedPanelIndex + 1)
        .find((img) => img.status === "done" && !img.accepted)
      ?? displayImages.find((img, idx) => idx !== selectedPanelIndex && img.status === "done" && !img.accepted)
    : null;
  const selectedPanelKey = selectedPanel ? `${selectedPanel.sceneId}-${selectedPanel.panelNumber}` : null;
  const selectedPanelBust = selectedPanelKey && id ? bustTimestamps[`${id}/${selectedPanelKey}`] : undefined;
  const selectedPanelImageUrl = selectedPanelImage
    ? panelImageUrl(id!, selectedPanelImage, selectedPanelBust)
    : "";

  const costForConfirm: StageCostEstimate | undefined = drawEstimate as StageCostEstimate | undefined;

  return (
    <RoomShell>
      <RoomHeader
        kicker="GENERATE PANELS"
        compact={isCompact}
        onToggle={toggle}
        title="GENERATE PANELS"
        lead="Review and generate final illustrated panels for your story."
      />
      <StyleCallout project={id} />

      <Toolbar>
        <RoomTabs
          ariaLabel="Panel status filter"
          tabs={FILTER_TABS.map(({ key, label }): RoomTab => ({
            key,
            label,
            count:
              key === "all" ? panelCounts.total
              : key === "generated" ? panelCounts.generated
              : key === "pending" ? panelCounts.pending
              : panelCounts.failed,
            active: statusFilter === key,
            onClick: () => setStatusFilter(key),
          }))}
        />

        <div className="flex flex-1 items-center gap-2 min-w-[16rem]">
          {scenes.length > 1 && (
            <select
              value={sceneFilter}
              onChange={(e) => setSceneFilter(e.target.value)}
              className="border-[2px] border-ink-black/20 bg-bristol px-3 py-2 font-body text-[0.78rem] text-ink-black focus:border-ink-black focus:outline-none"
            >
              <option value="all">All scenes</option>
              {scenes.map((s) => (
                <option key={s} value={s}>{s.replace(/_/g, " ").toUpperCase()}</option>
              ))}
            </select>
          )}
          <input
            type="search"
            placeholder="Search panels…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 border-[2px] border-ink-black/20 bg-bristol px-3 py-2 font-body text-[0.78rem] text-ink-black placeholder:text-ink-black/35 focus:border-ink-black focus:outline-none"
          />
          <div className="flex border-[2px] border-ink-black/20 overflow-hidden">
            {(["grid", "list"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => handleSetViewMode(mode)}
                className={`px-3 py-2 font-meta text-[0.6rem] tracking-[0.12em] transition-colors ${
                  viewMode === mode ? "bg-ink-black text-bristol" : "bg-bristol text-ink-black/50 hover:text-ink-black"
                }`}
              >
                {mode === "grid" ? "⊞" : "≡"}
              </button>
            ))}
          </div>
        </div>
      </Toolbar>

      <section className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_320px]">
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
                  accepted={!!img.accepted}
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
                  <span className={`shrink-0 inline-flex h-5 items-center px-2 font-meta text-[0.52rem] tracking-[0.1em] ${
                    state === "accepted" ? "bg-archive-sage text-bristol"
                    : state === "generated" || state === "regenerated" ? "bg-archive-sage/50 text-ink-black"
                    : state === "failed" ? "bg-hero-red text-bristol"
                    : state === "generating" ? "bg-narrator-gold text-ink-black animate-pulse"
                    : state === "queued" ? "bg-narrator-gold/30 text-ink-black"
                    : "bg-ink-black/15 text-ink-black"
                  }`}>
                    {state.toUpperCase()}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        <aside className="xl:sticky xl:top-4 xl:self-start space-y-5">
          {/* Panel progress card — donut + (when running) progress bar / ETA */}
          <Surface border="soft" shadow="none" padding="md">
            {isStageStuck && (
              <StaleStripe
                lastProgressAt={lastProgressAt}
                onContinue={handleContinueStale}
                onReset={handleResetStale}
                continuing={isPipelineRunning}
                resetting={isResetting}
              />
            )}
            <div className="mb-4 font-meta text-[0.58rem] tracking-[0.24em] text-ink-black/40">
              PANEL PROGRESS
            </div>
            <div className={allInked ? "animate-comic-pop" : undefined}>
              <PanelProgressDonut
                generated={panelCounts.generated}
                pending={panelCounts.pending}
                failed={panelCounts.failed}
                total={panelCounts.total}
              />
            </div>
            {allInked && (
              <div className="animate-comic-pop mt-4 inline-flex border-[2px] border-ink-black bg-narrator-gold px-3 py-1.5 font-meta text-[0.6rem] tracking-[0.18em] text-ink-black shadow-ink-sm">
                ALL PANELS INKED
              </div>
            )}
            {isDrawRunning && (
              <LiveProgressStrip
                itemsDone={generateStage?.items_done ?? 0}
                itemsTotal={generateStage?.items_total ?? panelCounts.total}
                project={id}
              />
            )}
            {(runningRegenCount > 0 || queuedRegenCount > 0) && (
              <div className="mt-3 font-meta text-[0.58rem] tracking-[0.12em] text-narrator-gold animate-pulse">
                {runningRegenCount > 0 && `${runningRegenCount} regenerating`}
                {runningRegenCount > 0 && queuedRegenCount > 0 && " · "}
                {queuedRegenCount > 0 && `${queuedRegenCount} queued`}
              </div>
            )}
          </Surface>

          {/* Live cockpit cards — only while running */}
          {isDrawRunning && <InFlightCard project={id} />}
          {isDrawRunning && <RecentFinishesCard project={id} />}

          <BySceneCard scenes={sceneProgress} defaultExpanded={!isDrawRunning} />

          {/* Actions — only when at rest */}
          {!isDrawRunning && (
            <div className="space-y-2">
              <button
                type="button"
                disabled={panelCounts.pending === 0 || isPipelineRunning}
                onClick={() => setConfirmAction("generate_all")}
                className="w-full border-[2px] border-ink-black bg-ink-black px-4 py-3 font-meta text-[0.62rem] tracking-[0.14em] text-bristol transition-colors hover:bg-ink-black/80 disabled:cursor-not-allowed disabled:opacity-40"
              >
                GENERATE ALL PENDING ({panelCounts.pending})
              </button>
              <button
                type="button"
                disabled={panelCounts.failed === 0 || isPipelineRunning}
                onClick={() => setConfirmAction("retry_failed")}
                className="w-full border-[2px] border-hero-red px-4 py-3 font-meta text-[0.62rem] tracking-[0.14em] text-hero-red transition-colors hover:bg-hero-red hover:text-bristol disabled:cursor-not-allowed disabled:opacity-40"
              >
                RETRY FAILED ({panelCounts.failed})
              </button>
            </div>
          )}
        </aside>
      </section>

      {selectedPanel && selectedPanelImage && id && (
        <PanelDetailModal
          isOpen={!!selectedPanel}
          onClose={() => setSelectedPanel(null)}
          onPrev={prevPanel ? () => setSelectedPanel({ sceneId: prevPanel.scene_id, panelNumber: prevPanel.panel_number }) : null}
          onNext={nextPanel ? () => setSelectedPanel({ sceneId: nextPanel.scene_id, panelNumber: nextPanel.panel_number }) : null}
          onNextUnaccepted={nextUnacceptedPanel ? () => setSelectedPanel({ sceneId: nextUnacceptedPanel.scene_id, panelNumber: nextUnacceptedPanel.panel_number }) : null}
          project={id}
          sceneId={selectedPanel.sceneId}
          panelNumber={selectedPanel.panelNumber}
          imageUrl={selectedPanelImageUrl}
          imageAvailable={selectedPanelImage.image_available ?? selectedPanelImage.status === "done"}
          status={selectedPanelImage.status}
          failureClassification={selectedPanelImage.failure_classification}
          errorMessage={selectedPanelImage.failure_message}
          errorDetail={selectedPanelImage.failure_detail}
          accepted={!!selectedPanelImage.accepted}
          versionCount={selectedPanelImage.version_count ?? 0}
        />
      )}

      <ConfirmDrawer
        open={confirmAction === "generate_all"}
        title="Generate All Pending"
        body={`This will generate ${panelCounts.pending} pending panel${panelCounts.pending === 1 ? "" : "s"}.`}
        cost={costForConfirm}
        extraBody={<QualityPresetField project={id} />}
        confirmLabel="Generate All Pending"
        onConfirm={handleGenerateAllPending}
        onClose={() => setConfirmAction(null)}
        busy={isPipelineRunning}
      />
      <ConfirmDrawer
        open={confirmAction === "retry_failed"}
        title="Retry Failed Panels"
        body={`This will retry ${panelCounts.failed} failed panel${panelCounts.failed === 1 ? "" : "s"}.`}
        cost={costForConfirm}
        extraBody={<QualityPresetField project={id} />}
        confirmLabel="Retry Failed"
        onConfirm={handleRetryFailed}
        onClose={() => setConfirmAction(null)}
        busy={isPipelineRunning}
      />
    </RoomShell>
  );
}
