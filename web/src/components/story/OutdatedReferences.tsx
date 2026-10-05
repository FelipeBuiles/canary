import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { useCastFreshness, useKeepReference, useReopenCast } from "../../api/seriesQueries";
import type { StageStatus, StoryBible } from "../../types/api";
import { referencesToUpdate } from "./castReferences";

interface Props {
  project: string;
  bible: StoryBible;
  castStatus: StageStatus;
  /** Opens Cast's resume confirmation, with its estimate. */
  onResume: () => void;
  resumeDisabled?: boolean;
  /** False until the project status that decides resumeDisabled has loaded. */
  ready?: boolean;
}

/**
 * References the author's Story Bible edits changed or added. An outdated one
 * keeps serving pages until the author keeps it or regenerates it; a missing
 * one waits for Cast. Arriving with ?references=update starts the update.
 */
export function OutdatedReferences({ project, bible, castStatus, onResume, resumeDisabled = false, ready = true }: Props) {
  const { t } = useI18n();
  const { data, isFetching } = useCastFreshness(project);
  const keep = useKeepReference();
  const reopen = useReopenCast();
  const pending = referencesToUpdate(data?.references);
  const [search, setSearch] = useSearchParams();
  const sectionRef = useRef<HTMLElement>(null);
  const requested = useRef(search.get("references") === "update");
  // An approved Cast reopens first; a pending one resumes directly.
  const approved = castStatus === "complete" || castStatus === "awaiting_review";
  const update = () => {
    if (!approved) { onResume(); return; }
    reopen.mutate({ project }, { onSuccess: onResume });
  };
  useEffect(() => {
    // Wait for a fresh report: a cached one can predate the edit.
    if (!requested.current || !data || isFetching || !ready) return;
    requested.current = false;
    setSearch((params) => { params.delete("references"); return params; }, { replace: true });
    if (!pending.length) return;
    sectionRef.current?.scrollIntoView?.({ block: "start" });
    if (!resumeDisabled) update();
  });
  if (!pending.length) return null;
  const entities = new Map<string, { name: string; looks: Map<string, string> }>(
    [...bible.characters, ...bible.locations, ...bible.props].map((entity) => [entity.id, {
      name: entity.name,
      looks: new Map((entity.appearance_states ?? []).map((look) => [look.id, look.label])),
    }]),
  );

  return (
    <section ref={sectionRef} className="space-y-4 border-[2px] border-ink-black bg-surface-container p-5" aria-label={t("References to update")}>
      <div>
        <h2 className="font-display text-xl font-black uppercase">{t("References to update")}</h2>
        <p className="mt-2 font-body text-sm text-ink-muted">
          {t("Your Story Bible edits changed or added these entries. Changed ones keep their current images until you keep or regenerate them; new ones need an image before pages can draw them.")}
        </p>
      </div>
      <ul className="divide-y-[2px] divide-ink-black/10">
        {pending.map((ref) => {
          const entity = entities.get(ref.entity_id);
          const look = ref.state_id ? entity?.looks.get(ref.state_id) ?? ref.state_id : null;
          return (
            <li key={`${ref.entity_id}:${ref.state_id ?? ""}`} className="flex flex-wrap items-center gap-3 py-3">
              <span className="min-w-0 flex-1 font-body text-sm">
                <span className="font-bold">{entity?.name ?? ref.entity_id}</span>
                {look && <span className="text-ink-muted"> · {look}</span>}
                <span className="ml-2 font-meta text-[0.65rem] uppercase tracking-[0.12em] text-ink-muted">
                  {ref.status === "missing" ? t("New, no image yet") : t("Changed since its image")}
                </span>
              </span>
              <Link to={{ pathname: "../story", search: `?edit=${ref.kind}:${encodeURIComponent(ref.entity_id)}` }} relative="path"
                className="inline-flex min-h-11 items-center font-meta text-xs underline underline-offset-4">{t("Edit details")}</Link>
              {ref.status === "outdated" && (
                <Button size="xs" variant="outline" disabled={keep.isPending}
                  onClick={() => keep.mutate({ project, kind: ref.kind, entityId: ref.entity_id, stateId: ref.state_id })}>
                  {t("Keep current image")}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      {(keep.error || reopen.error) && <p role="alert" className="font-body text-sm text-hero-red">{(keep.error ?? reopen.error)?.message}</p>}
      <div className="flex flex-wrap items-center justify-end gap-3">
        <p className="font-body text-xs text-ink-muted">{t("Cast makes the new images and regenerates every changed one you haven't kept. You'll see the cost first.")}</p>
        <Button size="sm" disabled={resumeDisabled || reopen.isPending} onClick={update}>{t("Update images")}</Button>
      </div>
    </section>
  );
}
