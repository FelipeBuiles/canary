import { useParams } from "react-router-dom";
import { useStoryBible, useUpdateStoryBible } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { SectionDivider } from "../../components/SectionDivider";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { SurfaceHeader } from "../../components/ui/Surface";
import { EditableText } from "../../components/ui/EditableText";
import { RoomShell } from "../../components/ui/RoomShell";
import { useRunAction } from "../../hooks/useRunAction";
import type { Character, Location } from "../../types/api";

export function CharacterCard({
  character,
  onSave,
}: {
  character: Character;
  onSave: (updated: Character) => void;
}) {
  const update = (patch: Partial<Character>) =>
    onSave({ ...character, ...patch });

  return (
    <Card className="p-4">
      <SurfaceHeader
        kicker={character.id.toUpperCase()}
        title={(
          <EditableText
            value={character.name}
            onSave={(v) => update({ name: v })}
            className="font-display text-[1.15rem] font-bold tracking-[-0.05em] text-ink-black"
          />
        )}
        actions={<Tag className="bg-pulp-paper">{character.id.toUpperCase()}</Tag>}
        className="-m-4 mb-3"
      />
      <div className="mt-1 flex items-center gap-1 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">
        <EditableText
          value={character.age_range}
          onSave={(v) => update({ age_range: v })}
          className="text-ink-black/55"
        />
        <span>&middot;</span>
        <EditableText
          value={character.gender}
          onSave={(v) => update({ gender: v })}
          className="text-ink-black/55"
        />
      </div>
      <div className="mt-3 text-[0.82rem] leading-6 text-ink-black/74">
        <span className="font-meta text-[0.48rem] tracking-[0.18em] text-ink-black/45">VISUAL ANCHOR</span>
        <EditableText
          value={character.visual_anchor}
          onSave={(v) => update({ visual_anchor: v })}
          multiline
          className="mt-1 block text-[0.78rem] italic leading-6 text-ink-black/68"
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {character.distinguishing_features.map((f) => (
          <Tag key={f}>{f}</Tag>
        ))}
      </div>
    </Card>
  );
}

export function LocationCard({
  location,
  onSave,
}: {
  location: Location;
  onSave: (updated: Location) => void;
}) {
  const update = (patch: Partial<Location>) =>
    onSave({ ...location, ...patch });

  return (
    <Card className="p-4">
      <SurfaceHeader
        kicker={location.id.toUpperCase()}
        title={(
          <EditableText
            value={location.name}
            onSave={(v) => update({ name: v })}
            className="font-display text-[1.15rem] font-bold tracking-[-0.05em] text-ink-black"
          />
        )}
        actions={<Tag className="bg-pulp-paper">{location.id.toUpperCase()}</Tag>}
        className="-m-4 mb-3"
      />
      <EditableText
        value={location.visual_anchor}
        onSave={(v) => update({ visual_anchor: v })}
        multiline
        className="mt-2 block text-[0.78rem] italic leading-6 text-ink-black/68"
      />
      <div className="mt-3 flex flex-wrap gap-1.5">
        {location.time_of_day && (
          <EditableText
            value={location.time_of_day}
            onSave={(v) => update({ time_of_day: v })}
            className="border border-ink-black px-2 py-1 font-meta text-[0.44rem] tracking-[0.14em]"
          />
        )}
        <EditableText
          value={location.mood}
          onSave={(v) => update({ mood: v })}
          className="border border-ink-black px-2 py-1 font-meta text-[0.44rem] tracking-[0.14em]"
        />
      </div>
    </Card>
  );
}

export function StoryBibleRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: bible, isLoading, error } = useStoryBible(name);
  const updateBible = useUpdateStoryBible();
  const { handleRun, isPending } = useRunAction();

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING STORY BIBLE…" />;
  }

  if (error || !bible || !name) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="STORY BIBLE NOT AVAILABLE"
        emptyDescription={error instanceof Error ? error.message : error ? "Failed to load story bible." : "This stage has not been reached yet."}
      />
    );
  }

  const handleUpdateCharacter = (updatedChar: Character) => {
    const newBible = {
      ...bible,
      characters: bible.characters.map(c => c.id === updatedChar.id ? updatedChar : c)
    };
    updateBible.mutate({ project: name, data: newBible });
  };

  const handleUpdateLocation = (updatedLoc: Location) => {
    const newBible = {
      ...bible,
      locations: bible.locations.map(l => l.id === updatedLoc.id ? updatedLoc : l)
    };
    updateBible.mutate({ project: name, data: newBible });
  };

  return (
    <RoomShell>
      <ShowcaseHeader
        label="EXTRACT / STORY BIBLE"
        title={bible.title}
        lead={<>by {bible.author} &middot; {bible.total_scenes} scenes extracted into the narrative frame.</>}
        actions={(
          <Button
            size="sm"
            variant="outline"
            onClick={() => name && handleRun(name, "extract", true)}
            disabled={isPending}
          >
            {isPending ? "RERUNNING…" : "RERUN EXTRACT"}
          </Button>
        )}
      />

      <section className="grid gap-6 xl:grid-cols-2">
        <div>
          <SectionDivider number={1} label="DRAMATIS PERSONAE" />
          <h2 className="mt-3 font-display text-[2.25rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
            CHARACTER ENTITIES
          </h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            {bible.characters.map((char) => (
              <CharacterCard
                key={char.id}
                character={char}
                onSave={handleUpdateCharacter}
              />
            ))}
          </div>
        </div>

        <div>
          <SectionDivider number={2} label="THE WORLD STAGE" />
          <h2 className="mt-3 font-display text-[2.25rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
            LOCATION NODES
          </h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            {bible.locations.map((loc) => (
              <LocationCard
                key={loc.id}
                location={loc}
                onSave={handleUpdateLocation}
              />
            ))}
          </div>
        </div>
      </section>
    </RoomShell>
  );
}
