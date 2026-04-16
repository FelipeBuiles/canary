import { useParams } from "react-router-dom";
import { useStoryBible } from "../../api/queries";
import { SectionLabel } from "../../components/SectionLabel";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import type { Character, Location } from "../../types/api";

function CharacterCard({ character }: { character: Character }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-display text-[1.15rem] font-bold tracking-[-0.05em] text-ink-black">
            {character.name}
          </div>
          <div className="mt-1 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">
            {character.age_range} &middot; {character.gender}
          </div>
        </div>
        <Tag className="bg-pulp-paper">{character.id.toUpperCase()}</Tag>
      </div>
      <div className="mt-3 text-[0.82rem] leading-6 text-ink-black/74">
        <span className="font-meta text-[0.48rem] tracking-[0.18em] text-ink-black/45">VISUAL ANCHOR</span>
        <p className="mt-1 text-[0.78rem] italic leading-6 text-ink-black/68">
          {character.visual_anchor}
        </p>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {character.distinguishing_features.map((f) => (
          <Tag key={f}>{f}</Tag>
        ))}
      </div>
    </Card>
  );
}

function LocationCard({ location }: { location: Location }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div className="font-display text-[1.15rem] font-bold tracking-[-0.05em] text-ink-black">
          {location.name}
        </div>
        <Tag className="bg-pulp-paper">{location.id.toUpperCase()}</Tag>
      </div>
      <p className="mt-2 text-[0.78rem] italic leading-6 text-ink-black/68">
        {location.visual_anchor}
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {location.time_of_day && (
          <Tag>{location.time_of_day}</Tag>
        )}
        <Tag>{location.mood}</Tag>
      </div>
    </Card>
  );
}

export function StoryBibleRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: bible, isLoading, error } = useStoryBible(name);

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING STORY BIBLE..." />;
  }

  if (error || !bible) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="STORY BIBLE NOT AVAILABLE"
        emptyDescription={error ? error.message : "This stage has not been reached yet."}
      />
    );
  }

  return (
    <RoomShell>
      <section className="border-[2px] border-ink-black bg-bristol p-4 md:p-5">
        <SectionLabel>EXTRACT / STORY BIBLE</SectionLabel>
        <h1 className="mt-3 max-w-[12ch] font-display text-[3rem] font-bold leading-[0.86] tracking-[-0.08em] text-ink-black md:text-[4.7rem]">
          {bible.title}
        </h1>
        <p className="mt-3 text-[0.9rem] text-ink-black/60">
          by {bible.author} &middot; {bible.total_scenes} scenes
        </p>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <div>
          <div className="mb-3 flex items-center gap-3">
            <h2 className="font-display text-[2.5rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
              CHARACTER ENTITIES
            </h2>
          </div>
          <SectionLabel>DRAMATIS PERSONAE</SectionLabel>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {bible.characters.map((char) => (
              <CharacterCard key={char.id} character={char} />
            ))}
          </div>
        </div>

        <div>
          <div className="mb-3">
            <h2 className="font-display text-[2.5rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
              LOCATION NODES
            </h2>
          </div>
          <SectionLabel>THE WORLD STAGE</SectionLabel>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {bible.locations.map((loc) => (
              <LocationCard key={loc.id} location={loc} />
            ))}
          </div>
        </div>
      </section>
    </RoomShell>
  );
}
