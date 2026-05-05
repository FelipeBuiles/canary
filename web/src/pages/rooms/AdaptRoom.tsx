import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  useProjectStatus,
  useScreenplays,
  useScreenplay,
  useStoryBible,
} from "../../api/queries";
import { RoomHeader } from "../../components/ui/RoomHeader";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { useCharacterName } from "../../hooks/useCharacterName";
import { useHeaderMode } from "../../hooks/useHeaderMode";

export function AdaptRoom() {
  const { id } = useParams<{ id: string }>();
  const { data: summaries, isLoading: loadingList } = useScreenplays(id);
  const { data: status } = useProjectStatus(id);
  const { data: bible } = useStoryBible(id);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id ?? null;
  const { data: screenplay, isLoading: loadingScript } = useScreenplay(id, activeScene);
  const stageInfo = status?.stages?.adapt;
  const stageStatus = stageInfo?.status ?? "pending";
  const resolveName = useCharacterName(id);
  const { isCompact, toggle } = useHeaderMode();

  // Character filter state
  const [activeCharFilter, setActiveCharFilter] = useState<string | null>(null);

  useEffect(() => {
    if (selectedScene || !summaries?.[0]?.scene_id) return;
    setSearchParams({ scene: summaries[0].scene_id }, { replace: true });
  }, [selectedScene, setSearchParams, summaries]);


  if (loadingList || (!summaries?.length && stageStatus !== "pending")) {
    return <RoomShell isLoading loadingText="LOADING SCREENPLAYS…" />;
  }

  if (!summaries?.length || !id) {
    return (
      <RoomShell>
        <StagePlaceholder
          stage="adapt"
          status={stageStatus}
          itemsDone={stageInfo?.items_done}
          itemsTotal={stageInfo?.items_total}
        />
      </RoomShell>
    );
  }

  const rerunAction = <RerunStageAction project={id} stage="adapt" label="Adapt" />;

  // Build scene → title map from story bible
  const sceneTitleMap: Record<string, string> = {};
  if (bible) {
    for (const s of bible.scenes) {
      sceneTitleMap[s.id] = s.title;
    }
  }

  // Current scene summary from bible
  const currentBibleScene = bible?.scenes.find((s) => s.id === activeScene);
  const sceneSummary = currentBibleScene?.summary ?? null;

  // Characters in current scene for filter chips
  const filterChars = screenplay?.characters ?? [];
  const filteredBeats = screenplay?.beats.filter((beat) => {
    if (!activeCharFilter) return true;
    return beat.character_id === activeCharFilter;
  });

  return (
    <RoomShell fullHeight>
      <div className="flex h-full min-h-0 flex-col gap-3 md:gap-8">
        <RoomHeader
          kicker="ADAPT"
          title="SCREENPLAY VIEWER"
          lead="Each scene's prose rendered into beats — action, dialogue, sfx, description — ready to panel."
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
                  count: `${s.beat_count} beats`,
                }))}
                activeId={activeScene ?? ""}
                onSelect={(id) => {
                  setSearchParams({ scene: id }, { replace: true });
                  setActiveCharFilter(null);
                }}
              />
            </div>
          )}

          <div className="min-h-0 min-w-0 overflow-hidden">
            {loadingScript ? (
              <div className="p-6"><LoadingBlock label="LOADING…" /></div>
            ) : screenplay ? (
              <div className="flex h-full min-h-0 flex-col">
                {/* Location + filter */}
                <div className="flex shrink-0 items-start justify-between gap-4 border-b border-ink-black/10 px-8 py-5">
                  <div>
                    <div className="font-meta text-[0.62rem] tracking-[0.22em] text-ink-black/45">
                      LOCATION
                    </div>
                    <div className="mt-0.5 font-display text-[1.1rem] font-black uppercase tracking-[-0.02em] text-ink-black [font-stretch:75%]">
                      {resolveName(screenplay.location_id)}
                    </div>
                  </div>

                  {filterChars.length > 0 && (
                    <div className="flex flex-col items-end gap-1.5 pt-0.5">
                      <div className="font-meta text-[0.58rem] tracking-[0.14em] text-ink-black/40 uppercase">
                        Filter by character
                      </div>
                      <div className="flex flex-wrap justify-end gap-1.5">
                        {filterChars.map((cid) => (
                          <button
                            key={cid}
                            type="button"
                            onClick={() =>
                              setActiveCharFilter((prev) => (prev === cid ? null : cid))
                            }
                            className={
                              activeCharFilter === cid
                                ? "bg-ink-black px-3 py-1 font-meta text-[0.62rem] font-bold tracking-[0.08em] text-bristol"
                                : "bg-surface-container px-3 py-1 font-meta text-[0.62rem] font-bold tracking-[0.08em] text-ink-black hover:bg-ink-black/10"
                            }
                          >
                            {resolveName(cid)}
                          </button>
                        ))}
                        {activeCharFilter && (
                          <button
                            type="button"
                            onClick={() => setActiveCharFilter(null)}
                            className="px-2 py-1 font-body text-[0.7rem] text-hero-red hover:underline"
                          >
                            clear
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-8 pb-8">
                  {/* Scene summary */}
                  {sceneSummary && (
                    <div className="mb-5 mt-5 border-l-[3px] border-hero-red pl-4 text-[0.82rem] leading-6 text-ink-black/62">
                      {sceneSummary}
                    </div>
                  )}

                  {/* Beats */}
                  {(filteredBeats ?? []).map((beat, i) => {
                    const isDialogue = beat.type === "dialogue";
                    const isDirection = beat.type === "direction";
                    const isNarration = beat.type === "narration";
                    const isSfx = beat.type === "sfx";
                    const isTransition = beat.transition_type != null && beat.content?.toLowerCase().startsWith("cut") || beat.type === "transition";

                    if (isTransition) {
                      return (
                        <div key={i} className="my-5 flex items-center gap-4">
                          <span className="h-px flex-1 bg-ink-black/12" />
                          <span className="font-meta text-[0.6rem] tracking-[0.22em] text-ink-black/35 uppercase">
                            {beat.content}
                          </span>
                          <span className="h-px flex-1 bg-ink-black/12" />
                        </div>
                      );
                    }

                    if (isSfx) {
                      return (
                        <div key={i} className="py-3">
                          <div className="font-meta text-[0.62rem] tracking-[0.22em] text-ink-black/45">
                            SFX
                          </div>
                          <div className="mt-1 font-meta text-[0.82rem] font-bold tracking-[0.1em] text-narrator-gold uppercase">
                            {beat.content}
                          </div>
                        </div>
                      );
                    }

                    if (isNarration) {
                      return (
                        <div
                          id={`beat-${i + 1}`}
                          key={i}
                          className="border-b border-narrator-gold/35 bg-narrator-gold/8 py-4"
                        >
                          <div className="font-meta text-[0.68rem] font-bold tracking-[0.18em] text-narrator-gold">
                            NARRATION
                          </div>
                          <div className="mt-2 max-w-[68ch] font-body text-[0.98rem] font-semibold leading-7 text-ink-black">
                            "{beat.content}"
                          </div>
                          {beat.narration_reason && (
                            <div className="mt-3 border-l-[3px] border-narrator-gold/60 pl-4 text-[0.78rem] leading-6 text-ink-fade">
                              {beat.narration_reason}
                            </div>
                          )}
                        </div>
                      );
                    }

                    if (isDirection) {
                      return (
                        <div key={i} className="py-2 pl-6">
                          <div className="font-body text-[0.78rem] italic leading-6 text-ink-fade">
                            {beat.content}
                          </div>
                          {beat.direction && (
                            <div className="mt-1 font-body text-[0.78rem] italic leading-6 text-ink-fade/70">
                              {beat.direction}
                            </div>
                          )}
                        </div>
                      );
                    }

                    const charLabel = isDialogue && beat.character_id
                      ? `DIALOGUE — ${resolveName(beat.character_id)}`
                      : isDialogue
                      ? "DIALOGUE"
                      : "ACTION";

                    return (
                      <div
                        id={`beat-${i + 1}`}
                        key={i}
                        className="border-b border-ink-black/10 py-4"
                      >
                        <div
                          className={`font-meta text-[0.68rem] tracking-[0.18em] ${
                            isDialogue ? "text-hero-red" : "text-ink-black/60"
                          }`}
                        >
                          {charLabel}
                        </div>
                        <div
                          className={`mt-2 font-body text-[0.9rem] font-medium leading-7 ${
                            isDialogue ? "text-ink-black" : "text-ink-black/80"
                          }`}
                        >
                          {beat.content}
                        </div>
                        {beat.direction && (
                          <div className="mt-3 pl-4 text-[0.78rem] italic leading-6 text-ink-fade">
                            {beat.direction}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="p-6">
                <StateBlock title="SELECT A SCENE" description="Select a scene to view the screenplay." icon="draft" />
              </div>
            )}
          </div>
        </section>
      </div>
    </RoomShell>
  );
}
