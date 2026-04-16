import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useImages, useProjectStatus, useRegenPanel } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { PanelCard } from "../../components/PanelCard";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { StatRow } from "../../components/ui/StatRow";
import { RoomShell } from "../../components/ui/RoomShell";
import { useRegenStore } from "../../store/regen";
import { useState } from "react";
import type { ImageStatus } from "../../types/api";

export function DrawRoom() {
  const { name } = useParams<{ name: string }>();
  const { active, bustTimestamps, errors, begin, markStarted, complete, fail } = useRegenStore();
  const [sceneFilter, setSceneFilter] = useState<string | null>(null);

  const projectRegen = name ? (active[name] ?? null) : null;
  const regeningKey = projectRegen?.key ?? null;
  const regenStartedAt = projectRegen?.startedAt ?? null;

  const { data: images, isLoading, dataUpdatedAt } = useImages(name, regeningKey ? 2000 : undefined);
  const { data: status } = useProjectStatus(name);
  const { mutate: regen } = useRegenPanel();

  // Completion: panel reappears in a poll that happened after file was deleted.
  useEffect(() => {
    if (!name || !regeningKey || !images || regenStartedAt === null) return;
    // dataUpdatedAt < regenStartedAt means cached data from before the delete — skip.
    if (dataUpdatedAt < regenStartedAt) return;

    const lastDash = regeningKey.lastIndexOf("-");
    const sceneId = regeningKey.slice(0, lastDash);
    const panelNum = parseInt(regeningKey.slice(lastDash + 1), 10);
    const done = images.some(
      (img) => img.scene_id === sceneId && img.panel_number === panelNum,
    );
    if (done) complete(name, regeningKey);
  }, [images, dataUpdatedAt, regeningKey, regenStartedAt, name, complete]);

  function handleRegen(sceneId: string, panelNumber: number) {
    if (!name) return;
    const key = `${sceneId}-${panelNumber}`;
    begin(name, key);
    regen(
      { project: name, sceneId, panelNumber },
      {
        onSuccess: () => markStarted(name),
        onError: (err) => {
          fail(name, key, err instanceof Error ? err.message : "Regeneration failed");
        },
      },
    );
  }

  const generateStage = status?.stages?.generate;
  const failedItems = generateStage?.items_failed ?? [];

  const baseImages = (sceneFilter
    ? images?.filter((img) => img.scene_id === sceneFilter)
    : images) ?? [];

  // Keep the regen panel in the grid while its file is absent from disk.
  const displayImages: ImageStatus[] = [...baseImages];
  if (regeningKey && name) {
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
    return <RoomShell isLoading loadingText="LOADING PANEL GALLERY..." />;
  }

  if ((!images?.length && !regeningKey) || !name) {
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
                isRegening={regeningKey === key}
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
              <StatRow label="TOTAL PANELS">{(images?.length ?? 0) + (regeningKey ? 1 : 0)}</StatRow>
              <StatRow label="COMPLETED">{images?.filter((i) => i.status === "done").length ?? 0}</StatRow>
              <StatRow label="FAILED">{images?.filter((i) => i.status === "failed").length ?? 0}</StatRow>
              {regeningKey && (
                <StatRow label="REGENING">
                  <span className="animate-pulse text-narrator-gold">1</span>
                </StatRow>
              )}
            </div>
          </Card>
        </div>
      </section>
    </RoomShell>
  );
}
