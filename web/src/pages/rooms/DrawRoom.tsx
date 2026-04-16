import { useState } from "react";
import { useParams } from "react-router-dom";
import { useImages, useProjectStatus } from "../../api/queries";
import { SectionLabel } from "../../components/SectionLabel";
import { PanelCard } from "../../components/PanelCard";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { StatRow } from "../../components/ui/StatRow";
import { RoomShell } from "../../components/ui/RoomShell";

export function DrawRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: images, isLoading } = useImages(name);
  const { data: status } = useProjectStatus(name);
  const [sceneFilter, setSceneFilter] = useState<string | null>(null);

  const scenes = images ? [...new Set(images.map((img) => img.scene_id))] : [];
  const filtered = sceneFilter
    ? images?.filter((img) => img.scene_id === sceneFilter)
    : images;
  const generateStage = status?.stages?.generate;
  const failedItems = generateStage?.items_failed ?? [];

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING PANEL GALLERY..." />;
  }

  if (!images?.length || !name) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="PANEL GALLERY NOT AVAILABLE"
        emptyDescription="Complete the DRAW stage first."
      />
    );
  }

  const visibleImages = filtered ?? [];

  return (
    <RoomShell>
      <section className="border-[2px] border-ink-black bg-bristol p-4 md:p-5">
        <SectionLabel>DRAW / PANEL GALLERY</SectionLabel>
        <h1 className="mt-3 font-display text-[2.5rem] font-bold leading-[0.86] tracking-[-0.08em] text-ink-black md:text-[3.75rem]">
          PANEL GALLERY
        </h1>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            variant={!sceneFilter ? "primary" : "outline"}
            size="sm"
            onClick={() => setSceneFilter(null)}
          >
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
      </section>

      <section className="grid gap-5 xl:grid-cols-[1fr_240px]">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {visibleImages.map((img) => {
            const imageUrl = `/api/projects/${encodeURIComponent(name)}/files/images/${img.scene_id}/panel_${String(img.panel_number).padStart(3, "0")}.png`;
            const isFailed = failedItems.includes(`${img.scene_id}/panel_${String(img.panel_number).padStart(3, "0")}`);

            return (
              <PanelCard
                key={`${img.scene_id}-${img.panel_number}`}
                sceneId={img.scene_id}
                panelNumber={img.panel_number}
                status={isFailed ? "failed" : img.status}
                imageUrl={imageUrl}
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
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/62">
                SCENE PALETTE
              </div>
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
              <StatRow label="TOTAL PANELS">{images.length}</StatRow>
              <StatRow label="COMPLETED">{images.filter((i) => i.status === "done").length}</StatRow>
              <StatRow label="FAILED">{images.filter((i) => i.status === "failed").length}</StatRow>
            </div>
          </Card>
        </div>
      </section>
    </RoomShell>
  );
}
