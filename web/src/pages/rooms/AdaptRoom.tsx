import { useState } from "react";
import { useParams } from "react-router-dom";
import { useScreenplays, useScreenplay } from "../../api/queries";
import { SectionLabel } from "../../components/SectionLabel";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";

export function AdaptRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading: loadingList } = useScreenplays(name);
  const [selectedScene, setSelectedScene] = useState<string | null>(null);
  const { data: screenplay, isLoading: loadingScript } = useScreenplay(name, selectedScene);

  return (
    <RoomShell
      isLoading={loadingList}
      loadingText="LOADING SCREENPLAYS..."
      isEmpty={!summaries?.length || !name}
      emptyTitle="SCREENPLAYS NOT AVAILABLE"
      emptyDescription="Complete the ADAPT stage first."
    >
      <section className="border-[2px] border-ink-black bg-bristol p-4 md:p-5">
        <SectionLabel>ADAPT / SCREENPLAY</SectionLabel>
        <h1 className="mt-3 font-display text-[2.5rem] font-bold leading-[0.86] tracking-[-0.08em] text-ink-black">
          SCREENPLAY VIEWER
        </h1>
      </section>

      <section className="grid gap-5 xl:grid-cols-[220px_1fr]">
        {summaries && (
          <SceneSidebar
            items={summaries.map((s) => ({
              id: s.scene_id,
              label: s.scene_id.replace("_", " ").toUpperCase(),
              count: `${s.beat_count} beats`,
            }))}
            activeId={selectedScene ?? summaries[0]?.scene_id ?? ""}
            onSelect={setSelectedScene}
          />
        )}

        <Card className="p-4 md:p-5">
          {loadingScript ? (
            <div className="flex min-h-[40vh] items-center justify-center">
              <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                LOADING...
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
