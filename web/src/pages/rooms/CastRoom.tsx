import { useState } from "react";
import { useParams } from "react-router-dom";
import { useStoryBible } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { SectionDivider } from "../../components/SectionDivider";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import type { Character, Location } from "../../types/api";

function CharacterCastCard({ character, projectName }: { character: Character; projectName: string }) {
  const refUrl = `/api/projects/${encodeURIComponent(projectName)}/files/refs/${encodeURIComponent(character.id)}/front.png`;
  const [imgFailed, setImgFailed] = useState(false);

  return (
    <Card>
      <div className="relative border-b-[2px] border-ink-black bg-ink-black">
        {imgFailed ? (
          <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
            <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/40">NO REF IMAGE</div>
            <div className="font-meta text-[0.44rem] tracking-[0.14em] text-bristol/25">RUN CAST STAGE</div>
          </div>
        ) : (
          <img
            src={refUrl}
            alt={character.name}
            className="aspect-[4/5] w-full object-cover"
            onError={() => setImgFailed(true)}
          />
        )}
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
  const plateUrl = `/api/projects/${encodeURIComponent(projectName)}/files/plates/${encodeURIComponent(location.id)}.png`;
  const [imgFailed, setImgFailed] = useState(false);

  return (
    <Card>
      <div className="relative border-b-[2px] border-ink-black bg-ink-black">
        {imgFailed ? (
          <div className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
            <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/40">NO PLATE IMAGE</div>
            <div className="font-meta text-[0.44rem] tracking-[0.14em] text-bristol/25">RUN CAST STAGE</div>
          </div>
        ) : (
          <img
            src={plateUrl}
            alt={location.name}
            className="aspect-[16/9] w-full object-cover"
            onError={() => setImgFailed(true)}
          />
        )}
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
      <ShowcaseHeader
        label="CAST / CHARACTER & LOCATION REFS"
        title="CASTING CALL"
        lead="Reference sheets and location plates produced by the casting director — each used as the visual anchor for every downstream panel."
      />

      <section className="grid gap-6 xl:grid-cols-2">
        <div>
          <SectionDivider number={1} label="DRAMATIS PERSONAE" />
          <h2 className="mt-3 font-display text-[2.25rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
            CHARACTER REFS
          </h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {bible.characters.map((char) => (
              <CharacterCastCard key={char.id} character={char} projectName={name} />
            ))}
          </div>
        </div>

        <div>
          <SectionDivider number={2} label="THE WORLD STAGE" />
          <h2 className="mt-3 font-display text-[2.25rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
            LOCATION PLATES
          </h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            {bible.locations.map((loc) => (
              <LocationPlateCard key={loc.id} location={loc} projectName={name} />
            ))}
          </div>
        </div>
      </section>
    </RoomShell>
  );
}
