import { useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useScreenplays, useScreenplay } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";

const BEAT_LABEL: Record<string, string> = {
  action: "ACTION",
  dialogue: "DIALOGUE",
  direction: "STAGE DIR.",
  sfx: "SFX",
};

export function AdaptRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading: loadingList } = useScreenplays(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id ?? null;
  const { data: screenplay, isLoading: loadingScript } = useScreenplay(name, activeScene);

  useEffect(() => {
    if (selectedScene || !summaries?.[0]?.scene_id) return;
    setSearchParams({ scene: summaries[0].scene_id }, { replace: true });
  }, [selectedScene, setSearchParams, summaries]);

  return (
    <RoomShell
      isLoading={loadingList}
      loadingText="LOADING SCREENPLAYS…"
      isEmpty={!summaries?.length || !name}
      emptyTitle="SCREENPLAYS NOT AVAILABLE"
      emptyDescription="Complete ADAPT first."
    >
      <div className="flex h-[calc(100vh-3rem)] min-h-0 flex-col gap-10 md:h-[calc(100vh-5rem)]">
        <ShowcaseHeader
          label="ADAPT / SCREENPLAY"
          title="SCREENPLAY VIEWER"
          lead="Each scene's prose rendered into beats — action, dialogue, sfx, description — ready to panel."
          actions={name ? <RerunStageAction project={name} stage="screenplay" label="Adapt" /> : null}
        />

        <section className="grid min-h-0 flex-1 grid-rows-[minmax(132px,30%)_minmax(0,1fr)] overflow-hidden border-[2px] border-ink-black bg-bristol xl:grid-cols-[300px_minmax(0,1fr)] xl:grid-rows-none">
          {summaries && (
            <div className="min-h-0 border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
              <SceneSidebar
                items={summaries.map((s) => ({
                  id: s.scene_id,
                  label: s.scene_id.replace(/_/g, " ").toUpperCase(),
                  count: `${s.beat_count} beats`,
                }))}
                activeId={activeScene ?? ""}
                onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
              />
            </div>
          )}

          <div className="min-h-0 min-w-0 overflow-hidden">
            {loadingScript ? (
              <div className="p-6"><LoadingBlock label="LOADING…" /></div>
            ) : screenplay ? (
              <div className="flex h-full min-h-0 flex-col">
                <div className="flex shrink-0 items-start justify-between gap-4 px-8 py-6">
                  <div>
                    <div className="font-meta text-[0.68rem] tracking-[0.22em] text-ink-black/45">
                      LOCATION
                    </div>
                    <div className="mt-1 font-meta text-[1rem] tracking-[0.16em] text-ink-black">
                      {screenplay.location_id.toUpperCase()}
                    </div>
                  </div>
                  <div className="flex flex-wrap justify-end gap-2 pt-1">
                    {screenplay.characters.map((cid) => (
                      <Tag key={cid} className="bg-surface-container px-4 py-1.5 text-[0.7rem]">
                        {cid}
                      </Tag>
                    ))}
                  </div>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-8 pb-8">
                  {screenplay.beats.map((beat, i) => {
                    const isDialogue = beat.type === "dialogue";
                    const isDirection = beat.type === "direction";
                    const labelText = BEAT_LABEL[beat.type] ?? beat.type.toUpperCase();
                    const fullLabel = isDialogue && beat.character_id
                      ? `${labelText} — ${beat.character_id}`
                      : labelText;
                    return (
                      <div key={i} className="border-b border-ink-black/12 py-4">
                        <div className={`font-meta text-[0.72rem] tracking-[0.18em] ${isDialogue ? "text-hero-red" : "text-ink-black/72"}`}>
                          {fullLabel}
                        </div>
                        <div className={`mt-2 text-[1.18rem] font-semibold leading-8 ${isDirection ? "italic text-ink-black/50" : "text-ink-black/88"}`}>
                          {beat.content}
                        </div>
                        {beat.direction && (
                          <div className="mt-4 border-t border-ink-black/10 pt-3">
                            <div className="font-meta text-[0.72rem] tracking-[0.18em] text-ink-black/45">
                              STAGE DIR.
                            </div>
                            <div className="mt-2 text-[1.08rem] font-semibold italic leading-7 text-ink-black/48">
                              {beat.direction}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="p-6"><StateBlock title="SELECT A SCENE" description="Select a scene to view the screenplay." icon="draft" /></div>
            )}
          </div>
        </section>
      </div>
    </RoomShell>
  );
}
