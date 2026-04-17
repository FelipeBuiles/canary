import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useGenerationJobs, useImages, useProjectStatus, useRegenPanel } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { PanelCard } from "../../components/PanelCard";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { StatRow } from "../../components/ui/StatRow";
import { RoomShell } from "../../components/ui/RoomShell";
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

  const { data: images, isLoading } = useImages(name, regeningKeys.length > 0 ? 2000 : undefined);
  const { data: status } = useProjectStatus(name);
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

  const baseImages = (sceneFilter
    ? images?.filter((img) => img.scene_id === sceneFilter)
    : images) ?? [];

  // Keep the regen panel in the grid while its file is absent from disk.
  const displayImages: ImageStatus[] = [...baseImages];
  for (const regeningKey of regeningKeys) {
    const lastDash = regeningKey.lastIndexOf("-");
    const regenSceneId = regeningKey.slice(0, lastDash);
    const regenPanelNum = parseInt(regeningKey.slice(lastDash + 1), 10);
    const alreadyPresent = displayImages.some(
      (img) => img.scene_id === regenSceneId && img.panel_number === regenPanelNum,
    );
    if (!alreadyPresent && (!sceneFilter || sceneFilter === regenSceneId)) {
      const synth: ImageStatus = { scene_id: regenSceneId, panel_number: regenPanelNum, status: "pending" };
      const idx = displayImages.findIndex(
        (img) =>
          img.scene_id > regenSceneId ||
          (img.scene_id === regenSceneId && img.panel_number > regenPanelNum),
      );
      if (idx === -1) displayImages.push(synth);
      else displayImages.splice(idx, 0, synth);
    }
  }

  const scenes = [...new Set(displayImages.map((img) => img.scene_id))];

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING PANEL GALLERY…" />;
  }

  if ((!images?.length && regeningKeys.length === 0) || !name) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="PANEL GALLERY NOT AVAILABLE"
        emptyDescription="Complete the DRAW stage first."
      />
    );
  }

  return (
    <RoomShell>
      <ShowcaseHeader
        label="DRAW / PANEL GALLERY"
        title="PANEL GALLERY"
        lead="Every generated panel at a glance — regenerate individual frames, review failures, switch scenes."
      />
      <StyleCallout project={name} />
      <div className="flex flex-wrap gap-2">
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
      </div>

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
              />
            );
          })}
        </div>

        <div className="space-y-4">
          <Card className="p-3">
            <div className="border-b-[2px] border-ink-black pb-2 font-display text-[1rem] font-bold tracking-[-0.04em]">
              REFS
            </div>
            <div className="mt-3 border-[2px] border-ink-black bg-ink-black p-3 text-bristol">
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/62">SCENE PALETTE</div>
              <div className="mt-3 flex gap-2">
                <div className="h-7 w-7 border border-bristol bg-[#24261d]" />
                <div className="h-7 w-7 border border-bristol bg-hero-red" />
                <div className="h-7 w-7 border border-bristol bg-bristol" />
                <div className="h-7 w-7 border border-bristol bg-[#6d5d58]" />
              </div>
            </div>
          </Card>
          <Card className="p-3">
            <div className="space-y-2">
              <StatRow label="TOTAL PANELS">{displayImages.length}</StatRow>
              <StatRow label="COMPLETED">{images?.filter((i) => i.status === "done").length ?? 0}</StatRow>
              <StatRow label="FAILED">{images?.filter((i) => i.status === "failed").length ?? 0}</StatRow>
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
          </Card>
        </div>
      </section>
    </RoomShell>
  );
}
