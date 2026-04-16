import { useState } from "react";
import { useParams } from "react-router-dom";
import { usePanelSummaries, usePanelsForScene } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";

export function StoryboardRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading } = usePanelSummaries(name);
  const [selectedScene, setSelectedScene] = useState<string | null>(null);
  const { data: panels, isLoading: loadingPanels } = usePanelsForScene(
    name,
    selectedScene ?? summaries?.[0]?.scene_id,
  );

  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;

  return (
    <RoomShell
      isLoading={isLoading}
      loadingText="LOADING PANEL BREAKDOWNS..."
      isEmpty={!summaries?.length || !name}
      emptyTitle="PANEL BREAKDOWNS NOT AVAILABLE"
      emptyDescription="Complete the STORYBOARD stage first."
    >
      <ShowcaseHeader
        label="STORYBOARD / PANEL BREAKDOWN"
        title="PANEL BREAKDOWNS"
        lead="Shot-by-shot blocking with camera, lighting, and dialogue — the blueprint the artist hands to the penciller."
      />

      <section className="grid gap-5 xl:grid-cols-[220px_1fr]">
        {summaries && (
          <SceneSidebar
            items={summaries.map((s) => ({
              id: s.scene_id,
              label: s.scene_id.replace("_", " ").toUpperCase(),
              count: `${s.panel_count} panels`,
            }))}
            activeId={activeScene ?? ""}
            onSelect={setSelectedScene}
          />
        )}

        <div>
          {loadingPanels ? (
            <div className="flex min-h-[40vh] items-center justify-center">
              <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                LOADING...
              </p>
            </div>
          ) : panels?.length ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {panels.map((panel) => (
                <Card key={`${panel.scene_id}-${panel.panel_number}`}>
                  <div className="border-b-[2px] border-ink-black bg-preview-tint p-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">
                          PANEL {String(panel.panel_number).padStart(2, "0")}
                        </div>
                        <div className="font-display text-[0.85rem] font-bold tracking-[-0.03em]">
                          {panel.shot_type}
                        </div>
                      </div>
                      <Tag>{panel.camera_angle}</Tag>
                    </div>
                  </div>
                  <div className="space-y-2 p-3">
                    <p className="text-[0.78rem] leading-6 text-ink-black/74">
                      {panel.background_description}
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {panel.characters_present.map((cid) => (
                        <Tag key={cid}>{cid}</Tag>
                      ))}
                    </div>
                    {panel.dialogue.length > 0 && (
                      <div className="space-y-1 border-t border-panel-line pt-2">
                        {panel.dialogue.map((d, i) => (
                          <div key={i} className="text-[0.72rem] text-ink-black/60">
                            <span className="font-meta text-[0.46rem] tracking-[0.14em] text-ink-black/45">
                              {d.type.toUpperCase()}
                            </span>{" "}
                            {d.text}
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="flex gap-2 text-[0.62rem] text-ink-black/45">
                      <span className="font-meta tracking-[0.14em]">{panel.lighting}</span>
                      <span className="font-meta tracking-[0.14em]">{panel.mood}</span>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          ) : (
            <div className="flex min-h-[40vh] items-center justify-center text-[0.82rem] text-ink-black/50">
              Select a scene to view panel breakdowns.
            </div>
          )}
        </div>
      </section>
    </RoomShell>
  );
}
