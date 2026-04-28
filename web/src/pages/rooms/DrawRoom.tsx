import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useGenerationJobs, useImages, useProjectStatus, useRegenPanel, usePromptSummaries } from "../../api/queries";
import { RoomHeader } from "../../components/ui/RoomHeader";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import { PanelCard } from "../../components/PanelCard";
import { PanelDetailModal } from "../../components/PanelDetailModal";
import { StatRow } from "../../components/ui/StatRow";
import { RoomShell } from "../../components/ui/RoomShell";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { StyleCallout } from "../../components/wizard/StyleCallout";
import { useActiveRegens, useRegenStore } from "../../store/regen";
import type { ImageStatus } from "../../types/api";

export function DrawRoom() {
  const { name } = useParams<{ name: string }>();
  const { isCompact, toggle } = useHeaderMode();
  const projectRegens = useActiveRegens(name ?? "");
  const bustTimestamps = useRegenStore((s) => s.bustTimestamps);
  const errors = useRegenStore((s) => s.errors);
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const updateJob = useRegenStore((s) => s.updateJob);
  const complete = useRegenStore((s) => s.complete);
  const fail = useRegenStore((s) => s.fail);
  const [sceneFilter, setSceneFilter] = useState<string | null>(null);
  const [selectedPanel, setSelectedPanel] = useState<{ sceneId: string; panelNumber: number } | null>(null);

  const regeningKeys = Object.keys(projectRegens);
  const regenJobIds = Object.values(projectRegens)
    .map((regen) => regen.jobId)
    .filter((jobId): jobId is string => !!jobId);
  const { data: generationJobs } = useGenerationJobs(name, regenJobIds);
  const regenModes = new Map(
    regeningKeys.map((key) => [key, projectRegens[key]?.status ?? "queued"] as const),
  );
  const runningRegenCount = Object.values(projectRegens).filter((regen) => regen.status === "running").length;
  const queuedRegenCount = Object.values(projectRegens).filter((regen) => regen.status === "queued").length;

  const { data: status } = useProjectStatus(name);
  const { data: images, isLoading } = useImages(
    name,
    regeningKeys.length > 0 || status?.stages?.generate?.status === "running" ? 2000 : undefined,
  );
  const { data: promptSummaries } = usePromptSummaries(name);
  const { mutate: regen } = useRegenPanel();

  function handleRegen(sceneId: string, panelNumber: number) {
    if (!name) return;
    const key = `${sceneId}-${panelNumber}`;
    begin(name, key);
    regen(
      { project: name, sceneId, panelNumber },
      {
        onSuccess: (data) => attachJob(name, key, data.job),
        onError: (err) => {
          fail(name, key, err instanceof Error ? err.message : "Regeneration failed");
        },
      },
    );
  }

  useEffect(() => {
    if (!name || !generationJobs?.jobs.length) return;
    const activeByJobId = new Map(
      Object.values(projectRegens)
        .filter((regen) => regen.jobId)
        .map((regen) => [regen.jobId, regen] as const),
    );
    for (const job of generationJobs.jobs) {
      const regen = activeByJobId.get(job.id);
      if (!regen) continue;
      if (job.status === "complete") complete(name, regen.key);
      else if (job.status === "failed") fail(name, regen.key, job.error ?? "Regeneration failed");
      else updateJob(name, regen.key, job);
    }
  }, [generationJobs, projectRegens, name, updateJob, complete, fail]);

  const generateStage = status?.stages?.draw;
  const failedItems = generateStage?.items_failed ?? [];
  const isGenerateStale = generateStage?.status === "running" && generateStage.stale;
  const imageByKey = useMemo(
    () => new Map<string, ImageStatus>(
      (images ?? []).map((img) => [`${img.scene_id}-${img.panel_number}`, img] as const),
    ),
    [images],
  );

  const baseImages = (sceneFilter
    ? images?.filter((img) => img.scene_id === sceneFilter)
    : images) ?? [];

  // Keep the regen panel in the grid while its file is absent from disk.
  const displayImages: ImageStatus[] = [...baseImages];

  // Add failed panels that might not be in images yet.
  // items_failed may be short keys ("scene_001/panel_001") or legacy absolute paths.
  for (const failedItem of failedItems) {
    const parts = failedItem.split("/");
    // Absolute paths: find the scene_NNN segment and the panel_NNN segment after it
    const sceneIdx = parts.findLastIndex((p) => /^scene_/.test(p));
    const failedSceneId = sceneIdx >= 0 ? parts[sceneIdx] : parts[0];
    const panelPart = sceneIdx >= 0 ? parts[sceneIdx + 1] : parts[1];
    const panelMatch = panelPart?.match(/panel_(\d+)/);
    if (!panelMatch || !failedSceneId) continue;
    const failedPanelNum = parseInt(panelMatch[1], 10);
    const alreadyPresent = displayImages.some(
      (img) => img.scene_id === failedSceneId && img.panel_number === failedPanelNum,
    );
    if (!alreadyPresent && (!sceneFilter || sceneFilter === failedSceneId)) {
      const synth: ImageStatus = { scene_id: failedSceneId, panel_number: failedPanelNum, status: "failed" };
      const idx = displayImages.findIndex(
        (img) =>
          img.scene_id > failedSceneId ||
          (img.scene_id === failedSceneId && img.panel_number > failedPanelNum),
      );
      if (idx === -1) displayImages.push(synth);
      else displayImages.splice(idx, 0, synth);
    }
  }

  // Add pending placeholders for panels that haven't been generated yet
  const synthesizedStatus = (sceneId: string, panelNumber: number): ImageStatus["status"] => {
    const key = `${sceneId}-${panelNumber}`;
    const regenMode = regenModes.get(key);
    if (regenMode === "queued" || regenMode === "running") return "pending";
    const panelStem = `panel_${String(panelNumber).padStart(3, "0")}`;
    const failedKey = `${sceneId}/${panelStem}`;
    // items_failed may store short keys ("scene/panel_001") or legacy absolute paths
    if (failedItems.some((f) => f === failedKey || f.endsWith(`/${sceneId}/${panelStem}.json`))) return "failed";
    if (isGenerateStale) return "stale";
    // If the draw stage has finished but this panel has no image, it failed to generate
    const ds = generateStage?.status;
    if (ds === "awaiting_review" || ds === "complete" || ds === "failed") return "failed";
    return "pending";
  };

  for (const summary of promptSummaries ?? []) {
    if (sceneFilter && sceneFilter !== summary.scene_id) continue;
    for (let panelNum = 1; panelNum <= summary.prompt_count; panelNum++) {
      const alreadyPresent = displayImages.some(
        (img) => img.scene_id === summary.scene_id && img.panel_number === panelNum,
      );
      if (!alreadyPresent) {
        const idx = displayImages.findIndex(
          (img) =>
            img.scene_id > summary.scene_id ||
            (img.scene_id === summary.scene_id && img.panel_number > panelNum),
        );
        const synth: ImageStatus = {
          scene_id: summary.scene_id,
          panel_number: panelNum,
          status: synthesizedStatus(summary.scene_id, panelNum),
        };
        if (idx === -1) displayImages.push(synth);
        else displayImages.splice(idx, 0, synth);
      }
    }
  }

  for (const regeningKey of regeningKeys) {
    const lastDash = regeningKey.lastIndexOf("-");
    const regenSceneId = regeningKey.slice(0, lastDash);
    const regenPanelNum = parseInt(regeningKey.slice(lastDash + 1), 10);
    const alreadyPresent = displayImages.some(
      (img) => img.scene_id === regenSceneId && img.panel_number === regenPanelNum,
    );
    if (!alreadyPresent && (!sceneFilter || sceneFilter === regenSceneId)) {
      const synth: ImageStatus = {
        scene_id: regenSceneId,
        panel_number: regenPanelNum,
        status: synthesizedStatus(regenSceneId, regenPanelNum),
      };
      const idx = displayImages.findIndex(
        (img) =>
          img.scene_id > regenSceneId ||
          (img.scene_id === regenSceneId && img.panel_number > regenPanelNum),
      );
      if (idx === -1) displayImages.push(synth);
      else displayImages.splice(idx, 0, synth);
    }
  }

  useEffect(() => {
    if (!name || !generationJobs) return;
    const reportedIds = new Set(generationJobs.jobs.map((job) => job.id));
    for (const regen of Object.values(projectRegens)) {
      if (!regen.jobId || reportedIds.has(regen.jobId)) continue;
      const image = imageByKey.get(regen.key);
      if (image?.status === "done") {
        complete(name, regen.key);
        continue;
      }
      if (image?.status === "failed") {
        fail(name, regen.key, "Generation failed");
        continue;
      }
      fail(
        name,
        regen.key,
        "Generation job tracking was lost (server restart/interruption). Use Quick Re-Do.",
      );
    }
  }, [generationJobs, imageByKey, projectRegens, name, complete, fail]);

  const scenes = [...new Set([...images?.map((img) => img.scene_id) ?? [], ...(promptSummaries?.map((s) => s.scene_id) ?? [])])];

  const drawStageStatus = generateStage?.status ?? "pending";

  if (isLoading || ((!images?.length && !promptSummaries?.length) && drawStageStatus !== "pending")) {
    return <RoomShell isLoading loadingText="LOADING PANEL GALLERY…" />;
  }

  if ((!images?.length && !promptSummaries?.length && regeningKeys.length === 0) || !name) {
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
  const selectedPanelKey = selectedPanel
    ? `${selectedPanel.sceneId}-${selectedPanel.panelNumber}`
    : null;
  const selectedPanelBust = selectedPanelKey && name
    ? bustTimestamps[`${name}/${selectedPanelKey}`]
    : undefined;
  const selectedPanelBaseUrl = selectedPanel
    ? `/api/projects/${encodeURIComponent(name!)}/files/draw/${selectedPanel.sceneId}/panel_${String(selectedPanel.panelNumber).padStart(3, "0")}.png`
    : "";
  const selectedPanelImageUrl = selectedPanelBust
    ? `${selectedPanelBaseUrl}?t=${selectedPanelBust}`
    : selectedPanelBaseUrl;

  return (
    <RoomShell>
      <RoomHeader
        kicker="DRAW"
        compact={isCompact}
        onToggle={toggle}
        title="PANEL GALLERY"
        lead="Every generated panel at a glance — regenerate individual frames, review failures, switch scenes."
        actions={<RerunStageAction project={name} stage="draw" label="Draw" itemsAtRisk={`${images?.length ?? 0} generated panels will be lost`} />}
      />
      <StyleCallout project={name} />
      <div className="flex max-w-full overflow-x-auto" role="tablist" aria-label="Panel filters">
        <button
          type="button"
          role="tab"
          aria-selected={!sceneFilter}
          onClick={() => setSceneFilter(null)}
          className={`min-h-12 shrink-0 border-[2px] border-r-0 border-ink-black px-7 font-meta text-[0.7rem] tracking-[0.18em] transition-colors ${
            !sceneFilter
              ? "bg-ink-black text-bristol"
              : "bg-pulp-paper text-ink-black hover:bg-bristol"
          }`}
        >
          ALL
        </button>
        {scenes.map((sceneId) => (
          <button
            key={sceneId}
            type="button"
            role="tab"
            aria-selected={sceneFilter === sceneId}
            onClick={() => setSceneFilter(sceneId)}
            className={`min-h-12 shrink-0 border-[2px] border-r-0 border-ink-black px-8 font-meta text-[0.7rem] tracking-[0.18em] transition-colors last:border-r-[2px] ${
              sceneFilter === sceneId
                ? "bg-ink-black text-bristol"
                : "bg-pulp-paper text-ink-black hover:bg-bristol"
            }`}
          >
            {sceneId.replace("_", " ").toUpperCase()}
          </button>
        ))}
      </div>

      <section className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="grid gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {displayImages.map((img) => {
            const key = `${img.scene_id}-${img.panel_number}`;
            const bust = name ? bustTimestamps[`${name}/${key}`] : undefined;
            const baseUrl = `/api/projects/${encodeURIComponent(name!)}/files/draw/${img.scene_id}/panel_${String(img.panel_number).padStart(3, "0")}.png`;
            const imageUrl = bust ? `${baseUrl}?t=${bust}` : baseUrl;
            const isFailed = failedItems.includes(
              `${img.scene_id}/panel_${String(img.panel_number).padStart(3, "0")}`,
            );
            const regenError = name ? errors[`${name}/${key}`] : undefined;
            return (
              <PanelCard
                key={key}
                sceneId={img.scene_id}
                panelNumber={img.panel_number}
                status={isFailed ? "failed" : img.status}
                imageUrl={imageUrl}
                regenMode={regenModes.get(key) ?? null}
                regenError={regenError}
                onRegenerate={() => handleRegen(img.scene_id, img.panel_number)}
                onPanelClick={() => setSelectedPanel({ sceneId: img.scene_id, panelNumber: img.panel_number })}
              />
            );
          })}
        </div>

        <aside className="xl:sticky xl:top-4 xl:self-start">
          <div className="border-[2px] border-ink-black/10 bg-bristol p-6">
            <div className="mb-5 font-meta text-[0.62rem] tracking-[0.26em] text-ink-black/45">
              SESSION STATS
            </div>
            <div className="space-y-3">
              <StatRow label="TOTAL PANELS">{displayImages.length}</StatRow>
              <StatRow label="COMPLETED">{images?.filter((i) => i.status === "done").length ?? 0}</StatRow>
              <StatRow label="FAILED">{images?.filter((i) => i.status === "failed").length ?? 0}</StatRow>
              {status?.stages?.generate?.status === "running" && generateStage && (
                <StatRow label="GENERATING">
                  <span className="animate-pulse text-narrator-gold">
                    {generateStage.items_done}/{generateStage.items_total}
                  </span>
                </StatRow>
              )}
              {runningRegenCount > 0 && (
                <StatRow label="RUNNING">
                  <span className="animate-pulse text-narrator-gold">{runningRegenCount}</span>
                </StatRow>
              )}
              {queuedRegenCount > 0 && (
                <StatRow label="QUEUED">
                  <span className="text-narrator-gold">{queuedRegenCount}</span>
                </StatRow>
              )}
            </div>
          </div>
        </aside>
      </section>
      {selectedPanel && selectedPanelImage && name && (
        <PanelDetailModal
          isOpen={!!selectedPanel}
          onClose={() => setSelectedPanel(null)}
          onPrev={prevPanel ? () => setSelectedPanel({ sceneId: prevPanel.scene_id, panelNumber: prevPanel.panel_number }) : null}
          onNext={nextPanel ? () => setSelectedPanel({ sceneId: nextPanel.scene_id, panelNumber: nextPanel.panel_number }) : null}
          project={name}
          sceneId={selectedPanel.sceneId}
          panelNumber={selectedPanel.panelNumber}
          imageUrl={selectedPanelImageUrl}
        />
      )}
    </RoomShell>
  );
}
