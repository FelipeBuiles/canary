import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useGenerationJobs, useImages, useProjectStatus, useRegenPanel, usePromptSummaries } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { PanelCard } from "../../components/PanelCard";
import { Button } from "../../components/ui/Button";
import { ControlGroup } from "../../components/ui/ControlGroup";
import { ImageModal } from "../../components/ui/ImageModal";
import { StatRow } from "../../components/ui/StatRow";
import { RoomShell } from "../../components/ui/RoomShell";
import { Surface, SurfaceHeader } from "../../components/ui/Surface";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { StyleCallout } from "../../components/wizard/StyleCallout";
import { useActiveRegens, useRegenStore } from "../../store/regen";
import type { ImageStatus } from "../../types/api";

export function DrawRoom() {
  const { name } = useParams<{ name: string }>();
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

  const generateStage = status?.stages?.generate;
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

  // Add failed panels that might not be in images yet
  for (const failedItem of failedItems) {
    const parts = failedItem.split("/");
    const failedSceneId = parts[0];
    const panelMatch = parts[1]?.match(/panel_(\d+)/);
    if (!panelMatch) continue;
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
    if (isGenerateStale) return "stale";
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

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING PANEL GALLERY…" />;
  }

  if ((!images?.length && !promptSummaries?.length && regeningKeys.length === 0) || !name) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="PANEL GALLERY NOT AVAILABLE"
        emptyDescription="Complete DRAW first."
      />
    );
  }

  return (
    <RoomShell>
      <ShowcaseHeader
        label="DRAW / PANEL GALLERY"
        title="PANEL GALLERY"
        lead="Every generated panel at a glance — regenerate individual frames, review failures, switch scenes."
        actions={<RerunStageAction project={name} stage="generate" label="Draw" itemsAtRisk={`${images?.length ?? 0} generated panels will be lost`} />}
      />
      <StyleCallout project={name} />
      <ControlGroup label="FILTER" aria-label="Panel filters">
        <Button variant={!sceneFilter ? "primary" : "outline"} size="sm" onClick={() => setSceneFilter(null)}>
          ALL
        </Button>
        {scenes.map((sceneId) => (
          <Button
            key={sceneId}
            variant={sceneFilter === sceneId ? "primary" : "outline"}
            size="sm"
            onClick={() => setSceneFilter(sceneId)}
          >
            {sceneId.replace("_", " ").toUpperCase()}
          </Button>
        ))}
      </ControlGroup>

      <section className="grid gap-5 xl:grid-cols-[1fr_240px]">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {displayImages.map((img) => {
            const key = `${img.scene_id}-${img.panel_number}`;
            const bust = name ? bustTimestamps[`${name}/${key}`] : undefined;
            const baseUrl = `/api/projects/${encodeURIComponent(name!)}/files/images/${img.scene_id}/panel_${String(img.panel_number).padStart(3, "0")}.png`;
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

        <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
          <Surface padding="sm" shadow="paper-sm">
            <SurfaceHeader kicker="VISUAL REFS" title="REFS" className="-m-3 mb-3" />
            <div className="mt-3 border-[2px] border-ink-black bg-ink-black p-3 text-bristol">
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/62">SCENE PALETTE</div>
              <div className="mt-3 flex gap-2">
                <div className="h-7 w-7 border border-bristol bg-[#24261d]" />
                <div className="h-7 w-7 border border-bristol bg-hero-red" />
                <div className="h-7 w-7 border border-bristol bg-bristol" />
                <div className="h-7 w-7 border border-bristol bg-[#6d5d58]" />
              </div>
            </div>
          </Surface>
          <Surface padding="sm" shadow="paper-sm">
            <div className="space-y-2">
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
          </Surface>
        </div>
      </section>
      {selectedPanel && name && (
        <ImageModal
          isOpen={!!selectedPanel}
          onClose={() => setSelectedPanel(null)}
          src={`/api/projects/${encodeURIComponent(name)}/files/images/${selectedPanel.sceneId}/panel_${String(selectedPanel.panelNumber).padStart(3, "0")}.png`}
          alt={`${selectedPanel.sceneId} panel ${selectedPanel.panelNumber}`}
        />
      )}
    </RoomShell>
  );
}
