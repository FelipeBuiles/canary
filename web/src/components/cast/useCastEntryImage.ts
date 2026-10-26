import { useContext, useEffect } from "react";
import { useCastReference } from "../../hooks/useCastReference";
import { useLiveStageAsset } from "../../hooks/useLiveStageAsset";
import { CastUpdatingContext, STORY_KIND, mainImageUrl, updatingKey, type CastEntry } from "./castAssets";

/**
 * One reference's main image and its generation state. The roster, the sheet
 * and the stage each read it; job state is shared through the query cache.
 * `active` also loads the regeneration estimate, which only the stage needs.
 */
export function useCastEntryImage(project: string, entry: CastEntry, stageRegenerating: boolean, active = false) {
  const id = entry.entity.id;
  const reference = useCastReference(project, entry.kind, id, undefined, active);
  const pendingUpdate = useContext(CastUpdatingContext).has(updatingKey(STORY_KIND[entry.kind], id));
  const { refreshImage } = reference;
  // Reload once this reference's new image lands, not only when the whole run ends.
  useEffect(() => {
    if (!stageRegenerating || !pendingUpdate) {
      const timer = window.setTimeout(() => refreshImage(), 0);
      return () => window.clearTimeout(timer);
    }
  }, [stageRegenerating, pendingUpdate, refreshImage]);
  const live = useLiveStageAsset(mainImageUrl(project, entry.kind, id), reference.timestamp, stageRegenerating);
  // Drawing while the asset is absent, still waiting for the running Cast to
  // redraw it, or while this reference's own regeneration is in flight.
  const isGenerating = (stageRegenerating && (!live.hasImage || pendingUpdate)) || reference.isSubmitting || !!reference.activeJob;
  const isQueued = reference.activeJob?.status === "queued" || !!reference.activeJob?.queue_position;
  return {
    ...reference,
    ...live,
    isGenerating,
    isQueued,
    missing: reference.imgFailed && !live.hasImage,
  };
}
