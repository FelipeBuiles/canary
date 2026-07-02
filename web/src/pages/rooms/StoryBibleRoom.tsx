import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useProjectStatus,
  useStageEstimate,
  useStoryBible,
  useUpdateStoryBible,
} from "../../api/queries";
import { useRunAction } from "../../hooks/useRunAction";
import { Tag } from "../../components/ui/Tag";
import { EditableText } from "../../components/ui/EditableText";
import { InspectDrawer } from "../../components/InspectDrawer";
import {
  ApprovalBar,
  SectionHeader,
  EntityCard,
  RoomHeader,
  RoomShell,
  RerunStageAction,
  StagePlaceholder,
} from "../../components/composites";
import { useShowDevContent } from "../../lib/devContent";
import type { Character, Location, StoryBible } from "../../types/api";
import type { DrawerKind } from "../../lib/stations";

function VisualAnchorEditor({
  value,
  onSave,
  label = "HOW THEY'LL LOOK",
}: {
  value: string;
  onSave: (value: string) => void;
  label?: string;
}) {
  return (
    <div className="mt-5">
      <span className="block font-meta text-[0.68rem] font-bold tracking-[0.22em] text-ink-black/45">
        {label} <span className="font-normal text-ink-black/30">✎</span>
      </span>
      <EditableText
        value={value}
        onSave={onSave}
        multiline
        className="mt-2 block max-w-[72ch] text-[0.95rem] font-semibold leading-7 text-ink-black/70"
      />
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
  const [showDevContent] = useShowDevContent();
  const update = (patch: Partial<Character>) =>
    onSave({ ...character, ...patch });

  return (
    <EntityCard interactive>
      <div className="flex items-start justify-between gap-4">
        <EditableText
          value={character.name}
          onSave={(v) => update({ name: v })}
          className="font-display text-[1.55rem] font-black uppercase leading-none tracking-[-0.05em] text-ink-black"
        />
        {showDevContent && (
          <Tag className="shrink-0 border-transparent bg-surface-container px-4 text-[0.66rem] text-ink-black/48">
            {character.id.toUpperCase()}
          </Tag>
        )}
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
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {character.distinguishing_features.map((f) => (
          <Tag key={f} className="border-transparent bg-surface-container px-4 text-[0.66rem] text-ink-black/70">
            {f}
          </Tag>
        ))}
        {character.distinguishing_features.length > 0 && (
          <span className="font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/35">
            → USED IN IMAGE PROMPTS
          </span>
        )}
      </div>
    </EntityCard>
  );
}

export function LocationCard({
  location,
  onSave,
}: {
  location: Location;
  onSave: (updated: Location) => void;
}) {
  const [showDevContent] = useShowDevContent();
  const update = (patch: Partial<Location>) =>
    onSave({ ...location, ...patch });

  return (
    <EntityCard interactive>
      <div className="flex items-start justify-between gap-4">
        <EditableText
          value={location.name}
          onSave={(v) => update({ name: v })}
          className="font-display text-[1.55rem] font-black uppercase leading-none tracking-[-0.05em] text-ink-black"
        />
        {showDevContent && (
          <Tag className="shrink-0 border-transparent bg-surface-container px-4 text-[0.66rem] text-ink-black/48">
            {location.id.toUpperCase()}
          </Tag>
        )}
      </div>
      <VisualAnchorEditor
        value={location.visual_anchor}
        onSave={(v) => update({ visual_anchor: v })}
        label="HOW IT'LL LOOK"
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
    </EntityCard>
  );
}

function WhatPulpFound({
  bible,
  onReadScript,
  scriptReady,
}: {
  bible: StoryBible;
  onReadScript: () => void;
  scriptReady: boolean;
}) {
  const opening = bible.scenes[0]?.source_start_quote?.trim();
  return (
    <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
      {/* Source card */}
      <EntityCard>
        <div className="font-meta text-[0.56rem] tracking-[0.22em] text-ink-black/45">SOURCE</div>
        <h2 className="mt-2 font-display text-[1.9rem] font-black uppercase leading-[0.95] tracking-[-0.04em] text-ink-black">
          {bible.title}
        </h2>
        <div className="mt-2 font-meta text-[0.62rem] tracking-[0.14em] text-ink-black/50">
          BY {bible.author.toUpperCase()}
        </div>
        {opening && (
          <p className="mt-4 border-l-[3px] border-narrator-gold pl-4 text-[0.95rem] italic leading-7 text-ink-black/65">
            “{opening}”
          </p>
        )}
      </EntityCard>

      {/* What PULP found card */}
      <EntityCard>
        <div className="font-meta text-[0.56rem] tracking-[0.22em] text-ink-black/45">WHAT SCENEWRIGHT FOUND</div>
        <dl className="mt-3 space-y-2.5">
          <div className="flex items-baseline justify-between gap-3 border-b border-ink-black/10 pb-2.5">
            <dt className="text-[0.85rem] text-ink-black/60">Scenes</dt>
            <dd className="font-body text-[0.95rem] font-bold text-ink-black">
              {bible.total_scenes} · kept in story order
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-3 border-b border-ink-black/10 pb-2.5">
            <dt className="text-[0.85rem] text-ink-black/60">Cast</dt>
            <dd className="font-body text-[0.95rem] font-bold text-ink-black">
              {bible.characters.length} character{bible.characters.length !== 1 ? "s" : ""} · {bible.locations.length} place{bible.locations.length !== 1 ? "s" : ""}
            </dd>
          </div>
        </dl>
        <button
          type="button"
          onClick={onReadScript}
          className="mt-4 inline-flex items-center gap-2 border-[2px] border-ink-black/25 bg-bristol px-3 py-1.5 font-meta text-[0.58rem] tracking-[0.14em] text-ink-black/70 transition-colors hover:border-ink-black hover:text-ink-black"
        >
          READ THE SCRIPT ▸
          {!scriptReady && (
            <span className="font-meta text-[0.46rem] tracking-[0.1em] text-ink-black/35">WRITES ITSELF LATER</span>
          )}
        </button>
      </EntityCard>
    </div>
  );
}

export function StoryBibleRoom() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: bible, isLoading, error } = useStoryBible(id);
  const { data: status } = useProjectStatus(id);
  const updateBible = useUpdateStoryBible();
  const approveStage = useApproveStage();
  const { handleRun, isPending: isPipelineRunning } = useRunAction();
  const { data: styleEstimate } = useStageEstimate(id, "style");
  const [drawer, setDrawer] = useState<DrawerKind | null>(null);

  const stageInfo = status?.stages?.extract;
  const stageStatus = stageInfo?.status ?? "pending";
  const scriptReady = status?.stages?.adapt?.status === "complete";

  if (isLoading || (!bible && stageStatus !== "pending")) {
    return (
      <RoomShell
        isLoading
        loadingText="SKETCHING THE STORY BIBLE…"
        loadingStage="extract"
        loadingStageStatus={stageStatus}
        loadingStageItemsDone={stageInfo?.items_done}
        loadingStageItemsTotal={stageInfo?.items_total}
      />
    );
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

  const needsApproval = stageStatus === "awaiting_review";
  const styleStarted = status?.stages?.style?.status != null && status.stages.style.status !== "pending";

  function handleLooksRight() {
    if (!id) return;
    if (needsApproval) {
      approveStage.mutate(
        { project: id, stage: "extract" },
        {
          onSuccess: () => {
            // Send the user to the style room so they see samples generate live.
            if (!styleStarted) handleRun(id, "style", { actionLabel: "Propose art styles" });
            navigate(`/project/${id}/styles`);
          },
        },
      );
    } else {
      navigate(`/project/${id}/styles`);
    }
  }

  return (
    <RoomShell>
      <RoomHeader
        kicker="STORY"
        title={bible.title}
        lead="Check what Scenewright read out of your story — fix names, looks, and details before anything is drawn."
      />

      <WhatPulpFound
        bible={bible}
        onReadScript={() => setDrawer("script")}
        scriptReady={scriptReady}
      />

      <div className="grid gap-10 xl:grid-cols-2">
        <section>
          <SectionHeader
            variant="underline"
            kicker="EVERYTHING IS EDITABLE"
            title="Characters"
          />
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

        <section>
          <SectionHeader
            variant="underline"
            kicker="WHERE IT HAPPENS"
            title="Places"
          />
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

      <InspectDrawer project={id} kind={drawer} onClose={() => setDrawer(null)} />

      <ApprovalBar
        next={needsApproval
          ? "Scenewright proposes five art styles drawn from your story"
          : "Pick your art style at the Look station"}
        estimateCredits={needsApproval ? styleEstimate?.estimate_credits : null}
        primaryLabel={needsApproval ? "LOOKS RIGHT — CONTINUE →" : "GO TO LOOK →"}
        onPrimary={handleLooksRight}
        primaryDisabled={approveStage.isPending || isPipelineRunning || stageStatus === "running"}
        busy={approveStage.isPending}
        secondary={<RerunStageAction project={id} stage="extract" label="Re-extract" />}
      />
    </RoomShell>
  );
}
