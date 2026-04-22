import { useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useScreenplays, useScreenplay } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { SurfaceHeader } from "../../components/ui/Surface";
import { RerunStageAction } from "../../components/ui/RerunStageAction";

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

  const beatBorderClass = (type: string) => {
    if (type === "action") return "border-ink-black";
    if (type === "dialogue") return "border-hero-red";
    if (type === "direction") return "border-ink-fade";
    if (type === "sfx") return "border-narrator-gold";
    return "border-archive-sage";
  };

  return (
    <RoomShell
      isLoading={loadingList}
      loadingText="LOADING SCREENPLAYS…"
      isEmpty={!summaries?.length || !name}
      emptyTitle="SCREENPLAYS NOT AVAILABLE"
      emptyDescription="Complete ADAPT first."
    >
      <ShowcaseHeader
        label="ADAPT / SCREENPLAY"
        title="SCREENPLAY VIEWER"
        lead="Each scene's prose rendered into beats — action, dialogue, sfx, description — ready to panel."
        actions={name ? <RerunStageAction project={name} stage="screenplay" label="Adapt" /> : null}
      />

      <section className="grid border-[2px] border-ink-black bg-bristol xl:grid-cols-[200px_1fr]">
        {summaries && (
          <div className="border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
            <SceneSidebar
              items={summaries.map((s) => ({
                id: s.scene_id,
                label: s.scene_id.replace("_", " ").toUpperCase(),
                count: `${s.beat_count} beats`,
              }))}
              activeId={activeScene ?? ""}
              onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
            />
          </div>
        )}

        <div className="min-w-0 p-4 md:p-6">
          {loadingScript ? (
            <LoadingBlock label="LOADING…" />
          ) : screenplay ? (
            <div>
              <SurfaceHeader
                kicker="LOCATION"
                title={screenplay.location_id.replace("_", " ").toUpperCase()}
                actions={(
                  <div className="text-right">
                    <div className="ui-kicker">CHARACTERS</div>
                    <div className="mt-1 flex flex-wrap justify-end gap-1">
                      {screenplay.characters.map((cid) => (
                        <Tag key={cid}>{cid}</Tag>
                      ))}
                    </div>
                  </div>
                )}
                className="-m-4 mb-4 md:-m-5 md:mb-4"
              />
              <div className="mt-4 space-y-3">
                {screenplay.beats.map((beat, i) => (
                  <div
                    key={i}
                    className={`border-l-[4px] py-2 pl-4 ${beatBorderClass(beat.type)}`}
                  >
                    <div className="font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
                      {beat.type.toUpperCase()}
                      {beat.character_id && ` — ${beat.character_id}`}
                    </div>
                    <div className="mt-1 text-[0.85rem] leading-6 text-ink-black/80">
                      {beat.content}
                    </div>
                    {beat.direction && (
                      <div className="mt-1 text-[0.72rem] italic text-ink-black/50">
                        {beat.direction}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <StateBlock title="SELECT A SCENE" description="Select a scene to view the screenplay." icon="draft" />
          )}
        </div>
      </section>
    </RoomShell>
  );
}
