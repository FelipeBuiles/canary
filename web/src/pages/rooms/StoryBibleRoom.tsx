import { useState } from "react";
import { useParams } from "react-router-dom";
import { useStoryBible, useUpdateStoryBible } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { SectionDivider } from "../../components/SectionDivider";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { EditableText } from "../../components/ui/EditableText";
import { RoomShell } from "../../components/ui/RoomShell";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import type { Character, Location } from "../../types/api";

function VisualAnchorEditor({
  value,
  onSave,
  label = "VISUAL ANCHOR",
}: {
  value: string;
  onSave: (value: string) => void;
  label?: string;
}) {
  const [expanded, setExpanded] = useState(value.length <= 100);
  const shouldTruncate = value.length > 100;
  const displayValue = !expanded && shouldTruncate ? `${value.slice(0, 100)}...` : value;

  return (
    <div className="mt-3 text-[0.82rem] leading-6 text-ink-black/74">
      <span className="font-meta text-[0.48rem] tracking-[0.18em] text-ink-black/45">{label}</span>
      {expanded ? (
        <EditableText
          value={value}
          onSave={onSave}
          multiline
          className="mt-1 block text-[0.78rem] italic leading-6 text-ink-black/68"
        />
      ) : (
        <p className="mt-1 text-[0.78rem] italic leading-6 text-ink-black/68">
          {displayValue}
        </p>
      )}
      {shouldTruncate && (
        <button
          type="button"
          onClick={() => setExpanded((next) => !next)}
          className="mt-1 font-meta text-[0.5rem] tracking-[0.16em] text-hero-red hover:text-ink-black"
        >
          {expanded ? "COLLAPSE" : "EXPAND"}
        </button>
      )}
    </div>
  );
}

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
    <Card shadow="lg" className="p-4">
      <div className="flex items-start justify-between gap-2">
        <EditableText
          value={character.name}
          onSave={(v) => update({ name: v })}
          className="font-display text-[1.15rem] font-bold uppercase tracking-[-0.05em] text-ink-black leading-none"
        />
        <Tag className="shrink-0 bg-pulp-paper">{character.id.toUpperCase()}</Tag>
      </div>
      <div className="mt-1.5 flex items-center gap-1 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">
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
      <VisualAnchorEditor
        value={character.visual_anchor}
        onSave={(v) => update({ visual_anchor: v })}
      />
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
    <Card shadow="lg" className="p-4">
      <div className="flex items-start justify-between gap-2">
        <EditableText
          value={location.name}
          onSave={(v) => update({ name: v })}
          className="font-display text-[1.15rem] font-bold uppercase tracking-[-0.05em] text-ink-black leading-none"
        />
        <Tag className="shrink-0 bg-pulp-paper">{location.id.toUpperCase()}</Tag>
      </div>
      <VisualAnchorEditor
        value={location.visual_anchor}
        onSave={(v) => update({ visual_anchor: v })}
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

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING STORY BIBLE…" />;
  }

  if (error || !bible || !name) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="STORY BIBLE NOT AVAILABLE"
        emptyDescription={error instanceof Error ? error.message : error ? "Failed to load story bible." : "This room is not ready yet."}
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
        lead={`by ${bible.author} · ${bible.total_scenes} scene${bible.total_scenes !== 1 ? "s" : ""} extracted into the narrative frame.`}
        actions={<RerunStageAction project={name} stage="extract" label="Extract" />}
      />

      <div className="grid gap-10 xl:grid-cols-2">
        {/* Characters */}
        <section>
          <SectionDivider number={1} label="DRAMATIS PERSONAE" />
          <h2 className="mt-2 font-display text-[1.4rem] font-bold uppercase leading-none tracking-[-0.03em]">
            Character Entities
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
        </section>

        {/* Locations */}
        <section>
          <SectionDivider number={2} label="THE WORLD STAGE" />
          <h2 className="mt-2 font-display text-[1.4rem] font-bold uppercase leading-none tracking-[-0.03em]">
            Location Nodes
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
        </section>
      </div>
    </RoomShell>
  );
}
