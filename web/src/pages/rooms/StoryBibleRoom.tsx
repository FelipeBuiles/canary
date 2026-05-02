import { useState } from "react";
import { useParams } from "react-router-dom";
import { useProjectStatus, useStoryBible, useUpdateStoryBible } from "../../api/queries";
import { RoomHeader } from "../../components/ui/RoomHeader";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import { Tag } from "../../components/ui/Tag";
import { EditableText } from "../../components/ui/EditableText";
import { RoomShell } from "../../components/ui/RoomShell";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
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
  const truncateAt = 120;
  const [expanded, setExpanded] = useState(value.length <= truncateAt);
  const shouldTruncate = value.length > truncateAt;
  const displayValue = !expanded && shouldTruncate ? `${value.slice(0, truncateAt).trim()}...` : value;

  return (
    <div className="mt-5 text-[1.05rem] font-semibold leading-8 text-ink-black/70">
      <span className="block font-meta text-[0.68rem] font-bold tracking-[0.22em] text-ink-black/45">{label}</span>
      {expanded ? (
        <EditableText
          value={value}
          onSave={onSave}
          multiline
          className="mt-2 block max-w-[72ch] text-[1.05rem] font-semibold leading-8 text-ink-black/70"
        />
      ) : (
        <p className="mt-2 max-w-[72ch]">
          {displayValue}
          {" "}
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="font-meta text-[0.72rem] tracking-[0.14em] text-hero-red hover:text-ink-black"
          >
            expand
          </button>
        </p>
      )}
      {expanded && shouldTruncate && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="mt-2 font-meta text-[0.72rem] tracking-[0.14em] text-hero-red hover:text-ink-black"
        >
          collapse
        </button>
      )}
    </div>
  );
}

function EntitySectionHeader({
  number,
  label,
  title,
}: {
  number: number;
  label: string;
  title: string;
}) {
  return (
    <header className="mb-7 border-b-[2px] border-ink-black pb-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <div className="font-meta text-[0.82rem] tracking-[0.24em] text-ink-black/52">
          SECTION {String(number).padStart(2, "0")} // {label}
        </div>
        <h2 className="font-display text-[1.9rem] font-black uppercase leading-none tracking-[-0.05em] text-ink-black">
          {title}
        </h2>
      </div>
    </header>
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
    <article className="border-[2px] border-ink-black/8 bg-bristol px-7 py-6 transition-colors duration-150 hover:border-ink-black/24">
      <div className="flex items-start justify-between gap-4">
        <EditableText
          value={character.name}
          onSave={(v) => update({ name: v })}
          className="font-display text-[1.55rem] font-black uppercase leading-none tracking-[-0.05em] text-ink-black"
        />
        <Tag className="shrink-0 border-transparent bg-surface-container px-4 text-[0.66rem] text-ink-black/48">
          {character.id.toUpperCase()}
        </Tag>
      </div>
      <div className="mt-3 flex items-center gap-2 font-body text-[1rem] font-semibold text-ink-black/50">
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
          <Tag key={f} className="border-transparent bg-surface-container px-4 text-[0.66rem] text-ink-black/70">
            {f}
          </Tag>
        ))}
      </div>
    </article>
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
    <article className="border-[2px] border-ink-black/8 bg-bristol px-7 py-6 transition-colors duration-150 hover:border-ink-black/24">
      <div className="flex items-start justify-between gap-4">
        <EditableText
          value={location.name}
          onSave={(v) => update({ name: v })}
          className="font-display text-[1.55rem] font-black uppercase leading-none tracking-[-0.05em] text-ink-black"
        />
        <Tag className="shrink-0 border-transparent bg-surface-container px-4 text-[0.66rem] text-ink-black/48">
          {location.id.toUpperCase()}
        </Tag>
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
            className="bg-surface-container px-4 py-1.5 font-meta text-[0.66rem] font-bold tracking-[0.14em] text-ink-black/70"
          />
        )}
        <EditableText
          value={location.mood}
          onSave={(v) => update({ mood: v })}
          className="bg-surface-container px-4 py-1.5 font-meta text-[0.66rem] font-bold tracking-[0.14em] text-ink-black/70"
        />
      </div>
    </article>
  );
}

export function StoryBibleRoom() {
  const { id } = useParams<{ id: string }>();
  const { isCompact, toggle } = useHeaderMode();
  const { data: bible, isLoading, error } = useStoryBible(id);
  const { data: status } = useProjectStatus(id);
  const updateBible = useUpdateStoryBible();

  const stageInfo = status?.stages?.extract;
  const stageStatus = stageInfo?.status ?? "pending";

  if (isLoading || (!bible && stageStatus !== "pending")) {
    return <RoomShell isLoading loadingText="LOADING STORY BIBLE…" />;
  }

  if (error || !bible || !id) {
    return (
      <RoomShell>
        <StagePlaceholder
          stage="extract"
          status={stageStatus}
          itemsDone={stageInfo?.items_done}
          itemsTotal={stageInfo?.items_total}
        />
      </RoomShell>
    );
  }

  const handleUpdateCharacter = (updatedChar: Character) => {
    const newBible = {
      ...bible,
      characters: bible.characters.map(c => c.id === updatedChar.id ? updatedChar : c)
    };
    updateBible.mutate({ project: id, data: newBible });
  };

  const handleUpdateLocation = (updatedLoc: Location) => {
    const newBible = {
      ...bible,
      locations: bible.locations.map(l => l.id === updatedLoc.id ? updatedLoc : l)
    };
    updateBible.mutate({ project: id, data: newBible });
  };

  return (
    <RoomShell>
      <RoomHeader
        kicker="EXTRACT"
        compact={isCompact}
        onToggle={toggle}
        title={bible.title}
        lead={`by ${bible.author} · ${bible.total_scenes} scene${bible.total_scenes !== 1 ? "s" : ""} extracted into the narrative frame.`}
        actions={<RerunStageAction project={id} stage="extract" label="Extract" />}
      />

      <div className="grid gap-10 xl:grid-cols-2">
        {/* Characters */}
        <section>
          <EntitySectionHeader number={1} label="DRAMATIS PERSONAE" title="Character Entities" />
          <div className="grid gap-5">
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
          <EntitySectionHeader number={2} label="THE WORLD STAGE" title="Location Nodes" />
          <div className="grid gap-5">
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
