import { useParams, useSearchParams } from "react-router-dom";
import { useLayoutPlan, useProjectStatus } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import type { PlannedPanel } from "../../types/api";

const IMPORTANCE_STYLES: Record<string, string> = {
  standard: "bg-surface-container text-ink-black/70",
  accent: "bg-chip-gold text-ink-black",
  hero: "bg-hero-red text-bristol",
  splash: "bg-ink-black text-bristol",
  inset: "bg-secondary-container text-on-secondary-container",
};

function PlanPanelCard({ panel }: { panel: PlannedPanel }) {
  const importanceStyle = IMPORTANCE_STYLES[panel.importance] ?? IMPORTANCE_STYLES.standard;

  return (
    <article className="min-h-[180px] border-[2px] border-ink-black/8 bg-pulp-paper px-6 py-5 transition-colors duration-150 hover:border-ink-black/24">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="font-meta text-[0.72rem] font-bold tracking-[0.2em] text-ink-black">
            {panel.shot_type.toUpperCase().replace(/[-_]/g, " ")}
          </span>
          {panel.camera_angle && (
            <span className="font-body text-[0.82rem] font-semibold text-ink-black/45">
              {panel.camera_angle}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`px-2 py-0.5 font-meta text-[0.52rem] tracking-[0.1em] uppercase ${importanceStyle}`}>
            {panel.importance}
          </span>
          <span className="border border-ink-black/15 px-2 py-0.5 font-meta text-[0.52rem] tracking-[0.1em] text-ink-black/55">
            {panel.shape_intent}
          </span>
        </div>
      </div>

      <p className="mt-4 text-[1rem] font-semibold leading-7 text-ink-black/70">
        {panel.background_description}
      </p>

      {panel.characters_present.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {panel.characters_present.map((cid) => (
            <span key={cid} className="bg-surface-container px-2.5 py-1 font-meta text-[0.62rem] font-bold leading-none tracking-[0.08em] text-ink-black">
              {cid}
            </span>
          ))}
        </div>
      )}

      {panel.dialogue.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {panel.dialogue.map((d, i) => (
            <div key={i} className="border-l-[3px] border-hero-red py-0.5 pl-3 text-[0.92rem] font-semibold italic leading-6 text-ink-black/78">
              "{d.text}"
            </div>
          ))}
        </div>
      )}

      <div className="mt-3 flex gap-3 font-meta text-[0.58rem] tracking-[0.06em] text-ink-black/40">
        <span>PANEL {panel.panel_number}</span>
        <span>·</span>
        <span>{panel.generation_mode.toUpperCase()} MODE</span>
        {panel.beat_ids.length > 0 && (
          <>
            <span>·</span>
            <span>{panel.beat_ids.length} beat{panel.beat_ids.length !== 1 ? "s" : ""}</span>
          </>
        )}
      </div>
    </article>
  );
}

export function PlanRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: plan, isLoading } = useLayoutPlan(name);
  const { data: status } = useProjectStatus(name);
  const [searchParams, setSearchParams] = useSearchParams();

  const stageInfo = status?.stages?.plan;
  const stageStatus = stageInfo?.status ?? "pending";

  const sceneIds = plan
    ? [...new Set(plan.planned_panels.map((p) => p.scene_id))]
    : [];

  const selectedScene = searchParams.get("scene");
  const activeScene = selectedScene ?? sceneIds[0] ?? null;

  const scenePanels = plan
    ? plan.planned_panels.filter((p) => p.scene_id === activeScene)
    : [];

  const panelCountByScene = plan
    ? Object.fromEntries(
        sceneIds.map((id) => [
          id,
          plan.planned_panels.filter((p) => p.scene_id === id).length,
        ]),
      )
    : {};

  if (isLoading || (!plan && stageStatus !== "pending")) {
    return <RoomShell isLoading loadingText="LOADING LAYOUT PLAN…" />;
  }

  if (!plan || sceneIds.length === 0 || !name) {
    return (
      <RoomShell>
        <StagePlaceholder
          stage="plan"
          status={stageStatus}
          itemsDone={stageInfo?.items_done}
          itemsTotal={stageInfo?.items_total}
        />
      </RoomShell>
    );
  }

  return (
    <RoomShell>
      <div className="flex h-[calc(100vh-3rem)] min-h-0 flex-col gap-10 md:h-[calc(100vh-5rem)]">
        <ShowcaseHeader
          label="PLAN / LAYOUT PLAN"
          title="LAYOUT PLAN"
          lead="Planned panels with importance, shape intent, and page assignment — the structural blueprint before image generation."
          actions={name ? <RerunStageAction project={name} stage="plan" label="Plan" /> : null}
        />

        {plan && plan.warnings.length > 0 && (
          <div className="flex flex-col gap-1.5 rounded border border-narrator-gold/40 bg-narrator-gold/10 px-4 py-3">
            {plan.warnings.map((w, i) => (
              <p key={i} className="font-meta text-[0.65rem] tracking-[0.06em] text-ink-black/70">
                ⚠ {w}
              </p>
            ))}
          </div>
        )}

        <section className="grid min-h-0 flex-1 grid-rows-[minmax(132px,30%)_minmax(0,1fr)] overflow-hidden border-[2px] border-ink-black bg-bristol xl:grid-cols-[300px_minmax(0,1fr)] xl:grid-rows-none">
          {sceneIds.length > 0 && (
            <div className="min-h-0 border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
              <SceneSidebar
                items={sceneIds.map((id) => ({
                  id,
                  label: id.replace(/_/g, " ").toUpperCase(),
                  count: `${panelCountByScene[id] ?? 0} panels`,
                }))}
                activeId={activeScene ?? ""}
                onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
              />
            </div>
          )}

          <div className="min-h-0 min-w-0 overflow-hidden">
            {scenePanels.length > 0 ? (
              <div className="h-full min-h-0 overflow-y-auto p-6 md:p-8">
                <div className="grid gap-5 lg:grid-cols-2 2xl:grid-cols-3">
                  {scenePanels.map((panel) => (
                    <PlanPanelCard key={panel.panel_id} panel={panel} />
                  ))}
                </div>
              </div>
            ) : (
              <div className="p-6">
                <StateBlock title="SELECT A SCENE" description="Select a scene to view planned panels." icon="draft" />
              </div>
            )}
          </div>
        </section>
      </div>
    </RoomShell>
  );
}
