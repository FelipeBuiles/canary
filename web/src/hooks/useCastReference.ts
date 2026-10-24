import { isInsufficientCreditsError } from "../api/client";
import { useCallback } from "react";
import { useAssetRegenEstimate, useRegenRef, useRegenStateRef, useRegenLocationState, useRegenRefWithInstruction, useRegenPlate, useRegenPlateWithInstruction, useRegenProp, useRegenPropWithInstruction } from "../api/queries";
import type { CastReferenceInput, GenerationJob } from "../types/api";
import { useReferenceJob } from "./useReferenceJob";

/** One author action owns admission, credit recovery, errors and image refresh. */
export function useCastReference(project: string, kind: "character" | "location" | "prop", entityId: string, stateId?: string, estimateEnabled = true) {
  const job = useReferenceJob(project, kind === "character" ? "char_id" : kind === "location" ? "loc_id" : "prop_id", entityId, stateId);
  const character = useRegenRef();
  const characterState = useRegenStateRef();
  const location = useRegenPlate();
  const locationState = useRegenLocationState();
  const prop = useRegenProp();
  const characterEdit = useRegenRefWithInstruction();
  const locationEdit = useRegenPlateWithInstruction();
  const propEdit = useRegenPropWithInstruction();
  const { data: estimate } = useAssetRegenEstimate(project, kind, entityId, stateId, estimateEnabled);
  const { setTimestamp, setImgFailed } = job;
  const refreshImage = useCallback(() => setTimestamp(Date.now()), [setTimestamp]);
  const imageFailed = () => setImgFailed(true);
  const pending = [character, characterState, location, locationState, prop, characterEdit, locationEdit, propEdit].some(mutation => mutation.isPending);
  /** ``withLooks`` redraws a main image's looks from the new image in the same job. */
  const regenerate = (text?: string, referenceAssets?: CastReferenceInput[], withLooks = false) => {
    const instruction = text?.trim();
    if (text !== undefined && !instruction) return;
    job.setRegenError(null);
    const submit = (): Promise<{ job: GenerationJob }> => {
      if (instruction) {
        const args = { project, stateId, instruction, referenceAssets, withLooks: !stateId && withLooks };
        if (kind === "character") return characterEdit.mutateAsync({ ...args, charId: entityId });
        if (kind === "location") return locationEdit.mutateAsync({ ...args, locId: entityId });
        return propEdit.mutateAsync({ ...args, propId: entityId });
      }
      if (kind === "character") return stateId
        ? characterState.mutateAsync({ project, charId: entityId, stateId })
        : character.mutateAsync({ project, charId: entityId, withLooks });
      if (kind === "location") return stateId
        ? locationState.mutateAsync({ project, locId: entityId, stateId })
        : location.mutateAsync({ project, locId: entityId, withLooks });
      return prop.mutateAsync({ project, propId: entityId });
    };
    void job.start({ identity: kind === "character" ? "char_id" : kind === "location" ? "loc_id" : "prop_id", value: stateId ? `${entityId}:${stateId}` : entityId }, submit, {
      actionLabel: stateId ? "Regenerate appearance" : `Regenerate ${kind}`,
      onRetry: () => regenerate(text, referenceAssets, withLooks),
    }).then(data => job.setActiveJob(data.job)).catch((error: Error) => { if (!isInsufficientCreditsError(error)) job.setRegenError(error.message); });
  };
  return { imgFailed: job.imgFailed, imageFailed, timestamp: job.timestamp, refreshImage, activeJob: job.activeJob, instructionDraft: job.instructionDraft, referenceDraft: job.referenceDraft, regenError: job.regenError, estimate, regenerate, isSubmitting: pending || job.isSubmitting };
}
