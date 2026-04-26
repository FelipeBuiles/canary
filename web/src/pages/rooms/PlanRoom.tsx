import { useParams, useSearchParams } from "react-router-dom";
import { useLayoutPlan, useProjectStatus, useStoryBible } from "../../api/queries";
import { RoomHeader } from "../../components/ui/RoomHeader";
import { StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { useCharacterName } from "../../hooks/useCharacterName";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import type { PlannedPanel, PlannedPage } from "../../types/api";

const IMPORTANCE_STYLES: Record<string, string> = {
  standard: "bg-surface-container text-ink-black/60",
  accent: "bg-chip-gold text-ink-black",
  hero: "bg-ink-black text-bristol",
  splash: "bg-hero-red text-bristol",
  inset: "bg-secondary-container text-on-secondary-container",
};

const IMPORTANCE_SIZE: Record<string, string> = {
  splash: "px-2.5 py-1 text-[0.6rem]",
  hero: "px-2.5 py-1 text-[0.6rem]",
  accent: "px-2 py-0.5 text-[0.55rem]",
  standard: "px-2 py-0.5 text-[0.52rem]",
  inset: "px-2 py-0.5 text-[0.52rem]",
};

function PlanPanelCard({
  panel,
  resolveName,
}: {
  panel: PlannedPanel;
  resolveName: (id: string) => string;
}) {
  const importanceStyle = IMPORTANCE_STYLES[panel.importance] ?? IMPORTANCE_STYLES.standard;
  const importanceSz = IMPORTANCE_SIZE[panel.importance] ?? IMPORTANCE_SIZE.standard;

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
          <span
            className={`font-meta font-bold uppercase tracking-[0.1em] ${importanceStyle} ${importanceSz}`}
          >
            {panel.importance}
          </span>
          <span className="border border-ink-black/15 px-2 py-0.5 font-meta text-[0.52rem] tracking-[0.1em] text-ink-black/55">
            {panel.shape_intent}
          </span>
          <span
            title={`Planned by: ${panel.generation_mode}`}
            className="flex h-4 w-4 cursor-help items-center justify-center font-meta text-[0.7rem] text-ink-black/35 hover:text-ink-black/70"
          >
            ⓘ
          </span>
        </div>
      </div>

      <p className="mt-4 text-[1rem] font-semibold leading-7 text-ink-black/70">
        {panel.background_description}
      </p>

      {panel.characters_present.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {panel.characters_present.map((cid) => (
            <span
              key={cid}
              className="bg-surface-container px-2.5 py-1 font-meta text-[0.62rem] font-bold leading-none tracking-[0.08em] text-ink-black"
            >
              {resolveName(cid)}
            </span>
          ))}
        </div>
      )}

      {panel.dialogue.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {panel.dialogue.map((d, i) => (
            <div
              key={i}
              className="border-l-[3px] border-hero-red py-0.5 pl-3 text-[0.92rem] font-semibold italic leading-6 text-ink-black/78"
            >
              "{d.text}"
            </div>
          ))}
        </div>
      )}

      <div className="mt-3 font-meta text-[0.58rem] tracking-[0.06em] text-ink-black/40">
        Panel {String(panel.panel_number).padStart(2, "0")}
        {panel.beat_ids.length > 0 && (
          <> · {panel.beat_ids.length} beat{panel.beat_ids.length !== 1 ? "s" : ""}</>
        )}
      </div>
    </article>
  );
}

function PageBreakBand({ page }: { page: PlannedPage }) {
  return (
    <div className="col-span-full my-2 flex items-center gap-3">
      <span className="h-px flex-1 bg-ink-black/18" />
      <span className="font-meta text-[0.62rem] font-bold tracking-[0.2em] text-ink-black/45 uppercase">
        PAGE {String(page.page_number).padStart(2, "0")}
        <span className="ml-2 font-normal">{page.panel_ids.length} panels</span>
        {page.page_rhythm_role && (
          <span className="ml-2 font-normal uppercase">{page.page_rhythm_role.replace(/_/g, " ")}</span>
        )}
      </span>
      <span className="h-px flex-1 bg-ink-black/18" />
    </div>
  );
}

export function PlanRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: plan, isLoading } = useLayoutPlan(name);
  const { data: status } = useProjectStatus(name);
  const { data: bible } = useStoryBible(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const resolveName = useCharacterName(name);
  const { isCompact, toggle } = useHeaderMode();

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

  // Build scene title map from bible
  const sceneTitleMap: Record<string, string> = {};
  if (bible) {
    for (const s of bible.scenes) {
      sceneTitleMap[s.id] = s.title;
    }
  }

  // Build page-break groups for the active scene
  // Each entry is either a PlannedPage (separator) or a PlannedPanel (card)
  type GridItem =
    | { kind: "page"; page: PlannedPage }
    | { kind: "panel"; panel: PlannedPanel };

  const gridItems: GridItem[] = [];
  if (plan && scenePanels.length > 0) {
    const panelIdToPanel = Object.fromEntries(
      plan.planned_panels.map((p) => [p.panel_id, p]),
    );
    const usedPanelIds = new Set<string>();

    for (const page of plan.planned_pages) {
      const pagePanels = page.panel_ids
        .map((id) => panelIdToPanel[id])
        .filter((p) => p && p.scene_id === activeScene);

      if (pagePanels.length > 0) {
        gridItems.push({ kind: "page", page });
        for (const p of pagePanels) {
          gridItems.push({ kind: "panel", panel: p });
          usedPanelIds.add(p.panel_id);
        }
      }
    }

    // Any panels not assigned to a page
    for (const panel of scenePanels) {
      if (!usedPanelIds.has(panel.panel_id)) {
        gridItems.push({ kind: "panel", panel });
      }
    }
  }

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

  const rerunAction = <RerunStageAction project={name} stage="plan" label="Plan" />;

  return (
    <RoomShell>
      <div className="flex h-[calc(100vh-3rem)] min-h-0 flex-col gap-3 md:h-[calc(100vh-5rem)] md:gap-8">
        <RoomHeader
          kicker="PLAN / LAYOUT PLAN"
          title="LAYOUT PLAN"
          lead="Planned panels with importance, shape intent, and page assignment — the structural blueprint before image generation."
          actions={rerunAction}
          compact={isCompact}
          onToggle={toggle}
        />

        {plan.warnings.length > 0 && (
          <div className="shrink-0 border-b-[2px] border-narrator-gold/50 bg-narrator-gold/15 px-5 py-3">
            {plan.warnings.map((w, i) => (
              <p key={i} className="font-meta text-[0.65rem] tracking-[0.06em] text-ink-black/80">
                ⚠ {w}
              </p>
            ))}
          </div>
        )}

        <section className="grid min-h-0 flex-1 grid-rows-[minmax(132px,30%)_minmax(0,1fr)] overflow-hidden border-[2px] border-ink-black bg-bristol xl:grid-cols-[200px_minmax(0,1fr)] xl:grid-rows-none">
          {sceneIds.length > 0 && (
            <div className="min-h-0 border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
              <SceneSidebar
                items={sceneIds.map((id) => ({
                  id,
                  label: id.replace(/_/g, " ").toUpperCase(),
                  sceneTitle: sceneTitleMap[id] ?? null,
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
                  {gridItems.map((item) =>
                    item.kind === "page" ? (
                      <PageBreakBand key={`page-${item.page.page_id}`} page={item.page} />
                    ) : (
                      <PlanPanelCard
                        key={item.panel.panel_id}
                        panel={item.panel}
                        resolveName={resolveName}
                      />
                    ),
                  )}
                </div>
              </div>
            ) : (
              <div className="p-6">
                <StateBlock
                  title="SELECT A SCENE"
                  description="Select a scene to view planned panels."
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
