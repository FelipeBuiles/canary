import { useParams } from "react-router-dom";
import { useStoryBible } from "../../api/queries";
import { SectionLabel } from "../../components/SectionLabel";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import type { Character, Location } from "../../types/api";

function CharacterCastCard({ character, projectName }: { character: Character; projectName: string }) {
  const refUrl = `/api/projects/${encodeURIComponent(projectName)}/files/refs/${character.id}/front.png`;

  return (
    <Card>
      <div className="relative border-b-[2px] border-ink-black bg-ink-black">
        <img
          src={refUrl}
          alt={character.name}
          className="aspect-[4/5] w-full object-cover"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
        <Tag className="absolute right-2 top-2 bg-hero-red text-bristol">
          REF
        </Tag>
      </div>
      <div className="p-3">
        <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black">
          {character.name}
        </div>
        <div className="mt-1 font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/55">
          {character.age_range} &middot; {character.gender}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {character.distinguishing_features.slice(0, 3).map((f) => (
            <Tag key={f}>{f}</Tag>
          ))}
        </div>
      </div>
    </Card>
  );
}

function LocationPlateCard({ location, projectName }: { location: Location; projectName: string }) {
  const plateUrl = `/api/projects/${encodeURIComponent(projectName)}/files/plates/${location.id}.png`;

  return (
    <Card>
      <div className="relative border-b-[2px] border-ink-black bg-ink-black">
        <img
          src={plateUrl}
          alt={location.name}
          className="aspect-[16/9] w-full object-cover"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
      </div>
      <div className="p-3">
        <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black">
          {location.name}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {location.time_of_day && (
            <Tag>{location.time_of_day}</Tag>
          )}
          <Tag>{location.mood}</Tag>
        </div>
      </div>
    </Card>
  );
}

export function CastRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: bible, isLoading } = useStoryBible(name);

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING CAST..." />;
  }

  if (!bible || !name) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="CAST NOT AVAILABLE"
        emptyDescription="Complete the EXTRACT and CAST stages first."
      />
    );
  }

  return (
    <RoomShell>
      <section className="grid gap-5 xl:grid-cols-2">
        <div>
          <div className="mb-3">
            <h2 className="font-display text-[2.5rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
              CHARACTER REFS
            </h2>
          </div>
          <SectionLabel>DRAMATIS PERSONAE</SectionLabel>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {bible.characters.map((char) => (
              <CharacterCastCard key={char.id} character={char} projectName={name} />
            ))}
          </div>
        </div>

        <div>
          <div className="mb-3">
            <h2 className="font-display text-[2.5rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
              LOCATION PLATES
            </h2>
          </div>
          <SectionLabel>THE WORLD STAGE</SectionLabel>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {bible.locations.map((loc) => (
              <LocationPlateCard key={loc.id} location={loc} projectName={name} />
            ))}
          </div>
        </div>
      </section>
    </RoomShell>
  );
}
