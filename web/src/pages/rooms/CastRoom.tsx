import { useGenerationTracking } from "../../hooks/useGenerationTracking";
import { ErrorNotice } from "../../components/composites/ErrorNotice";
import { ErrorDetails } from "../../components/composites/ErrorDetails";
import { CastRegenAction } from "../../components/composites/CastRegenAction";
import { CastIdentityReview } from "../../components/composites/CastIdentityReview";
import { useCastReview, useRedrawingCharacters } from "../../api/castReview";
import { ArrowUpRight, Search, Users, MapPin, Box, LoaderCircle, ImagePlus, Expand } from "lucide-react";
import { FieldLabel, TextField } from "../../components/ui/Field";
import { useCastReference } from "../../hooks/useCastReference";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { castCharacters } from "../../lib/castRoster";
import { msg } from "../../locales/messages";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useProjectStatus,
  useStageEstimate,
  useStoryBible,
  useCastAssetVersions,
  useRestoreCastAssetVersion,
  useImageGenerationMeta,
  useResetStale,
} from "../../api/queries";
import { useCastFreshness, useFillVisualAnchor } from "../../api/seriesQueries";
import { referencesToUpdate } from "../../components/story/castReferences";
import { ApprovalBar, ConfirmDrawer, RoomHeader, RoomShell, RerunStageAction, StagePlaceholder, SectionHeader, EntityCard } from "../../components/composites";
import { useRunAction } from "../../hooks/useRunAction";
import { useLiveStageAsset } from "../../hooks/useLiveStageAsset";
import { Tag } from "../../components/ui/Tag";
import { Button } from "../../components/ui/Button";
import { ImageModal } from "../../components/ui/ImageModal";
import { useImageViewer } from "../../hooks/useImageViewer";
import { GenerationDetailsPanel } from "../../components/ui/GenerationDetailsModal";
import { LazyImage } from "../../components/ui/LazyImage";
import type { AppearanceState, CastFailure, CastReferenceInput, Character, ContentTrigger, GenerationJob, Location, Prop } from "../../types/api";
import { useI18n } from "../../i18n";
import { ImageGenerationPreview } from "../../components/composites/ImageGenerationPreview";
import { StaleStageNotice } from "../../components/composites";
import { getCastCheckpointAction, isCastReviewBlocker } from "../../lib/castCheckpoint";
import { missingVisualAnchors, readableAnchor, type MissingVisualAnchor } from "../../lib/visualAnchor";
import { seriesPath } from "../../api/projectScope";
import type { EntityKind } from "../../api/storyBible";
import { OutdatedReferences } from "../../components/story/OutdatedReferences";

function queuedLabel(job: GenerationJob | null) {
  if (!job) return "QUEUED";
  if (job.status === "running") return "RUNNING";
  if (job.queue_position) return `QUEUE ${job.queue_position}`;
  return "QUEUED";
}

const REF_VIEWS = [
  { pose: "portrait", label: "Portrait" },
  { pose: "full_body", label: "Full body" },
] as const;

/**
 * Read-only derived views sent to the image model. Panel framing chooses the
 * portrait for close shots and the full-body crop for other shots.
 */
function ReferenceViews({ projectName, charId, timestamp }: { projectName: string; charId: string; timestamp: string | number }) {
  const { t } = useI18n();
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  const inspector = useImageViewer();
  const visiblePoses = REF_VIEWS.filter(({ pose }) => !failed[pose]);
  if (visiblePoses.length === 0) return null;
  const poseImages = visiblePoses.map(({ pose, label }) => ({
    src: `/api${seriesPath(projectName)}/files/refs/${encodeURIComponent(charId)}/${pose}.png?t=${encodeURIComponent(timestamp)}`,
    alt: `${t(label)} ${t("reference")}`,
  }));

  return (
    <div>
      <div className="font-meta text-xs tracking-[0.12em] text-ink-muted mb-3">
        {t("REFERENCE VIEWS")}
        <span className="mt-1 block font-body text-sm tracking-normal text-ink-muted">{t("Selected automatically to suit each shot.")}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {visiblePoses.map(({ pose, label }, position) => (
          <button
            type="button"
            key={pose}
            title={t("Zoom and inspect")}
            aria-label={`${t("Zoom and inspect")} · ${poseImages[position].alt}`}
            onClick={() => inspector.open(poseImages, position)}
            className="relative w-[104px] max-w-full cursor-zoom-in overflow-hidden border border-ink-black/15 transition-colors hover:border-ink-black/50 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
          >
            <img
              src={poseImages[position].src}
              alt={poseImages[position].alt}
              className="aspect-square w-full object-cover"
              onError={() => setFailed((f) => ({ ...f, [pose]: true }))}
            />
            <span className="block bg-ink-black/5 px-2 py-2 text-center font-meta text-xs tracking-normal text-ink-muted">
              {t(label)}
            </span>
          </button>
        ))}
      </div>
      {inspector.viewer}
    </div>
  );
}

/**
 * Per-state appearance refs (silver hands, stumps, collapsed building, …).
 * Each visually-significant state gets its own generated ref under
 * refs/<id>/states/<state>/ (characters) or plates/<id>/states/<state>.png (locations).
 * States whose ref hasn't been generated yet (or failed) show a compact status
 * rather than vanishing, so the gap is visible.
 */
/** The looks a main-image job redraws after it (its ``with_looks`` payload). */
function redrawnLooks(job: GenerationJob | null | undefined): readonly string[] | undefined {
  const looks = job?.payload.with_looks;
  return Array.isArray(looks) ? looks.filter((look): look is string => typeof look === "string") : undefined;
}

export function StateRefRow({
  projectName,
  entityId,
  kind,
  states,
  stageRegenerating,
  refreshToken,
  redrawing,
}: {
  projectName: string;
  entityId: string;
  kind: "character" | "location";
  states: AppearanceState[] | undefined;
  stageRegenerating: boolean;
  refreshToken: string | null;
  /** Looks the main image's running job redraws once its new image lands. */
  redrawing?: readonly string[];
}) {
  const { t } = useI18n();
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const [viewer, setViewer] = useState<AppearanceState | null>(null);
  const [viewerInstruction, setViewerInstruction] = useState<string | null>(null);
  const [restoredAt, setRestoredAt] = useState<Record<string, number>>({});
  useCastSuggestion(kind, entityId, (text, stateId) => {
    const state = states?.find((item) => item.id === stateId);
    if (state) { setViewer(state); setViewerInstruction(text); }
  }, true);

  const significant = (states ?? []).filter((s) => s.visually_significant);
  const tracking = useGenerationTracking(projectName, significant.length > 0);
  const { data: status } = useProjectStatus(projectName);
  const stateFailure = (stateId: string) => castFailureFor(status?.stages?.cast?.failures, entityId, stateId);
  const updating = useContext(CastUpdatingContext);
  const stateUpdating = (stateId: string) => updating.has(updatingKey(kind === "character" ? "characters" : "locations", entityId, stateId));
  const { data: freshness } = useCastFreshness(projectName, significant.length > 0);
  const outdated = new Set((freshness?.references ?? [])
    .filter((ref) => ref.entity_id === entityId && ref.state_id && ref.status === "outdated"
      && ref.kind === (kind === "character" ? "characters" : "locations"))
    .map((ref) => ref.state_id));
  if (significant.length === 0) return null;
  const stateJob = (stateId: string) => tracking.status({
    identity: kind === "character" ? "char_id" : "loc_id", value: `${entityId}:${stateId}`, currentStyle: true,
  });
  const version = (stateId: string) => {
    const job = stateJob(stateId);
    // The pending marker drops when the running Cast redraws this look, so the tile reloads then.
    return encodeURIComponent(`${refreshToken ?? "current"}${restoredAt[stateId] ? `-restored-${restoredAt[stateId]}` : ""}${job ? `-${job.id}-${job.status}` : ""}${stateUpdating(stateId) ? "-updating" : ""}`);
  };

  const base = `/api${seriesPath(projectName)}/files`;
  const thumbUrl = (stateId: string) =>
    kind === "character"
      ? `${base}/refs/${encodeURIComponent(entityId)}/states/${encodeURIComponent(stateId)}/portrait.png?v=${version(stateId)}`
      : `${base}/plates/${encodeURIComponent(entityId)}/states/${encodeURIComponent(stateId)}.png?v=${version(stateId)}`;


  const tileWidth = "flex w-60 max-w-full shrink-0 items-center gap-3 p-2";
  const imgAspect = "h-12 w-12 shrink-0 overflow-hidden";

  return (
    <div className="mt-4">
      <div className="font-meta text-xs tracking-[0.12em] text-ink-muted mb-3">
        {t("Alternate appearances")} · {significant.length}
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {significant.map((s) => {
          const src = thumbUrl(s.id);
          const job = stateJob(s.id);
          // A missing look is drawn by any Cast run; an existing one only while it is still pending update.
          const generating = (stageRegenerating && (failed[src] || stateUpdating(s.id))) || job?.status === "queued" || job?.status === "running"
            || !!redrawing?.includes(s.id);
          const failure = generating ? undefined : stateFailure(s.id);
          const frameClass = `${imgAspect} bg-surface-container`;
          const labelClass = "block min-w-0 break-words text-left font-body text-sm leading-snug text-ink-black";

          // A state tile is only unknown while its own file is absent. Each
          // poll changes the URL, so `failed` re-tests rather than latching.
          return failed[src] ? (
            <button
              type="button"
              onClick={() => setViewer(s)}
              aria-label={`${t("Review & adjust")} · ${s.label}`}
              key={s.id}
              title={
                generating
                  ? t("Being generated by the cast stage")
                  : t("Review & adjust")
              }
              className={`${tileWidth} overflow-hidden border-[2px] ${generating ? "border-ink-black/20" : failure ? "border-hero-red" : "border-dashed border-ink-black/20"}`}
            >
              <div className={`${frameClass} flex items-center justify-center text-ink-muted`} aria-hidden="true">
                {generating
                  ? <LoaderCircle size={20} className="motion-safe:animate-spin" />
                  : <ImagePlus size={20} />}
              </div>
              <span className={labelClass}>
                <span className="line-clamp-2" title={s.label}>{s.label}</span>
                <span role="status" className={`mt-1 block text-xs ${failure ? "text-hero-red" : "text-ink-muted"}`}>
                  {generating ? t("Generating appearance…")
                    : failure ? (failure.classification === "provider_blocked" ? t("Declined — review & adjust") : t("Failed — review & adjust"))
                    : t("Not generated yet")}
                </span>
              </span>
            </button>
          ) : (
            <button
              key={s.id}
              type="button"
              title={`${s.label} — ${t("click for full size")}`}
              aria-label={`${t("Open image")} · ${s.label}`}
              onClick={() => setViewer(s)}
              className={`${tileWidth} overflow-hidden border-[2px] border-ink-black/15 transition-colors hover:border-ink-black/50 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red`}
            >
              <div className={`${frameClass} relative`}>
                <img
                  src={src}
                  alt={`${s.label} ${t("reference")}`}
                  loading="lazy"
                  className={`h-full w-full object-cover ${generating ? "opacity-40" : ""}`}
                  onError={() => setFailed((f) => ({ ...f, [src]: true }))}
                />
                {generating && <LoaderCircle size={18} aria-hidden="true" className="absolute inset-0 m-auto text-ink-black motion-safe:animate-spin" />}
              </div>
              <span className={labelClass}><span className="line-clamp-2" title={s.label}>{s.label}</span><span role={generating ? "status" : undefined} className={`mt-1 block text-xs ${!generating && outdated.has(s.id) ? "text-hero-red" : "text-ink-muted"}`}>{generating ? t("Updating…") : outdated.has(s.id) ? t("Out of date · review & adjust") : t("Review & adjust")}</span></span>
            </button>
          );
        })}
      </div>
      {viewer && <StateAppearanceModal projectName={projectName} entityId={entityId} kind={kind}
        state={viewer} failure={stateFailure(viewer.id)} stageRegenerating={stageRegenerating}
        initialInstruction={viewerInstruction} onClose={() => { setViewer(null); setViewerInstruction(null); }}
        onRestored={() => setRestoredAt((previous) => ({ ...previous, [viewer.id]: Date.now() }))} />}

    </div>
  );
}

function StateAppearanceModal({ projectName, entityId, kind, state, failure, stageRegenerating, initialInstruction = null, onClose, onRestored }: {
  projectName: string; entityId: string; kind: "character" | "location";
  state: AppearanceState; failure?: CastFailure; stageRegenerating: boolean;
  /** Suggested direction to review, e.g. a less graphic version after a decline. */
  initialInstruction?: string | null;
  onClose: () => void; onRestored: () => void;
}) {
  const { t } = useI18n();
  const job = useCastReference(projectName, kind, entityId, state.id);
  const [instruction, setInstruction] = useState<string | null>(initialInstruction);
  const estimate = job.estimate;
  const busy = job.isSubmitting || !!job.activeJob;
  const src = `/api${seriesPath(projectName)}/files/${kind === "character"
    ? `refs/${encodeURIComponent(entityId)}/states/${encodeURIComponent(state.id)}/sheet.png`
    : `plates/${encodeURIComponent(entityId)}/states/${encodeURIComponent(state.id)}.png`}?t=${job.timestamp}`;
  const submit = job.regenerate;
  return <ImageModal isOpen onClose={onClose} src={src} alt={state.label} title={state.label}
    imageAvailable={!job.imgFailed} emptyLabel={t("NOT GENERATED")}
    generationStatus={busy || (stageRegenerating && job.imgFailed) ? (job.activeJob?.status === "queued" ? t("QUEUED") : t("DRAWING…")) : undefined}
    sidebar={<div className="space-y-5">
      <AnchorSection anchor={state.visual_anchor} />
      {failure && !busy && <ErrorNotice error={failure.message} operation="generate" title="This reference could not be completed." />}
      <img src={src} alt="" className="hidden" onError={() => job.imageFailed()} />
      <CastRegenAction projectName={projectName} assetType={kind} assetId={entityId} stateId={state.id}
        assetLabel={state.label} cost={estimate} hasImage={!job.imgFailed} busy={busy}
        busyLabel={job.activeJob ? queuedLabel(job.activeJob) : t("DRAWING…")}
        instruction={instruction ?? job.instructionDraft} onInstructionChange={setInstruction}
        error={job.regenError} onRegenerate={() => submit()} onRegenerateWithInstruction={submit} />
      <RefVersionHistory projectName={projectName} assetType={kind} assetId={entityId} stateId={state.id} busy={busy || stageRegenerating}
        refreshKey={job.timestamp} onRestored={() => { job.refreshImage(); onRestored(); }} />
    </div>} />;
}

/**
 * Re-roll history for a character or location (main or alternate appearance). Renders
 * nothing until at least one prior version has been archived, so it stays out
 * of the way until you've actually re-rolled. Includes the selected version;
 * clicking another thumbnail restores it.
 */
function RefVersionHistory({
  projectName,
  assetType,
  assetId,
  stateId,
  refreshKey,
  onRestored,
  busy = false,
}: {
  projectName: string;
  assetType: "character" | "location";
  assetId: string;
  stateId?: string;
  refreshKey?: unknown;
  onRestored?: () => void;
  busy?: boolean;
}) {
  const { t } = useI18n();
  const { data, error, isPending } = useCastAssetVersions(projectName, assetType, assetId, stateId, refreshKey);
  const restore = useRestoreCastAssetVersion();
  const versions = data?.versions ?? [];
  if (isPending) return <p className="font-body text-sm text-ink-muted">{t("Loading version history…")}</p>;
  if (error) return <p role="alert" className="font-body text-sm text-hero-red">{t("Version history could not be loaded.")}</p>;
  if (!versions.some((v) => !v.current)) return null;

  const fileUrl = (relPath: string) =>
    `/api${seriesPath(projectName)}/files/${relPath}`;

  return (
    <section aria-label={t("Versions")} className="mt-1.5">
      <h3 className="font-meta text-xs uppercase tracking-[0.1em] text-ink-muted">
        {t("Versions")} ({versions.length})
      </h3>
      <div className="mt-2 flex flex-wrap items-start gap-2">
        {versions.map((v) => (
          <button
            key={`${v.version}-${v.image_path}`}
            type="button"
            title={`${v.current ? t("Selected version") : t("Restore")} v${v.version}`}
            aria-label={`${v.current ? t("Selected version") : t("Restore")} v${v.version}`}
            aria-pressed={!!v.current}
            disabled={!!v.current || busy || restore.isPending}
            onClick={() =>
              restore.mutate(
                { project: projectName, assetType, assetId, version: v.version, stateId },
                { onSuccess: () => onRestored?.() },
              )
            }
            className={`relative w-20 overflow-hidden border-[2px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red ${v.current ? "border-ink-black shadow-ink" : "border-ink-black/20 hover:border-ink-black"} ${busy || restore.isPending ? "opacity-50" : ""}`}
          >
            <img src={`${fileUrl(v.image_path)}${v.current ? `?t=${encodeURIComponent(String(refreshKey ?? "current"))}` : ""}`} alt="" className="aspect-square w-full object-cover" />
            <span className={`block bg-bristol px-1 py-1 font-meta text-xs ${v.current ? "text-ink-black" : "text-ink-muted"}`}>
              v{v.version}
              {v.current && <span className="mt-1 block break-words font-bold">{t("Selected")}</span>}
            </span>
          </button>
        ))}
      {restore.error && <ErrorNotice error={restore.error} operation="save" />}
      </div>
    </section>
  );
}

/** A reference's look in reader terms. Internal subject-count tags stay hidden. */
function AnchorSection({ anchor }: { anchor: string }) {
  const { t } = useI18n();
  const readable = readableAnchor(anchor);
  return (
    <section aria-label={t("VISUAL ANCHOR")}>
      <h3 className="font-meta text-xs text-ink-muted">{t("VISUAL ANCHOR")}</h3>
      <p className="mt-1 break-words text-sm leading-6 text-ink-black">{readable}</p>
    </section>
  );
}

/** Rows every cast card spans so siblings align: image · name · look · traits · alternates · action. */
const CAST_CARD_ROWS = 6;
// No row gap: a subgrid would absorb it into every section. Cards space
// themselves with a bottom margin instead.
// Card minimums, not viewport breakpoints, decide column counts.
const CAST_GRID = "grid gap-x-5";
// Each card's wrapper carries its anchor and search visibility, and passes the
// CAST_CARD_ROWS rows through (Tailwind needs the literal row-span-6).
const CAST_GRID_ITEM = "row-span-6 mb-8 grid min-w-0 scroll-mt-24 grid-rows-subgrid gap-y-0";

/** "part0001_scene_003" → "Part 1, scene 3"; other ids read as words. */
function sceneLabel(sceneId: string, t: (key: string, values?: Record<string, string | number>) => string) {
  const match = /^part0*(\d+)_scene_0*(\d+)$/.exec(sceneId);
  if (match) return t("Part {part}, scene {scene}", { part: match[1], scene: match[2] });
  // "scene_the_headless_snug" → "The headless snug"
  const words = sceneId.replace(/^scene_/, "").replace(/_+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : sceneId;
}

function CastCard({
  projectName,
  entityId,
  editKind,
  name,
  aspect,
  imageSrc,
  imageWidth,
  imageHeight,
  probe,
  generating,
  queued,
  generatingCaption,
  missing,
  missingLabel,
  stageRegenerating,
  onOpen,
  onImageError,
  meta,
  tags,
  summary,
  alternates,
  error,
}: {
  projectName: string;
  entityId: string;
  /** Where "Edit details" opens this entry in the Story Bible editor. */
  editKind: EntityKind;
  name: string;
  aspect: "square" | "wide";
  imageSrc: string;
  imageWidth: number;
  imageHeight: number;
  probe: ReactNode;
  generating: boolean;
  queued: boolean;
  generatingCaption: string;
  missing: boolean;
  missingLabel: string;
  stageRegenerating: boolean;
  onOpen: () => void;
  onImageError: () => void;
  meta?: string;
  tags: string[];
  summary?: string;
  alternates: ReactNode;
  error: string | null;
}) {
  const { t } = useI18n();
  const { data: status } = useProjectStatus(projectName);
  const failure = !generating && !stageRegenerating ? castFailureFor(status?.stages?.cast?.failures, entityId, null) : undefined;
  const ratio = aspect === "wide" ? "16 / 9" : "1 / 1";
  const ratioClass = aspect === "wide" ? "aspect-[16/9]" : "aspect-square";

  return (
    <EntityCard subgridRows={CAST_CARD_ROWS} className="min-w-0">
      <button
        type="button"
        className="group relative block w-full cursor-zoom-in bg-surface-container text-left focus-visible:outline-[3px] focus-visible:outline-offset-[-3px] focus-visible:outline-hero-red disabled:cursor-wait"
        onClick={onOpen}
        aria-label={`${t("Open image")} · ${name}`}
      >
        {probe}
        <ImageGenerationPreview project={projectName} target={decodeURIComponent(imageSrc.split("/files/")[1]?.split("?")[0] ?? "")}
          active={generating} finalSrc={!missing ? imageSrc : undefined} aspect={ratio}
          label={queued ? t("QUEUED") : t("DRAWING…")} caption={generatingCaption}>
        {missing ? (
          <div className={`flex ${ratioClass} h-full w-full flex-col items-center justify-center gap-2 p-4 text-center`}>
            <div className={`font-meta text-xs font-bold tracking-[0.08em] ${failure ? "text-hero-red" : "text-ink-muted"}`}>
              {failure ? t("LAST ATTEMPT FAILED") : missingLabel}
            </div>
            <div className="font-meta text-xs tracking-[0.06em] text-ink-black/70">{t("OPEN TO GENERATE")}</div>
          </div>
        ) : (
          <>
            <LazyImage
              preserveAspectBox
              src={imageSrc}
              alt={name}
              loading="lazy"
              width={imageWidth}
              height={imageHeight}
              aspect={ratio}
              containerClassName={`${ratioClass} w-full`}
              className="object-contain"
              onError={onImageError}
            />
            <span
              aria-hidden="true"
              className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center border-[2px] border-bristol bg-ink-black/75 text-bristol transition-colors group-hover:bg-hero-red group-focus-visible:bg-hero-red"
            >
              <Expand size={15} />
            </span>
          </>
        )}
        </ImageGenerationPreview>
      </button>

      <div className="min-w-0 px-5 pt-4">
        <h3 className="line-clamp-2 text-balance font-display text-[1.45rem] font-black leading-[1.08] tracking-[-0.03em] text-ink-black" title={name}>
          {name}
        </h3>
        {meta && <p className="mt-1.5 font-body text-sm text-ink-muted [overflow-wrap:anywhere]">{meta}</p>}
      </div>

      <div className="min-w-0 px-5 pt-3">
        {summary && <p className="line-clamp-3 break-words font-body text-sm leading-6 text-ink-black/80">{summary}</p>}
      </div>

      <div className="min-w-0 px-5">
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-3">
            {tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
          </div>
        )}
      </div>

      <div className="min-w-0 px-5">{alternates}</div>

      <div className="min-w-0 px-5 pb-5 pt-5">
        <Button variant="outline" size="sm" className="w-full" onClick={onOpen} aria-label={`${t("Review & adjust")} · ${name}`}>
          <ArrowUpRight size={16} aria-hidden="true" />{t("Review & adjust")}
        </Button>
        <Link
          to={{ pathname: "../story", search: `?edit=${editKind}:${encodeURIComponent(entityId)}` }}
          relative="path"
          className="mt-3 inline-flex min-h-11 items-center font-meta text-xs text-ink-muted underline underline-offset-4 hover:text-ink-black"
        >
          {t("Edit details")}
        </Link>
        {error && (
          <ErrorNotice error={error} operation="generate" />
        )}
      </div>
    </EntityCard>
  );
}

type CastSuggestion = { kind: "character" | "location" | "prop"; entityId: string; stateId?: string | null; text: string; nonce: number };
const CastSuggestionContext = createContext<{ suggestion?: CastSuggestion; clear: () => void }>({ clear: () => undefined });

/**
 * References the running Cast stage has yet to redraw. An existing image is
 * not proof of a finished reference: while Cast updates changed entries,
 * their old images stay on disk until each new one lands.
 */
const CastUpdatingContext = createContext<ReadonlySet<string>>(new Set());
const updatingKey = (kind: EntityKind, entityId: string, stateId: string | null = null) => `${kind}:${entityId}:${stateId ?? ""}`;

/**
 * Opens one reference's review with suggested direction, once per suggestion.
 * Opening never spends: the author still reviews the direction and its cost.
 * `states` targets the entity's appearance states instead of its main image.
 */
function useCastSuggestion(kind: CastSuggestion["kind"], entityId: string, open: (text: string, stateId: string | null) => void, states = false) {
  const { suggestion, clear } = useContext(CastSuggestionContext);
  const [opened, setOpened] = useState<number | null>(null);
  const match = suggestion && suggestion.kind === kind && suggestion.entityId === entityId && !!suggestion.stateId === states
    ? suggestion : undefined;
  if (match && match.nonce !== opened) {
    setOpened(match.nonce);
    open(match.text.trim().slice(0, 500), match.stateId ?? null);
  }
  useEffect(() => {
    if (match && match.nonce === opened) clear();
  }, [match, opened, clear]);
}

function CharacterCastCard({
  character,
  projectName,
  stageRegenerating,
}: {
  character: Character;
  projectName: string;
  stageRegenerating: boolean;
}) {
  const refUrl = `/api${seriesPath(projectName)}/files/refs/${encodeURIComponent(character.id)}/sheet.png`;
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { imgFailed, imageFailed, timestamp, refreshImage, activeJob, isSubmitting, instructionDraft, regenError, regenerate, estimate: regenEstimate } =
    useCastReference(projectName, "character", character.id, undefined, isModalOpen);
  const [instruction, setInstruction] = useState<string | null>(null);
  useCastSuggestion("character", character.id, (text) => { setInstruction(text); setIsModalOpen(true); });
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `refs/${character.id}/sheet.png`,
    isModalOpen,
    timestamp,
  );


  const pendingUpdate = useContext(CastUpdatingContext).has(updatingKey("characters", character.id));
  // Reload once this reference's new image lands, not only when the whole run ends.
  useEffect(() => {
    if (!stageRegenerating || !pendingUpdate) {
      const timer = window.setTimeout(() => {
        refreshImage();
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [stageRegenerating, pendingUpdate, refreshImage]);

  const startRegen = (withLooks: boolean) => regenerate(undefined, undefined, withLooks);
  const submitInstruction = (text: string, referenceAssets: CastReferenceInput[], withLooks: boolean) => {
    if (!text.trim()) return;
    setInstruction(text.trim());
    regenerate(text, referenceAssets, withLooks);
  };
  // Looks this card's running job redraws after its main image.
  const redrawingLooks = redrawnLooks(activeJob);
  const isInstructionBusy = isSubmitting;

  const { t } = useI18n();
  const { hasImage, imageSrc, probe } = useLiveStageAsset(refUrl, timestamp, stageRegenerating);
  // A card shows drawing while its asset is absent, still waiting for the
  // running Cast to redraw it, or while this card's own regeneration is in flight.
  const isGenerating = (stageRegenerating && (!hasImage || pendingUpdate)) || isInstructionBusy || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <CastCard
        projectName={projectName}
        entityId={character.id}
        editKind="characters"
        name={character.name}
        aspect="square"
        imageSrc={imageSrc}
        imageWidth={320}
        imageHeight={320}
        probe={probe}
        generating={isGenerating}
        queued={!!isQueued}
        generatingCaption={activeJob ? t("GENERATING NEW REF") : t("REBUILDING CAST REF")}
        missing={imgFailed && !hasImage}
        missingLabel={t("NO REF IMAGE")}
        stageRegenerating={stageRegenerating}
        onOpen={() => setIsModalOpen(true)}
        onImageError={() => imageFailed()}
        meta={[character.age_range, character.gender].filter(Boolean).join(" · ")}
        tags={character.distinguishing_features.slice(0, 3)}
        summary={readableAnchor(character.visual_anchor)}
        alternates={(
          <StateRefRow
            projectName={projectName}
            entityId={character.id}
            kind="character"
            states={character.appearance_states}
            stageRegenerating={stageRegenerating}
            refreshToken={timestamp.toString()}
            redrawing={redrawingLooks}
          />
        )}
        error={regenError}
      />
      <ImageModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        src={imageSrc}
        imageAvailable={!imgFailed || hasImage}
        emptyLabel={t("NO REF IMAGE")}
        generationStatus={isGenerating ? (isQueued ? t("QUEUED") : t("DRAWING…")) : undefined}
        alt={character.name}
        title={character.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <AnchorSection anchor={character.visual_anchor} />
            <CastRegenAction
              projectName={projectName} assetType="character" assetId={character.id}
              assetLabel={character.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed || hasImage}
              busy={isInstructionBusy || !!activeJob}
              busyLabel={isQueued ? t("QUEUED") : t("DRAWING…")}
              error={regenError}
              instruction={instruction ?? instructionDraft}
              onInstructionChange={setInstruction}
              onRegenerate={startRegen}
              onRegenerateWithInstruction={submitInstruction}
            />
            <ReferenceViews projectName={projectName} charId={character.id} timestamp={timestamp} />
            <RefVersionHistory
              projectName={projectName}
              assetType="character" assetId={character.id}
              refreshKey={timestamp}
              busy={stageRegenerating || isGenerating || isInstructionBusy}
              onRestored={() => {
                refreshImage();
              }}
            />
            <StateRefRow projectName={projectName} entityId={character.id} kind="character" states={character.appearance_states} stageRegenerating={stageRegenerating} refreshToken={timestamp} redrawing={redrawingLooks} />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">AGE</div>
                <p className="text-[0.82rem] text-ink-black">{character.age_range}</p>
              </div>
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">GENDER</div>
                <p className="text-[0.82rem] text-ink-black">{character.gender}</p>
              </div>
            </div>
            {character.default_outfit && (
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">DEFAULT OUTFIT</div>
                <p className="text-[0.82rem] leading-6 text-ink-black">{character.default_outfit}</p>
              </div>
            )}
            {character.distinguishing_features.length > 0 && (
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-2">DISTINGUISHING FEATURES</div>
                <div className="flex flex-wrap gap-1.5">
                  {character.distinguishing_features.map((f) => (
                    <Tag key={f}>{f}</Tag>
                  ))}
                </div>
              </div>
            )}
            {character.relationships.length > 0 && (
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-2">RELATIONSHIPS</div>
                <ul className="space-y-1.5">
                  {character.relationships.map((r) => (
                    <li key={r.character_id} className="text-[0.78rem] leading-5 text-ink-black/80">
                      <span className="font-semibold capitalize">{r.character_id.replace(/_/g, " ")}</span>
                      <span className="text-ink-black/50"> — {r.relationship}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <GenerationDetailsPanel metadata={generationMeta} isLoading={isMetaLoading} />
          </div>
        )}
        actions={(
          <Button variant="outline" size="sm" onClick={() => setIsModalOpen(false)}>
            {t("CLOSE")}
          </Button>
        )}
      />
    </>
  );
}

function LocationPlateCard({
  location,
  projectName,
  stageRegenerating,
}: {
  location: Location;
  projectName: string;
  stageRegenerating: boolean;
}) {
  const plateUrl = `/api${seriesPath(projectName)}/files/plates/${encodeURIComponent(location.id)}.png`;
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { imgFailed, imageFailed, timestamp, refreshImage, activeJob, isSubmitting, instructionDraft, regenError, regenerate, estimate: regenEstimate } =
    useCastReference(projectName, "location", location.id, undefined, isModalOpen);
  const [instruction, setInstruction] = useState<string | null>(null);
  useCastSuggestion("location", location.id, (text) => { setInstruction(text); setIsModalOpen(true); });
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `plates/${location.id}.png`,
    isModalOpen,
    timestamp,
  );


  const pendingUpdate = useContext(CastUpdatingContext).has(updatingKey("locations", location.id));
  // Reload once this reference's new image lands, not only when the whole run ends.
  useEffect(() => {
    if (!stageRegenerating || !pendingUpdate) {
      const timer = window.setTimeout(() => {
        refreshImage();
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [stageRegenerating, pendingUpdate, refreshImage]);

  const startRegen = (withLooks: boolean) => regenerate(undefined, undefined, withLooks);
  const submitInstruction = (text: string, referenceAssets: CastReferenceInput[], withLooks: boolean) => {
    if (!text.trim()) return;
    setInstruction(text.trim());
    regenerate(text, referenceAssets, withLooks);
  };
  // Looks this card's running job redraws after its main image.
  const redrawingLooks = redrawnLooks(activeJob);
  const isInstructionBusy = isSubmitting;

  const { t } = useI18n();
  const { hasImage, imageSrc, probe } = useLiveStageAsset(plateUrl, timestamp, stageRegenerating);
  // A card shows drawing while its asset is absent, still waiting for the
  // running Cast to redraw it, or while this card's own regeneration is in flight.
  const isGenerating = (stageRegenerating && (!hasImage || pendingUpdate)) || isInstructionBusy || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <CastCard
        projectName={projectName}
        entityId={location.id}
        editKind="locations"
        name={location.name}
        aspect="wide"
        imageSrc={imageSrc}
        imageWidth={480}
        imageHeight={270}
        probe={probe}
        generating={isGenerating}
        queued={!!isQueued}
        generatingCaption={activeJob ? t("GENERATING NEW PLATE") : t("REBUILDING LOCATION PLATE")}
        missing={imgFailed && !hasImage}
        missingLabel={t("NO PLATE IMAGE")}
        stageRegenerating={stageRegenerating}
        onOpen={() => setIsModalOpen(true)}
        onImageError={() => imageFailed()}
        tags={[location.time_of_day, location.mood].filter((tag): tag is string => !!tag)}
        summary={readableAnchor(location.visual_anchor)}
        alternates={(
          <StateRefRow
            projectName={projectName}
            entityId={location.id}
            kind="location"
            states={location.appearance_states}
            stageRegenerating={stageRegenerating}
            refreshToken={timestamp.toString()}
            redrawing={redrawingLooks}
          />
        )}
        error={regenError}
      />
      <ImageModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        src={imageSrc}
        imageAvailable={!imgFailed || hasImage}
        emptyLabel={t("NO PLATE IMAGE")}
        generationStatus={isGenerating ? (isQueued ? t("QUEUED") : t("DRAWING…")) : undefined}
        alt={location.name}
        title={location.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <CastRegenAction
              projectName={projectName} assetType="location" assetId={location.id}
              assetLabel={location.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed || hasImage}
              busy={isInstructionBusy || !!activeJob}
              busyLabel={isQueued ? t("QUEUED") : t("DRAWING…")}
              error={regenError}
              instruction={instruction ?? instructionDraft}
              onInstructionChange={setInstruction}
              onRegenerate={startRegen}
              onRegenerateWithInstruction={submitInstruction}
            />
            <RefVersionHistory projectName={projectName} assetType="location" assetId={location.id}
              refreshKey={timestamp} busy={stageRegenerating || isGenerating || isInstructionBusy}
              onRestored={() => { refreshImage(); }} />
            <StateRefRow projectName={projectName} entityId={location.id} kind="location" states={location.appearance_states} stageRegenerating={stageRegenerating} refreshToken={timestamp} redrawing={redrawingLooks} />
            <AnchorSection anchor={location.visual_anchor} />
            <div className="flex flex-wrap gap-3">
              {location.time_of_day && (
                <div>
                  <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">TIME OF DAY</div>
                  <Tag>{location.time_of_day}</Tag>
                </div>
              )}
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">MOOD</div>
                <Tag>{location.mood}</Tag>
              </div>
            </div>
            <GenerationDetailsPanel metadata={generationMeta} isLoading={isMetaLoading} />
          </div>
        )}
        actions={(
          <Button variant="outline" size="sm" onClick={() => setIsModalOpen(false)}>
            {t("CLOSE")}
          </Button>
        )}
      />
    </>
  );
}

function PropRefCard({
  prop,
  projectName,
  stageRegenerating,
  firstSceneTitle,
}: {
  prop: Prop;
  projectName: string;
  stageRegenerating: boolean;
  /** The Story Bible title of the prop's first scene, when this series knows it. */
  firstSceneTitle?: string;
}) {
  const refUrl = `/api${seriesPath(projectName)}/files/refs/props/${encodeURIComponent(prop.id)}/ref.png`;
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { imgFailed, imageFailed, timestamp, refreshImage, activeJob, isSubmitting, instructionDraft, regenError, regenerate, estimate: regenEstimate } =
    useCastReference(projectName, "prop", prop.id, undefined, isModalOpen);
  const [instruction, setInstruction] = useState<string | null>(null);
  useCastSuggestion("prop", prop.id, (text) => { setInstruction(text); setIsModalOpen(true); });
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `refs/props/${prop.id}/ref.png`,
    isModalOpen,
    timestamp,
  );


  const pendingUpdate = useContext(CastUpdatingContext).has(updatingKey("props", prop.id));
  // Reload once this reference's new image lands, not only when the whole run ends.
  useEffect(() => {
    if (!stageRegenerating || !pendingUpdate) {
      const timer = window.setTimeout(() => {
        refreshImage();
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [stageRegenerating, pendingUpdate, refreshImage]);

  const startRegen = (withLooks: boolean) => regenerate(undefined, undefined, withLooks);
  const submitInstruction = (text: string, referenceAssets: CastReferenceInput[], withLooks: boolean) => {
    if (!text.trim()) return;
    setInstruction(text.trim());
    regenerate(text, referenceAssets, withLooks);
  };
  const isInstructionBusy = isSubmitting;

  const { t } = useI18n();
  const firstSceneLabel = prop.first_appearance_scene ? firstSceneTitle || sceneLabel(prop.first_appearance_scene, t) : undefined;
  const { hasImage, imageSrc, probe } = useLiveStageAsset(refUrl, timestamp, stageRegenerating);
  // A card shows drawing while its asset is absent, still waiting for the
  // running Cast to redraw it, or while this card's own regeneration is in flight.
  const isGenerating = (stageRegenerating && (!hasImage || pendingUpdate)) || isInstructionBusy || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <CastCard
        projectName={projectName}
        entityId={prop.id}
        editKind="props"
        name={prop.name}
        aspect="square"
        imageSrc={imageSrc}
        imageWidth={400}
        imageHeight={400}
        probe={probe}
        generating={isGenerating}
        queued={!!isQueued}
        generatingCaption={activeJob ? t("GENERATING NEW PROP") : t("REBUILDING PROP REF")}
        missing={imgFailed && !hasImage}
        missingLabel={t("NO REF IMAGE")}
        stageRegenerating={stageRegenerating}
        onOpen={() => setIsModalOpen(true)}
        onImageError={() => imageFailed()}
        meta={firstSceneLabel ? `${t("First seen")}: ${firstSceneLabel}` : undefined}
        tags={[]}
        summary={readableAnchor(prop.visual_anchor)}
        alternates={null}
        error={regenError}
      />
      <ImageModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        src={imageSrc}
        imageAvailable={!imgFailed || hasImage}
        emptyLabel={t("NO REF IMAGE")}
        generationStatus={isGenerating ? (isQueued ? t("QUEUED") : t("DRAWING…")) : undefined}
        alt={prop.name}
        title={prop.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <CastRegenAction
              projectName={projectName} assetType="prop" assetId={prop.id}
              assetLabel={prop.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed || hasImage}
              busy={isInstructionBusy || !!activeJob}
              busyLabel={isQueued ? t("QUEUED") : t("DRAWING…")}
              error={regenError}
              instruction={instruction ?? instructionDraft}
              onInstructionChange={setInstruction}
              onRegenerate={startRegen}
              onRegenerateWithInstruction={submitInstruction}
            />
            <AnchorSection anchor={prop.visual_anchor} />
            {prop.first_appearance_scene && (
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">FIRST APPEARANCE</div>
                <p className="text-[0.82rem] text-ink-black [overflow-wrap:anywhere]">{firstSceneLabel}</p>
              </div>
            )}
            <GenerationDetailsPanel metadata={generationMeta} isLoading={isMetaLoading} />
          </div>
        )}
        actions={(
          <Button variant="outline" size="sm" onClick={() => setIsModalOpen(false)}>
            {t("CLOSE")}
          </Button>
        )}
      />
    </>
  );
}


function castFailureFor(failures: CastFailure[] | undefined, entityId: string, stateId: string | null) {
  return failures?.find((failure) => failure.entity_id === entityId && failure.state_id === stateId);
}

/** Pages need a written look for every entry; a blank one is filled here, not by rerunning Extract. */
export function MissingAnchorsNotice({ projectId, missing }: { projectId: string; missing: MissingVisualAnchor[] }) {
  const { t } = useI18n();
  const fill = useFillVisualAnchor();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  return (
    <section role="alert" aria-labelledby="cast-missing-anchors-title" className="border-[3px] border-hero-red bg-surface-container p-4 md:p-5">
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

export function CastFailureNotice({ failures, onResume, resumeDisabled = false, onLessGraphic }: {
  failures: CastFailure[];
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
  return (
    <section role="alert" aria-labelledby="cast-failures-title" className="border-[3px] border-hero-red bg-surface-container p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 id="cast-failures-title" className="font-meta text-xs font-bold tracking-[0.12em] text-hero-red">{t("CAST STOPPED")}</h2>
          <p className="mt-2 font-body text-sm text-ink-black">{t("These references did not finish. Everything else is kept.")}</p>
        </div>
        {onResume && (
          <Button variant="outline" size="sm" disabled={resumeDisabled} onClick={onResume}>
            {t("RESUME CAST")}
          </Button>
        )}
      </div>
      <ul className="mt-3 space-y-4">
        {failures.map((failure) => {
          const declined = failure.classification === "provider_blocked";
          const triggers = failure.likely_triggers ?? [];
          return (
            <li key={failure.item_id} className="font-body text-sm leading-6 text-ink-black">
              <a href={anchor(failure)} className="font-bold underline decoration-hero-red underline-offset-4">{failure.label}</a>
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
    </section>
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
    <section role="status" aria-label={t("Cast progress")} className="space-y-2 border-[2px] border-ink-black bg-bristol p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 font-meta text-xs font-bold uppercase tracking-[0.08em]">
          <LoaderCircle size={14} aria-hidden="true" className="motion-safe:animate-spin" />
          {t("Drawing cast references")}
        </p>
        {total > 0 && <span className="font-meta text-xs tabular-nums text-ink-muted">{done} / {total}</span>}
      </div>
      {total > 0 && (
        <div className="relative h-2 w-full overflow-hidden border border-ink-black bg-pulp-paper">
          <div className="absolute inset-0 origin-left bg-narrator-gold transition-transform duration-[var(--motion-settle)]"
            style={{ transform: `scaleX(${percent / 100})` }} />
        </div>
      )}
      {remaining > 0 && (
        <p className="font-body text-xs text-ink-muted">
          {t("{count, plural, one {# changed reference still to redraw. Its current image stays until the new one lands.} other {# changed references still to redraw. Their current images stay until the new ones land.}}", { count: remaining })}
        </p>
      )}
    </section>
  );
}

export function CastRoom() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
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

  const matches = (entity: { name: string }) => entity.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase());
  const matchingCharacters = bible.characters.filter(matches).length;
  const matchingLocations = bible.locations.filter(matches).length;
  const matchingProps = bible.props.filter(matches).length;
  const matchCount = matchingCharacters + matchingLocations + matchingProps;

  return (
    <RoomShell project={id}>
      <RoomHeader
        title="CONFIRM CHARACTERS & PLACES"
        lead="These approved references guide every complete page. Open only the people or places that need a fix."
      />

      <section className="bg-ink-black p-6 text-pulp-paper shadow-paper md:p-8">
        <div className="grid gap-6 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] md:items-end">
          <div>
            <h2 className="font-display text-3xl font-black uppercase leading-tight tracking-[-0.03em] md:text-4xl">{t("Meet your cast")}</h2>
            <p className="mt-3 font-body text-sm leading-7 text-pulp-paper/85">{t("The faces, places and objects that make your story recognizable. Open a reference to inspect it, adjust its direction or explore another version.")}</p>
            <p className="mt-4 font-meta text-xs text-narrator-gold">{bible.title}</p>
          </div>
          <nav aria-label={t("Browse cast references")} className="flex flex-wrap gap-x-5 gap-y-2">
            <a href="#cast-characters" onClick={() => setSearch("")} className="inline-flex min-h-11 items-center gap-2 font-meta text-xs text-pulp-paper underline decoration-narrator-gold underline-offset-8"><Users size={16} aria-hidden="true" />{bible.characters.length} {t("Characters")}</a>
            <a href="#cast-places" onClick={() => setSearch("")} className="inline-flex min-h-11 items-center gap-2 font-meta text-xs text-pulp-paper underline decoration-narrator-gold underline-offset-8"><MapPin size={16} aria-hidden="true" />{bible.locations.length} {t("Places")}</a>
            {bible.props.length > 0 && <a href="#cast-props" onClick={() => setSearch("")} className="inline-flex min-h-11 items-center gap-2 font-meta text-xs text-pulp-paper underline decoration-narrator-gold underline-offset-8"><Box size={16} aria-hidden="true" />{bible.props.length} {t("Props")}</a>}
          </nav>
        </div>
      </section>

      <div className="flex flex-wrap items-end justify-between gap-4 bg-surface-container p-4">
        <div className="w-full sm:max-w-md">
          <FieldLabel htmlFor="cast-search">{t("Find a reference")}</FieldLabel>
          <div className="relative"><Search size={17} aria-hidden="true" className="pointer-events-none absolute left-3 top-3.5 text-ink-muted" /><TextField id="cast-search" type="search" className="pl-10" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search characters, places or props")} /></div>
        </div>
        {search.trim() ? <div className="flex items-center gap-3"><p role="status" className="font-body text-sm text-ink-muted">{t("{count} references found", { count: String(matchCount) })}</p><Button variant="outline" size="xs" onClick={() => setSearch("")}>{t("Clear search")}</Button></div> : <p className="max-w-sm font-body text-xs leading-6 text-ink-muted">{t("Review & adjust opens the image and its creative controls.")}</p>}
      </div>
      {search.trim() && matchCount === 0 && <p className="py-8 font-body text-sm text-ink-muted">{t("No matching references. Try another name or clear your search.")}</p>}

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

      {/* A queued run is already updating them; is_running covers queued as well as running jobs. */}
      {!stageRegenerating && !status?.is_running && (
        <OutdatedReferences project={id} bible={bible} castStatus={stageStatus}
          onResume={() => setConfirmCast(true)} resumeDisabled={isPipelineRunning || !status?.style_selected} ready={!!status} />
      )}

      {!stageRegenerating && !status?.is_running && (
        <CastFailureNotice
          failures={stageInfo?.failures ?? []}
          onLessGraphic={(failure) => {
            setSearch("");
            setCastSuggestion({
              kind: failure.asset_type!, entityId: failure.entity_id!, stateId: failure.state_id,
              text: t(LESS_GRAPHIC_DIRECTION), nonce: Date.now(),
            });
          }}
          onResume={checkpointAction === "resume" ? () => setConfirmCast(true) : undefined}
          resumeDisabled={isPipelineRunning || !status?.style_selected || !castResumeEstimate}
        />
      )}

      {stageRegenerating && stageInfo && <CastRunProgress done={stageInfo.items_done} total={stageInfo.items_total} remaining={updating.size} />}

      <CastUpdatingContext.Provider value={updating}>
      <CastSuggestionContext.Provider value={suggestionContext}>
      <section className="space-y-10">
        <div id="cast-characters" tabIndex={-1} hidden={!!search.trim() && matchingCharacters === 0}>
          <SectionHeader
            variant="underline"
            title="CHARACTER REFS"
            description="Portrait proofs keep faces, clothing, and silhouettes consistent from scene to scene."
          />
          {bible.characters.length > 0 && <CastIdentityReview projectId={id} characters={bible.characters} locations={bible.locations}
            onShowCharacter={() => setSearch("")}
            onUseSuggestion={(kind, entityId, text) => { setSearch(""); setCastSuggestion({ kind, entityId, text, nonce: Date.now() }); }}
            onResume={handleContinueStale} busy={stageRegenerating || !status?.style_selected}
            redrawing={redrawingCharacters} />}
          <div className={`${CAST_GRID} grid-cols-[repeat(auto-fill,minmax(min(100%,260px),1fr))]`}>
            {bible.characters.map((char) => (
              <div id={`cast-character-${char.id}`} tabIndex={-1} key={char.id} hidden={!matches(char)} className={CAST_GRID_ITEM}>
              <CharacterCastCard
                character={char}
                projectName={id}
                stageRegenerating={stageRegenerating}
              />
              </div>
            ))}
          </div>
        </div>

        <div id="cast-places" tabIndex={-1} hidden={!!search.trim() && matchingLocations === 0}>
          <SectionHeader
            variant="underline"
            title="LOCATION PLATES"
            description="Wide environment plates anchor geography, architecture, light, and atmosphere."
          />
          <div className={`${CAST_GRID} grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))]`}>
            {bible.locations.map((loc) => (
              <div id={`cast-location-${loc.id}`} tabIndex={-1} key={loc.id} hidden={!matches(loc)} className={CAST_GRID_ITEM}>
              <LocationPlateCard
                location={loc}
                projectName={id}
                stageRegenerating={stageRegenerating}
              />
              </div>
            ))}
          </div>
        </div>

        {bible.props.length > 0 && (
          <div id="cast-props" tabIndex={-1} hidden={!!search.trim() && matchingProps === 0}>
            <SectionHeader variant="underline" title="PROP REFS" />
            <div className={`${CAST_GRID} grid-cols-[repeat(auto-fill,minmax(min(100%,240px),1fr))]`}>
              {bible.props.map((prop) => (
                <div id={`cast-prop-${prop.id}`} tabIndex={-1} key={prop.id} hidden={!matches(prop)} className={CAST_GRID_ITEM}>
                <PropRefCard
                  prop={prop}
                  projectName={id}
                  stageRegenerating={stageRegenerating}
                  firstSceneTitle={bible.scenes.find((scene) => scene.id === prop.first_appearance_scene)?.title}
                />
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
      </CastSuggestionContext.Provider>
      </CastUpdatingContext.Provider>

      {resetError && <ErrorNotice error={resetError} operation="save" />}
      {!status?.style_selected && <p className="font-body text-sm text-ink-muted">{t("Choose a style before starting cast references.")}</p>}
      <ConfirmDrawer
        open={confirmCast}
        title={canStartCast ? t("Start cast characters & places") : t("Resume cast characters & places")}
        body={t("Current references are reused. Missing or outdated references are regenerated, then character identities are compared. Replaced artwork stays in version history.")}
        cost={castResumeEstimate}
        confirmLabel={canStartCast ? t("START CAST") : t("RESUME CAST")}
        onConfirm={startCast}
        onClose={() => setConfirmCast(false)}
        busy={isPipelineRunning || !castResumeEstimate}
      />
      {!projectBusy && !stageRegenerating && !isPipelineRunning && !continuing && <ApprovalBar
        next={canStartCast ? t("Start the character and place references when you are ready")
          : missingAnchors.length > 0
          ? t("Add the missing descriptions above to continue")
          : recheckOnly
          ? t("Scenewright checks your corrected cast, then adapts the book and plans complete pages — automatically")
          : checkpointAction === "resume"
          ? stageInfo?.approval_blocker ?? "Some cast references did not finish — resume from the missing images"
          : needsApproval && openCastNotes > 0
          ? t("{count, plural, one {# character note is open} other {# character notes are open}}. You can still continue; notes are advice.", { count: openCastNotes })
          : needsApproval
          ? "Scenewright adapts the book and plans complete pages — automatically"
          : stageStatus === "complete"
            ? "Review complete pages at the Pages station"
            : "Scenewright is drawing your cast"}
        estimateCredits={recheckOnly
          ? (castResumeEstimate && chainEstimate ? castResumeEstimate.estimate_credits + chainEstimate.estimate_credits : undefined)
          : canStartCast || checkpointAction === "resume"
          ? castResumeEstimate?.estimate_credits
          : needsApproval
            ? chainEstimate?.estimate_credits
            : null}
        primaryLabel={canStartCast ? t("START CAST") : recheckOnly
          ? "LOOKS RIGHT — CONTINUE →"
          : checkpointAction === "resume"
          ? "↺ RESUME CAST"
          : needsApproval
            ? "LOOKS RIGHT — CONTINUE →"
            : "GO TO PAGES →"}
        onPrimary={handleContinueToPages}
        primaryDisabled={approveStage.isPending || isPipelineRunning || projectBusy || (!canStartCast && missingAnchors.length > 0) || (!canStartCast && checkpointAction === "wait") || ((canStartCast || checkpointAction === "resume") && (!status?.style_selected || !castResumeEstimate))}
        busy={approveStage.isPending || isPipelineRunning || continuing}
        error={actionError}
        secondary={<RerunStageAction project={id} stage="cast" label="cast" disabled={stageRegenerating} />}
      />}
    </RoomShell>
  );
}
