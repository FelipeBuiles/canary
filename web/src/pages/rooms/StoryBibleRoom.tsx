import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useProjectStatus,
  useStoryBible,
  useUpdateStoryBible,
} from "../../api/queries";
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
import { useI18n } from "../../i18n";

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
      <span className="block font-meta text-[0.62rem] font-bold tracking-[0.1em] text-ink-muted">
        {label} <span className="font-normal text-ink-muted">✎</span>
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
          className="font-display text-[1.55rem] font-black uppercase leading-none tracking-[-0.03em] text-ink-black"
        />
        {showDevContent && (
          <Tag className="shrink-0 border-transparent bg-surface-container px-4 text-[0.66rem] text-ink-black/48">
            {character.id.toUpperCase()}
          </Tag>
        )}
      </div>
      <div className="mt-3 flex items-center gap-2 font-body text-[1rem] font-semibold text-ink-muted">
        <EditableText
          value={character.age_range}
          onSave={(v) => update({ age_range: v })}
          className="text-ink-muted"
        />
        <span>&middot;</span>
        <EditableText
          value={character.gender}
          onSave={(v) => update({ gender: v })}
          className="text-ink-muted"
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
          <span className="font-meta text-[0.56rem] font-bold tracking-[0.08em] text-ink-muted">
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
          className="font-display text-[1.55rem] font-black uppercase leading-none tracking-[-0.03em] text-ink-black"
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
  const { t } = useI18n();
  const opening = bible.scenes[0]?.source_start_quote?.trim();
  return (
    <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
      {/* Source card */}
      <EntityCard className="-rotate-[0.4deg] shadow-paper">
        <div className="font-meta text-[0.58rem] font-bold tracking-[0.1em] text-ink-muted">{t("SOURCE MANUSCRIPT")}</div>
        <h2 className="mt-2 font-display text-[1.9rem] font-black uppercase leading-[0.95] tracking-[-0.04em] text-ink-black">
          {bible.title}
        </h2>
        <div className="mt-2 font-meta text-[0.62rem] font-bold tracking-[0.08em] text-ink-muted">
          {t("BY")} {bible.author.toUpperCase()}
        </div>
        {opening && (
          <p className="mt-4 bg-surface-container px-4 py-3 text-[0.95rem] italic leading-7 text-ink-black/65">
            “{opening}”
          </p>
        )}
      </EntityCard>

      {/* What PULP found card */}
      <EntityCard className="lg:translate-y-4">
        <div className="font-meta text-[0.58rem] font-bold tracking-[0.1em] text-ink-muted">{t("WHAT SCENEWRIGHT FOUND")}</div>
        <dl className="mt-3 space-y-2.5">
          <div className="flex items-baseline justify-between gap-3 border-b border-ink-black/10 pb-2.5">
            <dt className="text-[0.85rem] text-ink-black/60">{t("Scenes")}</dt>
            <dd className="font-body text-[0.95rem] font-bold text-ink-black">
              {bible.total_scenes} · {t("kept in story order")}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-3 border-b border-ink-black/10 pb-2.5">
            <dt className="text-[0.85rem] text-ink-black/60">{t("Cast")}</dt>
            <dd className="font-body text-[0.95rem] font-bold text-ink-black">
              {bible.characters.length} {t("characters")} · {bible.locations.length} {t("places")}
            </dd>
          </div>
        </dl>
        <button
          type="button"
          onClick={onReadScript}
          className="mt-4 inline-flex min-h-11 items-center gap-2 border-[2px] border-ink-black/25 bg-bristol px-3 py-1.5 font-meta text-[0.6rem] font-bold tracking-[0.08em] text-ink-muted transition-colors hover:border-ink-black hover:text-ink-black"
        >
          {t("READ THE SCRIPT")} ▸
          {!scriptReady && (
            <span className="font-meta text-[0.46rem] tracking-[0.1em] text-ink-black/35">{t("WRITES ITSELF LATER")}</span>
          )}
        </button>
      </EntityCard>
    </div>
  );
}

function StorySpine({ bible }: { bible: StoryBible }) {
  const { t } = useI18n();
  if (bible.narrative_arcs.length === 0) return null;

  return (
    <section>
      <SectionHeader
        variant="underline"
        title="STORY SPINE"
        description="The extracted acts and turning points, kept in the order of your manuscript."
      />
      <ol className="flex overflow-x-auto border-[3px] border-ink-black bg-ink-black shadow-paper-sm">
        {bible.narrative_arcs.map((arc) => (
          <li
            key={`${arc.act}-${arc.title}`}
            className="min-w-[230px] flex-1 border-r-[2px] border-bristol/20 bg-ink-black px-5 py-5 text-bristol last:border-r-0"
          >
            <div className="flex items-center justify-between font-meta text-[0.56rem] font-bold tracking-[0.08em] text-bristol/70">
              <span>{t("ACT")} {String(arc.act).padStart(2, "0")}</span>
              <span>{arc.scenes.length} {t("SCENES")}</span>
            </div>
            <h3 className="mt-3 font-display text-[1.2rem] font-black uppercase leading-[0.95] tracking-[-0.03em] text-bristol">
              {arc.title}
            </h3>
            {arc.turning_point && (
              <p className="mt-3 border-t-[2px] border-bristol/18 pt-3 font-body text-[0.78rem] font-semibold leading-5 text-bristol/75">
                {arc.turning_point}
              </p>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function StoryBibleRoom() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: bible, isLoading, error } = useStoryBible(id);
  const { data: status } = useProjectStatus(id);
  const updateBible = useUpdateStoryBible();
  const approveStage = useApproveStage();
  const [drawer, setDrawer] = useState<DrawerKind | null>(null);

  const stageInfo = status?.stages?.extract;
  const stageStatus = stageInfo?.status ?? "pending";
  const scriptReady = status?.stages?.adapt?.status === "complete";

  if (isLoading || (!bible && stageStatus !== "pending")) {
    return (
      <RoomShell
        project={id ?? ""}
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
      <RoomShell project={id ?? ""}>
        <StagePlaceholder
          project={id ?? ""}
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
  function handleLooksRight() {
    if (!id) return;
    if (needsApproval) {
      approveStage.mutate(
        { project: id, stage: "extract" },
        {
          onSuccess: () => {
            // Let the author choose automatic exploration or bring a direction
            // before any style credits are spent.
            navigate(`/project/${id}/styles`);
          },
        },
      );
    } else {
      navigate(`/project/${id}/styles`);
    }
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker="STORY"
        title="CONFIRM THE STORY"
        lead="Check the people, places, and turning points Scenewright found. Edit only what needs correction."
      />

      <WhatPulpFound
        bible={bible}
        onReadScript={() => setDrawer("script")}
        scriptReady={scriptReady}
      />

      <StorySpine bible={bible} />

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
        next="Choose automatic exploration or bring your own visual direction"
        primaryLabel={needsApproval ? "LOOKS RIGHT — CONTINUE →" : "GO TO LOOK →"}
        onPrimary={handleLooksRight}
        primaryDisabled={approveStage.isPending || stageStatus === "running"}
        busy={approveStage.isPending}
        secondary={<RerunStageAction project={id} stage="extract" label="story" />}
      />
    </RoomShell>
  );
}
