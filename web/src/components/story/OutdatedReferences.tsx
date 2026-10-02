import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { useCastFreshness, useKeepReference, useReopenCast } from "../../api/seriesQueries";
import type { StageStatus, StoryBible } from "../../types/api";

interface Props {
  project: string;
  bible: StoryBible;
  castStatus: StageStatus;
  /** Opens Cast's resume confirmation, with its estimate. */
  onResume: () => void;
  resumeDisabled?: boolean;
}

/**
 * References whose entity the author edited. Each one keeps serving pages
 * until the author keeps it as it is or regenerates it through Cast.
 */
export function OutdatedReferences({ project, bible, castStatus, onResume, resumeDisabled = false }: Props) {
  const { t } = useI18n();
  const { data } = useCastFreshness(project);
  const keep = useKeepReference();
  const reopen = useReopenCast();
  const outdated = (data?.references ?? []).filter((ref) => ref.status === "outdated");
  if (!outdated.length) return null;
  const entities = new Map<string, { name: string; looks: Map<string, string> }>(
    [...bible.characters, ...bible.locations, ...bible.props].map((entity) => [entity.id, {
      name: entity.name,
      looks: new Map((entity.appearance_states ?? []).map((look) => [look.id, look.label])),
    }]),
  );
  // An approved Cast reopens first; a pending one resumes directly.
  const approved = castStatus === "complete" || castStatus === "awaiting_review";

  return (
    <section className="space-y-4 border-[2px] border-ink-black bg-surface-container p-5" aria-label={t("Out-of-date references")}>
      <div>
        <h2 className="font-display text-xl font-black uppercase">{t("Out-of-date references")}</h2>
        <p className="mt-2 font-body text-sm text-ink-muted">
          {t("These entries changed in the Story Bible after their images were made. Pages keep using the current images until you keep them as they are or regenerate them.")}
        </p>
      </div>
      <ul className="divide-y-[2px] divide-ink-black/10">
        {outdated.map((ref) => {
          const entity = entities.get(ref.entity_id);
          const look = ref.state_id ? entity?.looks.get(ref.state_id) ?? ref.state_id : null;
          return (
            <li key={`${ref.entity_id}:${ref.state_id ?? ""}`} className="flex flex-wrap items-center gap-3 py-3">
              <span className="min-w-0 flex-1 font-body text-sm">
                <span className="font-bold">{entity?.name ?? ref.entity_id}</span>
                {look && <span className="text-ink-muted"> · {look}</span>}
              </span>
              <Link to={{ pathname: "../story", search: `?edit=${ref.kind}:${encodeURIComponent(ref.entity_id)}` }} relative="path"
                className="inline-flex min-h-11 items-center font-meta text-xs underline underline-offset-4">{t("Edit details")}</Link>
              <Button size="xs" variant="outline" disabled={keep.isPending}
                onClick={() => keep.mutate({ project, kind: ref.kind, entityId: ref.entity_id, stateId: ref.state_id })}>
                {t("Keep current image")}
              </Button>
            </li>
          );
        })}
      </ul>
      {(keep.error || reopen.error) && <p role="alert" className="font-body text-sm text-hero-red">{(keep.error ?? reopen.error)?.message}</p>}
      <div className="flex flex-wrap items-center justify-end gap-3">
        <p className="font-body text-xs text-ink-muted">{t("Regenerating resumes Cast for every out-of-date image you haven't kept.")}</p>
        <Button size="sm" disabled={resumeDisabled || reopen.isPending} onClick={() => {
          if (!approved) { onResume(); return; }
          reopen.mutate({ project }, { onSuccess: onResume });
        }}>{t("Regenerate out-of-date images")}</Button>
      </div>
    </section>
  );
}
