import { useParams, useSearchParams } from "react-router-dom";
import { useScreenplays, useScreenplay } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { useRunAction } from "../../hooks/useRunAction";

export function AdaptRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading: loadingList } = useScreenplays(name);
  const { handleRun, isPending } = useRunAction();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const { data: screenplay, isLoading: loadingScript } = useScreenplay(name, selectedScene);

  return (
    <RoomShell
      isLoading={loadingList}
      loadingText="LOADING SCREENPLAYS…"
      isEmpty={!summaries?.length || !name}
      emptyTitle="SCREENPLAYS NOT AVAILABLE"
      emptyDescription="Complete the ADAPT stage first."
    >
      <ShowcaseHeader
        label="ADAPT / SCREENPLAY"
        title="SCREENPLAY VIEWER"
        lead="Each scene's prose rendered into beats — action, dialogue, sfx, description — ready to panel."
        actions={(
          <Button
            size="sm"
            variant="outline"
            onClick={() => name && handleRun(name, "screenplay", true)}
            disabled={isPending}
          >
            {isPending ? "RERUNNING…" : "RERUN ADAPT"}
          </Button>
        )}
      />

      <section className="grid gap-5 xl:grid-cols-[220px_1fr]">
        {summaries && (
          <SceneSidebar
            items={summaries.map((s) => ({
              id: s.scene_id,
              label: s.scene_id.replace("_", " ").toUpperCase(),
              count: `${s.beat_count} beats`,
            }))}
            activeId={selectedScene ?? summaries[0]?.scene_id ?? ""}
            onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
          />
        )}

        <Card className="p-4 md:p-5">
          {loadingScript ? (
            <div className="flex min-h-[40vh] items-center justify-center">
              <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                LOADING…
              </p>
            </div>
          ) : screenplay ? (
            <div>
              <div className="flex items-center gap-3 border-b-[2px] border-ink-black pb-3">
                <div>
                  <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45">
                    LOCATION
                  </div>
                  <div className="font-display text-[1rem] font-bold tracking-[-0.04em]">
                    {screenplay.location_id.replace("_", " ").toUpperCase()}
                  </div>
                </div>
                <div className="ml-auto">
                  <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45">
                    CHARACTERS
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {screenplay.characters.map((cid) => (
                      <Tag key={cid}>{cid}</Tag>
                    ))}
                  </div>
                </div>
              </div>

              <div className="mt-4 space-y-3">
                {screenplay.beats.map((beat, i) => (
                  <div
                    key={i}
                    className={`border-l-[4px] py-2 pl-4 ${
                      beat.type === "dialogue"
                        ? "border-hero-red"
                        : beat.type === "action"
                          ? "border-narrator-gold"
                          : beat.type === "sfx"
                            ? "border-ink-black"
                            : "border-archive-sage"
                    }`}
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
            <div className="flex min-h-[40vh] items-center justify-center text-[0.82rem] text-ink-black/50">
              Select a scene to view the screenplay.
            </div>
          )}
        </Card>
      </section>
    </RoomShell>
  );
}
