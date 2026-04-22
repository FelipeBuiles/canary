import { useState } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { SectionLabel } from "../SectionLabel";
import { StatRow } from "../ui/StatRow";
import { DestructiveButton } from "../ui/DestructiveButton";
import { RerunDrawer } from "../ui/RerunDrawer";
import type { StoryBible, Character, Location } from "../../types/api";
import { CharacterCard, LocationCard } from "../../pages/rooms/StoryBibleRoom";
import { useUpdateStoryBible } from "../../api/queries";
import { useI18n } from "../../i18n";
import { RERUN_IMPACT } from "../../lib/rerunImpact";

interface ReviewExtractStepProps {
  storyBible: StoryBible | undefined;
  onApprove: () => void;
  isApproving: boolean;
  onRegenExtract?: () => void;
  isRegenerating?: boolean;
  project?: string;
}

export function ReviewExtractStep({ storyBible, onApprove, isApproving, onRegenExtract, isRegenerating, project }: ReviewExtractStepProps) {
  const updateBible = useUpdateStoryBible();
  const { t } = useI18n();
  const [rerunOpen, setRerunOpen] = useState(false);

  if (!storyBible) {
    return (
      <Card className="flex min-h-[40vh] items-center justify-center p-5">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">{t("LOADING STORY BIBLE…")}</p>
      </Card>
    );
  }

  const handleUpdateCharacter = (updatedChar: Character) => {
    if (!project) return;
    const newBible = {
      ...storyBible,
      characters: storyBible.characters.map(c => c.id === updatedChar.id ? updatedChar : c)
    };
    updateBible.mutate({ project, data: newBible });
  };

  const handleUpdateLocation = (updatedLoc: Location) => {
    if (!project) return;
    const newBible = {
      ...storyBible,
      locations: storyBible.locations.map(l => l.id === updatedLoc.id ? updatedLoc : l)
    };
    updateBible.mutate({ project, data: newBible });
  };

  return (
    <div className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="sage">{t("REVIEW CHECKPOINT")}</SectionLabel>
        <h1 className="mt-4 display-headline">{t("STORY BIBLE")}</h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          Review the extracted story data below. Characters, locations, and scenes
          will drive all downstream rooms.
        </p>
      </Card>

      <Card className="p-5">
        <div className="space-y-2">
          <StatRow label="TITLE">{storyBible.title}</StatRow>
          <StatRow label="AUTHOR">{storyBible.author}</StatRow>
          <StatRow label="SCENES">{storyBible.total_scenes}</StatRow>
          <StatRow label="CHARACTERS">{storyBible.characters.length}</StatRow>
          <StatRow label="LOCATIONS">{storyBible.locations.length}</StatRow>
          <StatRow label="NARRATIVE ARCS">{storyBible.narrative_arcs.length}</StatRow>
        </div>
      </Card>

      {storyBible.characters.length > 0 && (
        <Card className="p-5">
          <div className="border-b-[2px] border-ink-black pb-2 font-display text-[1rem] font-bold tracking-[-0.04em]">
            CHARACTERS
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {storyBible.characters.map((c) => (
              <CharacterCard 
                key={c.id} 
                character={c} 
                onSave={handleUpdateCharacter}
              />
            ))}
          </div>
        </Card>
      )}

      {storyBible.locations.length > 0 && (
        <Card className="p-5">
          <div className="border-b-[2px] border-ink-black pb-2 font-display text-[1rem] font-bold tracking-[-0.04em]">
            LOCATIONS
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {storyBible.locations.map((l) => (
              <LocationCard 
                key={l.id} 
                location={l} 
                onSave={handleUpdateLocation}
              />
            ))}
          </div>
        </Card>
      )}

      <div className="flex items-center gap-4">
        <Button size="lg" onClick={onApprove} disabled={isApproving || isRegenerating}>
          {isApproving ? t("APPROVING…") : t("APPROVE & CONTINUE")}
        </Button>
        {onRegenExtract && (
          <>
            <DestructiveButton
              size="md"
              onClick={() => setRerunOpen(true)}
              disabled={isApproving || isRegenerating}
            >
              {isRegenerating ? t("RE-EXTRACTING…") : t("↺ RE-EXTRACT")}
            </DestructiveButton>
            <RerunDrawer
              open={rerunOpen}
              stageName="Extract"
              impactStages={RERUN_IMPACT.extract.downstream}
              estimatedCost={RERUN_IMPACT.extract.cost}
              costIsPlaceholder={RERUN_IMPACT.extract.costIsPlaceholder}
              itemsAtRisk="Story bible edits and downstream generated work will be replaced."
              confirmLabel="Re-extract"
              busy={isApproving || isRegenerating}
              onConfirm={() => {
                onRegenExtract();
                setRerunOpen(false);
              }}
              onClose={() => setRerunOpen(false)}
            />
          </>
        )}
      </div>
    </div>
  );
}
