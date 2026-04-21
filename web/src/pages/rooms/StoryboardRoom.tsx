import { useParams, useSearchParams } from "react-router-dom";
import { usePanelSummaries, usePanelsForScene, useUpdatePanel } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { EditableText } from "../../components/ui/EditableText";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { useRunAction } from "../../hooks/useRunAction";
import type { PanelBreakdown } from "../../types/api";

export function StoryboardRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading } = usePanelSummaries(name);
  const { handleRun, isPending } = useRunAction();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const { data: panels, isLoading: loadingPanels } = usePanelsForScene(
    name,
    selectedScene ?? summaries?.[0]?.scene_id,
  );
  const updatePanel = useUpdatePanel();

  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;

  const handleSavePanel = (panel: PanelBreakdown, patch: Partial<PanelBreakdown>) => {
    if (!name || !activeScene) return;
    updatePanel.mutate({
      project: name,
      sceneId: activeScene,
      data: { ...panel, ...patch },
    });
  };

  return (
    <RoomShell
      isLoading={isLoading}
      loadingText="LOADING PANEL BREAKDOWNS…"
      isEmpty={!summaries?.length || !name}
      emptyTitle="PANEL BREAKDOWNS NOT AVAILABLE"
      emptyDescription="Complete the STORYBOARD stage first."
    >
      <ShowcaseHeader
        label="STORYBOARD / PANEL BREAKDOWN"
        title="PANEL BREAKDOWNS"
        lead="Shot-by-shot blocking with camera, lighting, and dialogue — the blueprint the artist hands to the penciller."
        actions={(
          <Button
            size="sm"
            variant="outline"
            onClick={() => name && handleRun(name, "panels", true)}
            disabled={isPending}
          >
            {isPending ? "RERUNNING…" : "RERUN STORYBOARD"}
          </Button>
        )}
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
            onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
          />
        )}

        <div>
          {loadingPanels ? (
            <div className="flex min-h-[40vh] items-center justify-center">
              <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                LOADING…
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
                        <EditableText
                          value={panel.shot_type}
                          onSave={(v) => handleSavePanel(panel, { shot_type: v })}
                          className="font-display text-[0.85rem] font-bold tracking-[-0.03em]"
                        />
                      </div>
                      <EditableText
                        value={panel.camera_angle}
                        onSave={(v) => handleSavePanel(panel, { camera_angle: v })}
                        className="border border-ink-black px-2 py-1 font-meta text-[0.44rem] tracking-[0.14em]"
                      />
                    </div>
                  </div>
                  <div className="space-y-2 p-3">
                    <EditableText
                      value={panel.background_description}
                      onSave={(v) => handleSavePanel(panel, { background_description: v })}
                      multiline
                      className="block text-[0.78rem] leading-6 text-ink-black/74"
                    />
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
                      <EditableText
                        value={panel.lighting}
                        onSave={(v) => handleSavePanel(panel, { lighting: v })}
                        className="font-meta tracking-[0.14em]"
                      />
                      <EditableText
                        value={panel.mood}
                        onSave={(v) => handleSavePanel(panel, { mood: v })}
                        className="font-meta tracking-[0.14em]"
                      />
                      {panel.sfx && (
                        <EditableText
                          value={panel.sfx}
                          onSave={(v) => handleSavePanel(panel, { sfx: v })}
                          className="font-meta tracking-[0.14em]"
                        />
                      )}
                      {panel.transition_note && (
                        <EditableText
                          value={panel.transition_note}
                          onSave={(v) => handleSavePanel(panel, { transition_note: v })}
                          className="font-meta tracking-[0.14em]"
                        />
                      )}
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
