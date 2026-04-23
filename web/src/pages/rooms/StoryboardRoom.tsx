import { useParams, useSearchParams } from "react-router-dom";
import { usePanelSummaries, usePanelsForScene, useUpdatePanel } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { EditableText } from "../../components/ui/EditableText";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { ShotDiagram } from "../../components/ui/ShotDiagram";
import type { PanelBreakdown } from "../../types/api";

function titleCaseShot(value: string) {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.toUpperCase())
    .join("-");
}

export function StoryboardRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading } = usePanelSummaries(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;
  const { data: panels, isLoading: loadingPanels } = usePanelsForScene(name, activeScene);
  const updatePanel = useUpdatePanel();

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
      emptyDescription="Complete STORYBOARD first."
    >
      <ShowcaseHeader
        label="STORYBOARD / PANEL BREAKDOWN"
        title="PANEL BREAKDOWNS"
        lead="Shot-by-shot blocking with camera, lighting, and dialogue — the blueprint the artist hands to the penciller."
        actions={name ? <RerunStageAction project={name} stage="panels" label="Storyboard" /> : null}
      />

      <section className="grid border-[2px] border-ink-black bg-bristol xl:grid-cols-[200px_1fr]">
        {summaries && (
          <div className="border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
            <SceneSidebar
              items={summaries.map((s) => ({
                id: s.scene_id,
                label: s.scene_id.replace(/_/g, " ").toUpperCase(),
                count: `${s.panel_count} beats`,
              }))}
              activeId={activeScene ?? ""}
              onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
            />
          </div>
        )}

        <div className="min-w-0 p-5 md:p-7">
          {loadingPanels ? (
            <LoadingBlock label="LOADING…" />
          ) : panels?.length ? (
            <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
              {panels.map((panel) => (
                <div
                  key={`${panel.scene_id}-${panel.panel_number}`}
                  className="min-h-[230px] border-[2px] border-ink-black bg-pulp-paper p-5 shadow-paper-sm"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <ShotDiagram shot={panel.shot_type} size={26} className="shrink-0 [&>span]:hidden" />
                      <EditableText
                        value={titleCaseShot(panel.shot_type)}
                        onSave={(v) => handleSavePanel(panel, { shot_type: v })}
                        className="font-meta text-[0.7rem] tracking-[0.2em] text-ink-black"
                      />
                    </div>
                    <EditableText
                      value={panel.camera_angle}
                      onSave={(v) => handleSavePanel(panel, { camera_angle: v })}
                      className="shrink-0 font-meta text-[0.58rem] tracking-[0.12em] text-ink-black/45"
                    />
                  </div>

                  <div className="mt-5 space-y-3">
                    <div className="font-meta text-[0.58rem] tracking-[0.14em] text-ink-black/45">
                      PANEL {String(panel.panel_number).padStart(2, "0")}
                    </div>
                    <EditableText
                      value={panel.background_description}
                      onSave={(v) => handleSavePanel(panel, { background_description: v })}
                      multiline
                      className="block text-[1rem] leading-6 text-ink-black/74"
                    />
                    <div className="flex flex-wrap gap-1">
                      {panel.characters_present.map((cid) => (
                        <span key={cid} className="border border-ink-black/25 bg-surface-container px-2 py-0.5 font-meta text-[0.54rem] tracking-[0.1em] text-ink-black">
                          {cid}
                        </span>
                      ))}
                    </div>
                    {panel.dialogue.length > 0 && (
                      <div className="space-y-2">
                        {panel.dialogue.map((d, i) => (
                          <div key={i} className="border-l-[2px] border-hero-red py-0.5 pl-3 text-[0.9rem] italic leading-6 text-ink-black/78">
                            "{d.text}"
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[0.72rem] text-ink-black/45">
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
                </div>
              ))}
            </div>
          ) : (
            <StateBlock title="SELECT A SCENE" description="Select a scene to view panel breakdowns." icon="draft" />
          )}
        </div>
      </section>
    </RoomShell>
  );
}
