import { ErrorNotice } from "../composites/ErrorNotice";
import { ConfirmDrawer } from "../composites/ConfirmDrawer";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { CreditAmount } from "../ui/CreditAmount";
import { useCastFreshness, useKeepReference, useReopenCast } from "../../api/seriesQueries";
import { fetchAssetRegenEstimate, regenLocationState, regenStateRef } from "../../api/pipeline";
import { seedGenerationJob } from "../../api/generationTracking";
import type { ReferenceFreshness } from "../../api/storyBible";
import type { CostEstimate, StageStatus, StoryBible } from "../../types/api";
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

interface Group {
  kind: ReferenceFreshness["kind"];
  entityId: string;
  name: string;
  /** Looks drawn from a main image that has since been redrawn. */
  redrawn: ReferenceFreshness[];
  /** Entries whose description or direction changed, or that have no image yet. */
  changed: ReferenceFreshness[];
}

/**
 * References that no longer match what Cast would draw now, one group per
 * entry. Looks drawn from a since-redrawn main image only need redrawing, so
 * they never send the author to the Story Bible: an edit there would redesign
 * the main image and outdate the looks again. Arriving with
 * ?references=update starts the update.
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
  const lookLabel = (ref: ReferenceFreshness) =>
    ref.state_id ? entities.get(ref.entity_id)?.looks.get(ref.state_id) ?? ref.state_id : null;
  const groups = new Map<string, Group>();
  for (const ref of pending) {
    const key = `${ref.kind}:${ref.entity_id}`;
    const group = groups.get(key) ?? {
      kind: ref.kind, entityId: ref.entity_id, name: entities.get(ref.entity_id)?.name ?? ref.entity_id, redrawn: [], changed: [],
    };
    (ref.status === "outdated" && ref.reason === "parent_redrawn" ? group.redrawn : group.changed).push(ref);
    groups.set(key, group);
  }
  const keepAll = (refs: ReferenceFreshness[]) => {
    for (const ref of refs) keep.mutate({ project, kind: ref.kind, entityId: ref.entity_id, stateId: ref.state_id });
  };

  return (
    <section ref={sectionRef} className="space-y-4 border-[2px] border-ink-black bg-surface-container p-5" aria-label={t("References to update")}>
      <div>
        <h2 className="font-display text-xl font-black uppercase">{t("References to update")}</h2>
        <p className="mt-2 font-body text-sm text-ink-muted">
          {t("These references no longer match what Cast would draw now. Out-of-date images keep serving pages until you update or keep them; new entries need an image before pages can draw them.")}
        </p>
      </div>
      <ul className="divide-y-[2px] divide-ink-black/10">
        {[...groups.values()].map((group) => (
          <li key={`${group.kind}:${group.entityId}`} className="space-y-3 py-3" aria-label={group.name}>
            <div className="flex flex-wrap items-center gap-3">
              <span className="min-w-0 flex-1 font-body text-sm font-bold">{group.name}</span>
              {group.changed.length > 0 && (
                <Link to={{ pathname: "../story", search: `?edit=${group.kind}:${encodeURIComponent(group.entityId)}` }} relative="path"
                  className="inline-flex min-h-11 items-center font-meta text-xs underline underline-offset-4">{t("Edit details")}</Link>
              )}
            </div>
            {group.redrawn.length > 0 && (
              <div className="space-y-2 border-l-[3px] border-ink-black/20 pl-3">
                <p className="font-body text-sm">
                  {t("{count, plural, one {Its main image was redrawn, so this look was drawn from the previous one:} other {Its main image was redrawn, so these # looks were drawn from the previous one:}}", { count: group.redrawn.length })}
                  {" "}<span className="text-ink-muted">{group.redrawn.map(lookLabel).join(" · ")}</span>
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  {group.kind !== "props" && (
                    <RedrawLooks project={project} kind={group.kind === "characters" ? "character" : "location"}
                      entityId={group.entityId} name={group.name} looks={group.redrawn.map((ref) => ref.state_id!)} />
                  )}
                  <Button size="xs" variant="outline" disabled={keep.isPending} onClick={() => keepAll(group.redrawn)}>
                    {group.redrawn.length === 1 ? t("Keep look as it is") : t("Keep looks as they are")}
                  </Button>
                </div>
              </div>
            )}
            {group.changed.map((ref) => (
              <div key={ref.state_id ?? ""} className="flex flex-wrap items-center gap-3">
                <span className="min-w-0 flex-1 font-body text-sm">
                  {lookLabel(ref) ?? t("Main image")}
                  <span className="ml-2 font-meta text-[0.65rem] uppercase tracking-[0.12em] text-ink-muted">
                    {ref.status === "missing" ? t("New, no image yet") : t("Changed since its image")}
                  </span>
                </span>
                {ref.status === "outdated" && (
                  <Button size="xs" variant="outline" disabled={keep.isPending} onClick={() => keepAll([ref])}>
                    {t("Keep current image")}
                  </Button>
                )}
              </div>
            ))}
          </li>
        ))}
      </ul>
      {(keep.error || reopen.error) && <ErrorNotice error={(keep.error ?? reopen.error)} operation="save" />}
      <div className="flex flex-wrap items-center justify-end gap-3">
        <p className="font-body text-xs text-ink-muted">{t("Cast makes the new images and regenerates every changed one you haven't kept. You'll see the cost first.")}</p>
        <Button size="sm" disabled={resumeDisabled || reopen.isPending} onClick={update}>{t("Update images")}</Button>
      </div>
    </section>
  );
}

/** Redraws one entry's outdated looks from its current main image, after a priced confirmation. */
function RedrawLooks({ project, kind, entityId, name, looks }: {
  project: string; kind: "character" | "location"; entityId: string; name: string; looks: string[];
}) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const estimates = useQueries({
    queries: looks.map((look) => ({
      queryKey: ["project", project, "asset-regen-estimate", kind, entityId, look, undefined],
      queryFn: () => fetchAssetRegenEstimate(project, kind, entityId, look),
      staleTime: 60_000,
    })),
  });
  const loaded = estimates.every((query) => query.data);
  const cost: CostEstimate | undefined = loaded && estimates[0]?.data ? {
    ...estimates[0].data,
    estimate_credits: estimates.reduce((sum, query) => sum + (query.data?.estimate_credits ?? 0), 0),
  } : undefined;
  const redraw = useMutation({
    mutationFn: async () => {
      // One job per look, so each lands (and is billed) on its own.
      for (const look of looks) {
        const admitted = kind === "character"
          ? await regenStateRef(project, entityId, look)
          : await regenLocationState(project, entityId, look);
        seedGenerationJob(qc, project, admitted.job);
      }
    },
  });
  return (
    <>
      <Button size="xs" disabled={!cost || redraw.isPending} onClick={() => setConfirming(true)}>
        {looks.length === 1 ? t("Redraw look") : t("Redraw looks")}
        {cost && <> <span aria-hidden="true">·</span> <CreditAmount value={cost.estimate_credits} approximate label={t("credits")} /></>}
      </Button>
      {redraw.error && <ErrorNotice error={redraw.error} operation="generate" />}
      <ConfirmDrawer
        open={confirming}
        title={looks.length === 1 ? t("Redraw look") : t("Redraw looks")}
        body={t("{count, plural, one {Scenewright will redraw {name}'s look from its current main image. The current version stays in history.} other {Scenewright will redraw {name}'s # looks from its current main image. The current versions stay in history.}}", { count: looks.length, name })}
        cost={cost}
        confirmLabel={looks.length === 1 ? t("Redraw look") : t("Redraw looks")}
        onConfirm={() => { setConfirming(false); redraw.mutate(); }}
        onClose={() => setConfirming(false)}
        busy={redraw.isPending}
      />
    </>
  );
}
