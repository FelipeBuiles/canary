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
                label: s.scene_id.replace(/_/g, " ").toUpperCase(),
                count: `${s.beat_count} beats`,
              }))}
              activeId={activeScene ?? ""}
              onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
            />
          </div>
        )}

        <div className="min-w-0 overflow-y-auto">
          {loadingScript ? (
            <div className="p-6"><LoadingBlock label="LOADING…" /></div>
          ) : screenplay ? (
            <div>
              {/* Location + character header row */}
              <div className="flex items-start justify-between gap-4 border-b border-ink-black/15 px-6 py-4">
                <div>
                  <div className="font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
                    LOCATION
                  </div>
                  <div className="mt-0.5 font-meta text-[0.68rem] tracking-[0.1em] text-ink-black">
                    {screenplay.location_id.toUpperCase()}
                  </div>
                </div>
                <div className="flex flex-wrap justify-end gap-1 pt-0.5">
                  {screenplay.characters.map((cid) => (
                    <Tag key={cid}>{cid}</Tag>
                  ))}
                </div>
              </div>

              {/* Beats */}
              <div>
                {screenplay.beats.map((beat, i) => {
                  const isDialogue = beat.type === "dialogue";
                  const isDirection = beat.type === "direction";
                  const labelText = BEAT_LABEL[beat.type] ?? beat.type.toUpperCase();
                  const fullLabel = isDialogue && beat.character_id
                    ? `${labelText} — ${beat.character_id}`
                    : labelText;
                  return (
                    <div key={i} className="border-b border-ink-black/15 px-6 py-3">
                      <div className={`font-meta text-[0.46rem] tracking-[0.18em] ${isDialogue ? "text-hero-red" : "text-ink-black/45"}`}>
                        {fullLabel}
                      </div>
                      <div className={`mt-1 text-[0.85rem] leading-6 ${isDirection ? "italic text-ink-black/55" : "text-ink-black/80"}`}>
                        {beat.content}
                      </div>
                      {beat.direction && (
                        <div className="mt-1 text-[0.72rem] italic text-ink-black/50">
                          {beat.direction}
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
    </RoomShell>
  );
}
