import { useMemo } from "react";
import { placementChecks, type PlacementEvidence } from "@lettering-engine";
import type { LetteringEvidence, PageLettering } from "../api/lettering";

export function engineEvidence(evidence: LetteringEvidence): PlacementEvidence {
  const read = evidence.page_read;
  return {
    panels: evidence.panels, speakers: evidence.speakers, heads: read?.heads ?? null,
    stray_lettering: read?.stray_lettering ?? [], in_world_text: read?.in_world_text ?? [],
  };
}

export function useChecks(state: PageLettering | null, evidence: LetteringEvidence) {
  return useMemo(() => state ? placementChecks(state, engineEvidence(evidence)) : [], [state, evidence]);
}
