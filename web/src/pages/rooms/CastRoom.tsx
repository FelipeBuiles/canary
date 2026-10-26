import { ErrorNotice } from "../../components/composites/ErrorNotice";
import { ErrorDetails } from "../../components/composites/ErrorDetails";
import { CastIdentityReview } from "../../components/composites/CastIdentityReview";
import { useCastReview, useRedrawingCharacters } from "../../api/castReview";
import { LoaderCircle, ScanFace, X } from "lucide-react";
import { FieldLabel, TextField } from "../../components/ui/Field";
import { useCallback, useEffect, useMemo, useState } from "react";
import { castCharacters } from "../../lib/castRoster";
import { msg } from "../../locales/messages";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useProjectStatus,
  useStageEstimate,
  useStoryBible,
  useResetStale,
} from "../../api/queries";
import { useCastFreshness, useFillVisualAnchor } from "../../api/seriesQueries";
import { referencesToUpdate } from "../../components/story/castReferences";
import { ApprovalBar, ConfirmDrawer, RoomHeader, RoomShell, RerunStageAction, StagePlaceholder } from "../../components/composites";
import { useRunAction } from "../../hooks/useRunAction";
import { Button } from "../../components/ui/Button";
import type { CastFailure, ContentTrigger } from "../../types/api";
import { useI18n } from "../../i18n";
import { RoomNotice, RoomNoticeRow, StaleStageNotice } from "../../components/composites";
import { getCastCheckpointAction, isCastReviewBlocker } from "../../lib/castCheckpoint";
import { missingVisualAnchors, type MissingVisualAnchor } from "../../lib/visualAnchor";
import { OutdatedReferences } from "../../components/story/OutdatedReferences";
import { cn } from "../../lib/cn";
import {
  CastSuggestionContext, CastUpdatingContext, looksOf, updatingKey,
  type CastEntry, type CastKind, type CastSuggestion,
} from "../../components/cast/castAssets";
import { CastRoster, type CastAttention, type RosterGroup } from "../../components/cast/CastRoster";
import { CastSheet } from "../../components/cast/CastSheet";
import { CastWorkspace } from "../../components/cast/CastWorkspace";

/** "part0001_scene_003" → "Part 1, scene 3"; other ids read as words. */
function sceneLabel(sceneId: string, t: (key: string, values?: Record<string, string | number>) => string) {
  const match = /^part0*(\d+)_scene_0*(\d+)$/.exec(sceneId);
  if (match) return t("Part {part}, scene {scene}", { part: match[1], scene: match[2] });
  // "scene_the_headless_snug" → "The headless snug"
  const words = sceneId.replace(/^scene_/, "").replace(/_+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : sceneId;
}

const entryKey = (entry: { kind: CastKind; entity: { id: string } }) => `${entry.kind}:${entry.entity.id}`;
const ANCHOR = /^#cast-(character|location|prop)-(.+)$/;

const DARK_BUTTON = "inline-flex h-8 items-center gap-2 border border-pulp-paper/22 px-3 font-meta text-[0.8125rem] font-medium text-pulp-paper transition-colors hover:bg-pulp-paper/8 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold";
const darkSegment = (on: boolean) => cn(
  "inline-flex h-8 items-center px-3 font-meta text-[0.8125rem] font-medium transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-narrator-gold",
  on ? "bg-pulp-paper text-ink-black" : "text-pulp-paper/85 hover:bg-pulp-paper/8 hover:text-pulp-paper",
);

/** Pages need a written look for every entry; a blank one is filled here, not by rerunning Extract. */
export function MissingAnchorsNotice({ projectId, missing }: { projectId: string; missing: MissingVisualAnchor[] }) {
  const { t } = useI18n();
  const fill = useFillVisualAnchor();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  return (
    <section role="alert" aria-labelledby="cast-missing-anchors-title" className="border border-hero-red/70 bg-bristol p-4 shadow-[3px_3px_0_0_var(--color-hero-red)] md:p-5">
      <h2 id="cast-missing-anchors-title" className="font-meta text-xs font-bold tracking-[0.12em] text-hero-red">{t("MISSING DESCRIPTIONS")}</h2>
      <p className="mt-2 font-body text-sm text-ink-black">{t("Pages need a written look for these entries. Add one to continue; nothing already made is redone.")}</p>
      <ul className="mt-3 space-y-3">
        {missing.map((entry) => {
          const draft = drafts[entry.key] ?? "";
          const inputId = `missing-anchor-${entry.key}`;
          return (
            <li key={entry.key}>
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!draft.trim()) return;
                  fill.mutate({ project: projectId, entity_id: entry.entityId, appearance_state_id: entry.stateId, visual_anchor: draft });
                }}
              >
                <div className="min-w-0 flex-1">
                  <FieldLabel htmlFor={inputId}>{t("Describe how {name} looks", { name: entry.name })}</FieldLabel>
                  <TextField id={inputId} value={draft} maxLength={2000} disabled={fill.isPending}
                    onChange={(event) => setDrafts((current) => ({ ...current, [entry.key]: event.target.value }))} />
                </div>
                <Button type="submit" variant="outline" size="sm" disabled={fill.isPending || !draft.trim()}>{t("SAVE")}</Button>
              </form>
            </li>
          );
        })}
      </ul>
      {fill.error && <ErrorNotice error={fill.error} operation="generate" />}
    </section>
  );
}

/** Names each reference that stopped Cast and why, so Resume is never a blind retry. */
/** Direction sent through a card's review after a decline; the author sees and can edit it first. */
const LESS_GRAPHIC_DIRECTION = msg("Make this less graphic so the image provider accepts it. Show it non-explicitly: keep any nudity covered, draped or stylized with no visible breasts, nipples or genitals, and show injuries through framing, shadow or aftermath rather than gore. Keep its identity, materials, colors and design otherwise unchanged.");

const TRIGGER_CATEGORY: Record<ContentTrigger["category"], string> = {
  nudity: msg("nudity"), sexual: msg("sexual content"), gore: msg("gore"), violence: msg("violence"),
};
const TRIGGER_SOURCE: Record<ContentTrigger["source"], string> = {
  description: msg("its description"), direction: msg("its direction"), style: msg("the style notes"), other: msg("the request"),
};
const STORY_KIND: Record<NonNullable<CastFailure["asset_type"]>, string> = {
  character: "characters", location: "locations", prop: "props",
};

export function CastFailureNotice({ failures, onResume, resumeDisabled = false, onLessGraphic, onShow }: {
  failures: CastFailure[];
  /** Puts the failed reference on the stage. */
  onShow?: (kind: CastKind, id: string) => void;
  /** Offered beside the list so every missing reference can be retried at once. */
  onResume?: () => void;
  resumeDisabled?: boolean;
  /** Opens the declined reference's review with less graphic direction to confirm. */
  onLessGraphic?: (failure: CastFailure) => void;
}) {
  const { t } = useI18n();
  if (failures.length === 0) return null;
  const anchor = (failure: CastFailure) => {
    const section = failure.asset_type === "character" ? "character" : failure.asset_type === "location" ? "location" : "prop";
    if (failure.entity_id) return `#cast-${section}-${failure.entity_id}`;
    return failure.asset_type === "character" ? "#cast-characters" : failure.asset_type === "location" ? "#cast-places" : "#cast-props";
  };
  const first = failures[0].label;
  return (
    <RoomNotice tone="danger" role="alert" title={t("Cast stopped")}
      label={failures.length === 1
        ? t("Cast stopped · {name} didn't finish", { name: first })
        : t("Cast stopped · {count} references didn't finish", { count: String(failures.length) })}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 font-body text-sm text-ink-black">{t("These references did not finish. Everything else is kept.")}</p>
        {onResume && (
          <Button variant="secondary" size="sm" disabled={resumeDisabled} onClick={onResume}>
            {t("Resume cast")}
          </Button>
        )}
      </div>
      <ul className="mt-3 space-y-4">
        {failures.map((failure) => {
          const declined = failure.classification === "provider_blocked";
          const triggers = failure.likely_triggers ?? [];
          return (
            <li key={failure.item_id} className="font-body text-sm leading-6 text-ink-black">
              <a href={anchor(failure)} className="font-bold underline decoration-hero-red underline-offset-4"
                onClick={(event) => {
                  if (!onShow || !failure.entity_id || !failure.asset_type) return;
                  event.preventDefault();
                  onShow(failure.asset_type, failure.entity_id);
                }}>{failure.label}</a>
              <span className="block text-ink-black/80">{declined ? t("Model declined this content") : t("This reference could not be completed.")}</span>
              <ErrorDetails error={failure.message} />
              {declined && triggers.length > 0 && (
                <div className="mt-2">
                  <p className="font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("Likely cause")}</p>
                  <ul className="mt-1 space-y-1">
                    {triggers.map((trigger) => (
                      <li key={trigger.phrase}>
                        <mark className="bg-narrator-gold/40 px-1 font-bold text-ink-black">{trigger.phrase}</mark>
                        <span className="text-ink-black/80"> · {t("{category} in {source}", {
                          category: t(TRIGGER_CATEGORY[trigger.category]), source: t(TRIGGER_SOURCE[trigger.source]),
                        })}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {declined && (onLessGraphic || failure.entity_id) && (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  {onLessGraphic && failure.entity_id && failure.asset_type && (
                    <Button size="sm" variant="outline" onClick={() => onLessGraphic(failure)}>{t("Make a less graphic version")}</Button>
                  )}
                  {failure.entity_id && failure.asset_type && (
                    <Link to={{ pathname: "../story", search: `?edit=${STORY_KIND[failure.asset_type]}:${encodeURIComponent(failure.entity_id)}` }} relative="path"
                      className="inline-flex min-h-11 items-center font-meta text-xs underline underline-offset-4">{t("Reword its description")}</Link>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {failures.some((failure) => failure.classification === "provider_blocked") && (
        <p className="mt-4 font-body text-xs text-ink-muted">
          {t("A less graphic version opens the reference with suggested direction and its cost; nothing is generated until you confirm. Rewording the description changes it everywhere the entry appears.")}
        </p>
      )}
    </RoomNotice>
  );
}

/**
 * The Cast run's progress in its own room. The floating indicator stays out
 * of the running stage's screen, so this is the only progress shown here.
 */
function CastRunProgress({ done, total, remaining }: { done: number; total: number; remaining: number }) {
  const { t } = useI18n();
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <section role="status" aria-label={t("Cast progress")} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 font-meta text-[0.8125rem] text-pulp-paper/85">
      <span className="flex items-center gap-2">
        <LoaderCircle size={14} aria-hidden="true" className="text-narrator-gold motion-safe:animate-spin" />
        {t("Drawing cast references")}
      </span>
      {total > 0 && (
        <>
          <span className="tabular-nums text-on-chrome-muted">{done} / {total}</span>
          <span aria-hidden="true" className="relative h-1 w-32 overflow-hidden bg-pulp-paper/15">
            <span className="absolute inset-0 origin-left bg-narrator-gold transition-transform duration-[var(--motion-settle)]"
              style={{ transform: `scaleX(${percent / 100})` }} />
          </span>
        </>
      )}
      {remaining > 0 && (
        <span className="basis-full font-body text-xs text-on-chrome-muted">
          {t("{count, plural, one {# changed reference still to redraw. Its current image stays until the new one lands.} other {# changed references still to redraw. Their current images stay until the new ones land.}}", { count: remaining })}
        </span>
      )}
    </section>
  );
}

export function CastRoom() {
  const { t } = useI18n();
  const location = useLocation();
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"focus" | "sheet">("focus");
  const [checkOpen, setCheckOpen] = useState(false);
  // A #cast-<kind>-<id> link opens that reference.
  const [selectedKey, setSelectedKey] = useState<string | null>(() => {
    const match = ANCHOR.exec(location.hash);
    return match ? `${match[1]}:${decodeURIComponent(match[2])}` : null;
  });
  const [confirmCast, setConfirmCast] = useState(false);
  const [castSuggestion, setCastSuggestion] = useState<CastSuggestion | undefined>();
  const clearCastSuggestion = useCallback(() => setCastSuggestion(undefined), []);
  const suggestionContext = useMemo(() => ({ suggestion: castSuggestion, clear: clearCastSuggestion }), [castSuggestion, clearCastSuggestion]);
  // Set when Continue re-checked the cast; the server approves it if nothing is left to review.
  const [continuing, setContinuing] = useState(false);
  const [actionError, setActionError] = useState<Error | string | null>(null);
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: sourceBible, isLoading } = useStoryBible(id);
  const bible = useMemo(() => sourceBible
    ? { ...sourceBible, characters: castCharacters(sourceBible) } : undefined, [sourceBible]);
  const { data: status } = useProjectStatus(id);
  const approveStage = useApproveStage();
  const { mutate: resetStale, isPending: isResetting, error: resetError } = useResetStale();
  const { handleRun, isPending: isPipelineRunning } = useRunAction();
  // The estimate for Adapt covers the automatic Adapt → Plan chain.
  const { data: chainEstimate } = useStageEstimate(id, "adapt");
  const isCastStageRunning = status?.stages?.cast?.status === "running";
  const stageRegenerating = isCastStageRunning;
  const stageInfo = status?.stages?.cast;
  const stageStatus = stageInfo?.status ?? "pending";
  const missingAnchors = bible ? missingVisualAnchors([...bible.characters, ...bible.locations, ...bible.props]) : [];
  // A missing anchor is fixed in place below; resuming Cast cannot write one.
  const checkpointAction = getCastCheckpointAction(stageStatus, missingAnchors.length ? null : stageInfo?.approval_blocker);
  const isStageStuck = !!stageInfo?.stale;
  const lastProgressAt = stageInfo?.last_progress_at ?? null;
  const needsApproval = checkpointAction === "approve";
  // After corrections every reference exists; only the character comparison is out of date.
  const recheckOnly = checkpointAction === "resume" && isCastReviewBlocker(stageInfo?.approval_blocker);
  const canStartCast = stageStatus === "pending";
  const redrawingCharacters = useRedrawingCharacters(id ?? "");
  const { data: castReview } = useCastReview(id ?? "", !!status?.is_running || redrawingCharacters.size > 0);
  // Any queued or running job (a single redraw included) must finish before approval.
  const projectBusy = !!status?.is_running || redrawingCharacters.size > 0;
  // Character Check notes are advice; approval never waits on them.
  const openCastNotes = castReview?.status === "current" && !castReview.reviewing ? castReview.issues.length : 0;
  const { data: castResumeEstimate } = useStageEstimate(id, "cast", !isCastStageRunning);
  const { data: freshness } = useCastFreshness(id, true, stageRegenerating);
  const updating = useMemo(() => new Set(stageRegenerating
    ? referencesToUpdate(freshness?.references).map((ref) => updatingKey(ref.kind, ref.entity_id, ref.state_id))
    : []), [stageRegenerating, freshness]);

  const groups = useMemo<RosterGroup[]>(() => bible ? [
    { kind: "character", label: t("Characters"), entries: bible.characters.map((entity) => ({ kind: "character" as const, entity })) },
    { kind: "location", label: t("Places"), entries: bible.locations.map((entity) => ({ kind: "location" as const, entity })) },
    { kind: "prop", label: t("Props"), entries: bible.props.map((entity) => ({ kind: "prop" as const, entity })) },
  ] : [], [bible, t]);
  const entries = useMemo(() => groups.flatMap((group) => group.entries), [groups]);
  const selected = entries.find((entry) => entryKey(entry) === selectedKey) ?? entries[0];
  const characterNames = useMemo(() => new Map((bible?.characters ?? []).map((character) => [character.id, character.name])), [bible]);

  function show(kind: CastKind, entityId: string) {
    setSelectedKey(`${kind}:${entityId}`);
    setView("focus");
  }
  function suggest(suggestion: Omit<CastSuggestion, "nonce">) {
    setSearch("");
    setCheckOpen(false);
    show(suggestion.kind, suggestion.entityId);
    setCastSuggestion({ ...suggestion, nonce: Date.now() });
  }

  function startCast() {
    if (!id || !status?.style_selected || !castResumeEstimate) return;
    setActionError(null);
    handleRun(id, "cast", {
      actionLabel: canStartCast ? t("Start cast characters & places") : t("Resume cast characters & places"),
      onSuccess: () => setConfirmCast(false),
      onError: (error) => { setConfirmCast(false); setActionError(error); },
    });
  }

  // A re-check that found something to review (or failed) ends the continue;
  // the footer then shows why. Reset while rendering, not in an effect.
  if (continuing && stageStatus !== "running" && stageStatus !== "complete"
      && !isCastReviewBlocker(stageInfo?.approval_blocker)) {
    setContinuing(false);
  }
  // Once the re-check passes the server approves Cast and starts Adapt; follow it to Pages.
  useEffect(() => {
    if (continuing && id && stageStatus === "complete") navigate(`/project/${id}/pages`);
  }, [continuing, id, stageStatus, navigate]);

  function continueAfterCorrections() {
    if (!id || !status?.style_selected) return;
    setActionError(null);
    setContinuing(true);
    handleRun(id, "cast", {
      thenApprove: true,
      actionLabel: t("Continue"),
      onError: (error) => { setContinuing(false); setActionError(error); },
    });
  }

  function handleContinueToPages() {
    if (!id) return;
    if (recheckOnly) {
      continueAfterCorrections();
    } else if (checkpointAction === "resume" || canStartCast) {
      setConfirmCast(true);
    } else if (checkpointAction === "approve") {
      setActionError(null);
      approveStage.mutate(
        { project: id, stage: "cast" },
        {
          onSuccess: () => {
            navigate(`/project/${id}/pages`);
          },
          onError: (error) => setActionError(error),
        },
      );
    } else if (checkpointAction === "continue") {
      navigate(`/project/${id}/pages`);
    }
  }

  function handleResetStale() {
    if (!id) return;
    resetStale({ project: id });
  }

  function handleContinueStale() {
    if (!id) return;
    setConfirmCast(true);
  }

  if (isLoading || (!bible && stageStatus !== "pending")) {
    return (
      <RoomShell
        project={id ?? ""}
        isLoading
        loadingText="LOADING CAST…"
        loadingStage="cast"
        loadingStageStatus={stageStatus}
        loadingStageItemsDone={stageInfo?.items_done}
        loadingStageItemsTotal={stageInfo?.items_total}
      />
    );
  }

  if (!bible || !id) {
    return (
      <RoomShell project={id ?? ""}>
        <StagePlaceholder
          activeJobs={status?.active_jobs}
          project={id ?? ""}
          stage="cast"
          status={stageStatus}
          itemsDone={stageInfo?.items_done}
          itemsTotal={stageInfo?.items_total}
          error={stageInfo?.error}
          errorDetail={stageInfo?.error_detail}
          errorCode={stageInfo?.error_code}
        />
      </RoomShell>
    );
  }

  const failures = stageInfo?.failures ?? [];
  const outdatedEntities = new Set((freshness?.references ?? [])
    .filter((ref) => ref.status === "outdated")
    .map((ref) => `${ref.kind}:${ref.entity_id}`));
  const attentionOf = (entry: CastEntry): CastAttention | undefined => {
    if (stageRegenerating) return undefined;
    if (failures.some((failure) => failure.entity_id === entry.entity.id && failure.asset_type === entry.kind)) return "failed";
    const storyKind = entry.kind === "character" ? "characters" : entry.kind === "location" ? "locations" : "props";
    return outdatedEntities.has(`${storyKind}:${entry.entity.id}`) ? "outdated" : undefined;
  };
  const firstSceneTitle = (entry: CastEntry) => entry.kind === "prop" && entry.entity.first_appearance_scene
    ? bible.scenes.find((scene) => scene.id === entry.entity.first_appearance_scene)?.title || sceneLabel(entry.entity.first_appearance_scene, t)
    : undefined;
  const subOf = (entry: CastEntry) => {
    const looks = looksOf(entry).length;
    const lookCount = looks > 0 ? t("{count, plural, one {# look} other {# looks}}", { count: looks }) : undefined;
    if (entry.kind === "character") return [entry.entity.age_range, entry.entity.gender, lookCount].filter(Boolean).join(" · ");
    if (entry.kind === "location") return [entry.entity.time_of_day, lookCount].filter(Boolean).join(" · ") || entry.entity.mood;
    const first = firstSceneTitle(entry);
    return first ? `${t("First seen")}: ${first}` : t("Prop");
  };

  const hasNotices = isStageStuck || (!stageRegenerating && missingAnchors.length > 0) || !!resetError || !status?.style_selected;

  const toolbar = (
    <div className="relative flex min-h-14 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 px-5 py-2.5">
      <div role="group" aria-label={t("Cast view")} className="inline-flex border border-pulp-paper/22">
        <button type="button" aria-pressed={view === "focus"} onClick={() => setView("focus")} className={darkSegment(view === "focus")}>{t("Focus")}</button>
        <button type="button" aria-pressed={view === "sheet"} onClick={() => setView("sheet")} className={darkSegment(view === "sheet")}>{t("Sheet")}</button>
      </div>
      {stageRegenerating && stageInfo && <CastRunProgress done={stageInfo.items_done} total={stageInfo.items_total} remaining={updating.size} />}
      {bible.characters.length > 0 && (
        <div className="ml-auto">
          <button type="button" aria-expanded={checkOpen} aria-controls="cast-character-check" onClick={() => setCheckOpen((open) => !open)}
            className={cn(DARK_BUTTON, openCastNotes > 0 && "border-ink-black! bg-narrator-gold! text-ink-black! hover:bg-narrator-gold/90!", checkOpen && openCastNotes === 0 && "bg-pulp-paper/10!")}>
            <ScanFace size={15} aria-hidden="true" />
            {openCastNotes > 0
              ? t("{count, plural, one {Character check · # note} other {Character check · # notes}}", { count: openCastNotes })
              : t("Character check")}
          </button>
          <div id="cast-character-check" hidden={!checkOpen}
            className="absolute right-5 top-full z-30 mt-1 max-h-[min(36rem,70vh)] w-[min(36rem,calc(100vw-2.5rem))] overflow-y-auto border border-ink-black bg-bristol text-ink-black shadow-[6px_6px_0_0_rgb(0_0_0/0.45)]">
            <div className="flex justify-end px-2 pt-2">
              <button type="button" onClick={() => setCheckOpen(false)} aria-label={t("Close")} title={t("Close")}
                className="flex size-8 items-center justify-center text-ink-muted hover:text-ink-black focus-visible:outline-2 focus-visible:outline-hero-red">
                <X size={16} aria-hidden="true" />
              </button>
            </div>
            <CastIdentityReview projectId={id} characters={bible.characters} locations={bible.locations}
              onShowCharacter={(kind, entityId) => { setSearch(""); setCheckOpen(false); show(kind, entityId); }}
              onUseSuggestion={(kind, entityId, text) => suggest({ kind, entityId, text })}
              onResume={handleContinueStale} busy={stageRegenerating || !status?.style_selected}
              redrawing={redrawingCharacters} />
          </div>
        </div>
      )}
    </div>
  );

  return (
    <RoomShell project={id} bleed>
      <RoomHeader
        title={t("Cast")}
        lead={[
          t("{count, plural, one {# character} other {# characters}}", { count: bible.characters.length }),
          t("{count, plural, one {# place} other {# places}}", { count: bible.locations.length }),
          bible.props.length > 0 ? t("{count, plural, one {# prop} other {# props}}", { count: bible.props.length }) : undefined,
        ].filter(Boolean).join(" · ")}
      />

      {hasNotices && (
        <div className="space-y-3 px-4 pt-4 sm:px-6 studio-desktop:px-5">
          {isStageStuck && (
            <StaleStageNotice
              lastProgressAt={lastProgressAt}
              onContinue={handleContinueStale}
              onReset={handleResetStale}
              continuing={isPipelineRunning}
              resetting={isResetting}
              stageLabel="CAST"
              itemLabel="cast images"
            />
          )}
          {!stageRegenerating && missingAnchors.length > 0 && <MissingAnchorsNotice projectId={id} missing={missingAnchors} />}
          {resetError && <ErrorNotice error={resetError} operation="save" />}
          {!status?.style_selected && <p className="font-body text-sm text-ink-muted">{t("Choose a style before starting cast references.")}</p>}
        </div>
      )}
      {/* A queued run is already updating them; is_running covers queued as well as running jobs. */}
      {!stageRegenerating && !status?.is_running && (
        <RoomNoticeRow className="empty:hidden">
          <CastFailureNotice
            failures={failures}
            onShow={(kind, entityId) => { setSearch(""); show(kind, entityId); }}
            onLessGraphic={(failure) => suggest({
              kind: failure.asset_type!, entityId: failure.entity_id!, stateId: failure.state_id, text: t(LESS_GRAPHIC_DIRECTION),
            })}
            onResume={checkpointAction === "resume" ? () => setConfirmCast(true) : undefined}
            resumeDisabled={isPipelineRunning || !status?.style_selected || !castResumeEstimate}
          />
          <OutdatedReferences project={id} bible={bible} castStatus={stageStatus}
            onResume={() => setConfirmCast(true)} resumeDisabled={isPipelineRunning || !status?.style_selected} ready={!!status} />
        </RoomNoticeRow>
      )}

      <CastUpdatingContext.Provider value={updating}>
      <CastSuggestionContext.Provider value={suggestionContext}>
        <div className={cn("flex min-h-[34rem] flex-1 flex-col studio-desktop:min-h-0 studio-desktop:flex-row", hasNotices && "mt-4 border-t border-ink-black/12")}>
          {view === "focus" && (
            <CastRoster project={id} groups={groups} subOf={subOf} selectedKey={selected ? entryKey(selected) : null}
              stageRegenerating={stageRegenerating} attentionOf={attentionOf}
              search={search} onSearch={setSearch} onSelect={(entry) => show(entry.kind, entry.entity.id)} />
          )}
          {view === "focus" && selected ? (
            <CastWorkspace
              key={entryKey(selected)}
              project={id}
              entry={selected}
              sub={subOf(selected)}
              toolbar={toolbar}
              stageRegenerating={stageRegenerating}
              characterNames={characterNames}
              firstSceneTitle={firstSceneTitle(selected)}
              onShow={show}
            />
          ) : (
            <section aria-label={t("References")} className="benday-ink flex min-w-0 flex-1 flex-col text-pulp-paper">
              {toolbar}
              <CastSheet project={id} groups={groups} stageRegenerating={stageRegenerating} attentionOf={attentionOf}
                onOpen={(entry) => show(entry.kind, entry.entity.id)} />
            </section>
          )}
        </div>
      </CastSuggestionContext.Provider>
      </CastUpdatingContext.Provider>

      <ConfirmDrawer
        open={confirmCast}
        title={canStartCast ? t("Start cast characters & places") : t("Resume cast characters & places")}
        body={t("Current references are reused. Missing or outdated references are regenerated, then character identities are compared. Replaced artwork stays in version history.")}
        cost={castResumeEstimate}
        confirmLabel={canStartCast ? t("Start cast") : t("Resume cast")}
        onConfirm={startCast}
        onClose={() => setConfirmCast(false)}
        busy={isPipelineRunning || !castResumeEstimate}
      />
      {!projectBusy && !stageRegenerating && !isPipelineRunning && !continuing && <ApprovalBar
        next={canStartCast ? t("Start the character and place references when you are ready")
          : missingAnchors.length > 0
          ? t("Add the missing descriptions above to continue")
          : recheckOnly
          ? t("Scenewright checks your corrected cast, then adapts the book and plans every page")
          : checkpointAction === "resume"
          ? failures.length > 0
            ? t("{count, plural, one {# reference didn't finish. Resume to draw it.} other {# references didn't finish. Resume to draw them.}}", { count: failures.length })
            : stageInfo?.approval_blocker ?? t("Some references didn't finish. Resume to draw the missing images.")
          : needsApproval && openCastNotes > 0
          ? t("{count, plural, one {# character note is open} other {# character notes are open}}. You can still continue; notes are advice.", { count: openCastNotes })
          : needsApproval
          ? t("Your cast is ready. Scenewright adapts the book and plans every page next.")
          : stageStatus === "complete"
            ? t("Review your finished pages in Pages")
            : t("Scenewright is drawing your cast")}
        estimateCredits={recheckOnly
          ? (castResumeEstimate && chainEstimate ? castResumeEstimate.estimate_credits + chainEstimate.estimate_credits : undefined)
          : canStartCast || checkpointAction === "resume"
          ? castResumeEstimate?.estimate_credits
          : needsApproval
            ? chainEstimate?.estimate_credits
            : null}
        primaryLabel={canStartCast ? t("Start cast")
          : checkpointAction === "resume" && !recheckOnly
          ? t("Resume cast")
          : recheckOnly || needsApproval
            ? t("Continue to Pages")
            : t("Go to Pages")}
        onPrimary={handleContinueToPages}
        primaryDisabled={approveStage.isPending || isPipelineRunning || projectBusy || (!canStartCast && missingAnchors.length > 0) || (!canStartCast && checkpointAction === "wait") || ((canStartCast || checkpointAction === "resume") && (!status?.style_selected || !castResumeEstimate))}
        busy={approveStage.isPending || isPipelineRunning || continuing}
        error={actionError}
        secondary={<RerunStageAction project={id} stage="cast" label="cast" disabled={stageRegenerating} />}
      />}
    </RoomShell>
  );
}
