import { useParams, useSearchParams } from "react-router-dom";
import {
  usePanelSummaries,
  usePanelsForScene,
  useUpdatePanel,
  useProjectStatus,
  useStoryBible,
} from "../../api/queries";
import { RoomHeader } from "../../components/ui/RoomHeader";
import { EditableText } from "../../components/ui/EditableText";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { ShotDiagram } from "../../components/ui/ShotDiagram";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { useCharacterName } from "../../hooks/useCharacterName";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import type { PanelBreakdown } from "../../types/api";

function titleCaseShot(value: string) {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.toUpperCase())
    .join("-");
}

function StoryboardPanelCard({
  panel,
  onSave,
  resolveName,
}: {
  panel: PanelBreakdown;
  onSave: (patch: Partial<PanelBreakdown>) => void;
  resolveName: (id: string) => string;
}) {
  return (
    <article className="group min-h-[252px] border-[2px] border-ink-black/8 bg-pulp-paper px-6 py-6 transition-colors duration-150 hover:border-ink-black/24">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <ShotDiagram shot={panel.shot_type} size={28} className="shrink-0 [&>span]:hidden" />
          <EditableText
            value={titleCaseShot(panel.shot_type)}
            onSave={(v) => onSave({ shot_type: v })}
            className="font-meta text-[0.86rem] font-bold tracking-[0.2em] text-ink-black"
          />
        </div>
        <div className="flex items-center gap-2">
          <EditableText
            value={panel.camera_angle}
            onSave={(v) => onSave({ camera_angle: v })}
            className="shrink-0 font-body text-[0.82rem] font-semibold text-ink-black/45"
          />
          {/* Edit affordance: shown only on hover (desktop) */}
          <span className="hidden font-meta text-[0.6rem] tracking-[0.1em] text-hero-red opacity-0 transition-opacity group-hover:opacity-100 md:inline">
            ✎ click to edit
          </span>
          {/* Always visible on mobile */}
          <span className="font-meta text-[0.6rem] tracking-[0.1em] text-hero-red md:hidden">
            ✎ edit
          </span>
        </div>
      </div>

      <div className="mt-6">
        <div className="font-meta text-[0.72rem] font-bold tracking-[0.16em] text-ink-black/45">
          PANEL {String(panel.panel_number).padStart(2, "0")}
        </div>
        <EditableText
          value={panel.background_description}
          onSave={(v) => onSave({ background_description: v })}
          multiline
          className="mt-2 block text-[1.08rem] font-semibold leading-7 text-ink-black/70"
        />

        {panel.characters_present.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {panel.characters_present.map((cid) => (
              <span
                key={cid}
                className="bg-surface-container px-3 py-1 font-meta text-[0.68rem] font-bold leading-none tracking-[0.08em] text-ink-black"
              >
                {resolveName(cid)}
              </span>
            ))}
          </div>
        )}

        {panel.dialogue.length > 0 && (
          <div className="mt-4 space-y-2">
            {panel.dialogue.map((d, i) => (
              <div
                key={i}
                className="border-l-[3px] border-hero-red py-0.5 pl-4 text-[0.92rem] font-semibold italic leading-6 text-ink-black/78"
              >
                "{d.text}"
              </div>
            ))}
          </div>
        )}

        {/* Lighting / mood as labeled two-column row */}
        {(panel.lighting || panel.mood) && (
          <div className="mt-4 grid grid-cols-2 gap-3 border-t border-ink-black/8 pt-4">
            {panel.lighting && (
              <div>
                <div className="font-meta text-[0.58rem] tracking-[0.18em] text-ink-black/40 uppercase">
                  Light
                </div>
                <div className="mt-0.5 font-body text-[0.78rem] font-medium text-ink-black/70">
                  {panel.lighting}
                </div>
              </div>
            )}
            {panel.mood && (
              <div>
                <div className="font-meta text-[0.58rem] tracking-[0.18em] text-ink-black/40 uppercase">
                  Mood
                </div>
                <div className="mt-0.5 font-body text-[0.78rem] font-medium text-ink-black/70">
                  {panel.mood}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export function StoryboardRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading } = usePanelSummaries(name);
  const { data: status } = useProjectStatus(name);
  const { data: bible } = useStoryBible(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;
  const { data: panels, isLoading: loadingPanels } = usePanelsForScene(name, activeScene);
  const updatePanel = useUpdatePanel();
  const stageInfo = status?.stages?.storyboard;
  const stageStatus = stageInfo?.status ?? "pending";
  const resolveName = useCharacterName(name);
  const { isCompact, toggle } = useHeaderMode();

  const handleSavePanel = (panel: PanelBreakdown, patch: Partial<PanelBreakdown>) => {
    if (!name || !activeScene) return;
    updatePanel.mutate({
      project: name,
      sceneId: activeScene,
      data: { ...panel, ...patch },
    });
  };

  const sceneTitleMap: Record<string, string> = {};
  if (bible) {
    for (const s of bible.scenes) {
      sceneTitleMap[s.id] = s.title;
    }
  }

  if (isLoading || (!summaries?.length && stageStatus !== "pending")) {
    return <RoomShell isLoading loadingText="LOADING PANEL BREAKDOWNS…" />;
  }

  if (!summaries?.length || !name) {
    return (
      <RoomShell>
        <StagePlaceholder
          stage="storyboard"
          status={stageStatus}
          itemsDone={stageInfo?.items_done}
          itemsTotal={stageInfo?.items_total}
        />
      </RoomShell>
    );
  }

  const rerunAction = <RerunStageAction project={name} stage="storyboard" label="Storyboard" />;

  return (
    <RoomShell>
      <div className="flex h-[calc(100vh-3rem)] min-h-0 flex-col gap-3 md:h-[calc(100vh-5rem)] md:gap-8">
        <RoomHeader
          kicker="STORYBOARD"
          title="PANEL BREAKDOWNS"
          lead="Shot-by-shot blocking with camera, lighting, and dialogue — the blueprint the artist hands to the penciller."
          actions={rerunAction}
          compact={isCompact}
          onToggle={toggle}
        />

        <section className="grid min-h-0 flex-1 grid-rows-[minmax(132px,30%)_minmax(0,1fr)] overflow-hidden border-[2px] border-ink-black bg-bristol xl:grid-cols-[200px_minmax(0,1fr)] xl:grid-rows-none">
          {summaries && (
            <div className="min-h-0 border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
              <SceneSidebar
                items={summaries.map((s) => ({
                  id: s.scene_id,
                  label: s.scene_id.replace(/_/g, " ").toUpperCase(),
                  sceneTitle: sceneTitleMap[s.scene_id] ?? null,
                  count: `${s.panel_count} panels`,
                }))}
                activeId={activeScene ?? ""}
                onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
              />
            </div>
          )}

          <div className="min-h-0 min-w-0 overflow-hidden">
            {loadingPanels ? (
              <div className="p-6"><LoadingBlock label="LOADING…" /></div>
            ) : panels?.length ? (
              <div className="h-full min-h-0 overflow-y-auto p-6 md:p-8">
                <div className="grid gap-6 lg:grid-cols-2 2xl:grid-cols-3">
                  {panels.map((panel) => (
                    <StoryboardPanelCard
                      key={`${panel.scene_id}-${panel.panel_number}`}
                      panel={panel}
                      onSave={(patch) => handleSavePanel(panel, patch)}
                      resolveName={resolveName}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <div className="p-6">
                <StateBlock
                  title="SELECT A SCENE"
                  description="Select a scene to view panel breakdowns."
                  icon="draft"
                />
              </div>
            )}
          </div>
        </section>
      </div>
    </RoomShell>
  );
}
