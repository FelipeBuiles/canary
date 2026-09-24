import { CastRegenAction } from "../../components/composites/CastRegenAction";
import { CastIdentityReview } from "../../components/composites/CastIdentityReview";
import { ArrowUpRight, Search, Users, MapPin, Box, LoaderCircle, ImagePlus } from "lucide-react";
import { FieldLabel, TextField } from "../../components/ui/Field";
import { useReferenceJob } from "../../hooks/useReferenceJob";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useGenerationJobs,
  useProjectStatus,
  useStageEstimate,
  useStoryBible,
  useRegenRef,
  useRegenStateRef,
  useRegenLocationState,
  useCastAssetVersions,
  useRestoreCastAssetVersion,
  useRegenRefWithInstruction,
  useRegenPlate,
  useRegenPlateWithInstruction,
  useRegenProp,
  useRegenPropWithInstruction,
  useAssetRegenEstimate,
  useImageGenerationMeta,
  useResetStale,
} from "../../api/queries";
import { ApprovalBar, ConfirmDrawer, RoomHeader, RoomShell, RerunStageAction, StagePlaceholder, SectionHeader, EntityCard } from "../../components/composites";
import { useRunAction } from "../../hooks/useRunAction";
import { useLiveStageAsset } from "../../hooks/useLiveStageAsset";
import { Tag } from "../../components/ui/Tag";
import { Button } from "../../components/ui/Button";
import { ImageModal } from "../../components/ui/ImageModal";
import { GenerationDetailsPanel } from "../../components/ui/GenerationDetailsModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StatusPill } from "../../components/ui/StatusPill";
import type { AppearanceState, CastFailure, CastReferenceInput, Character, GenerationJob, Location, Prop } from "../../types/api";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { useI18n } from "../../i18n";
import { FlowingDotsPlaceholder } from "../../components/ui/FlowingDotsPlaceholder";
import { StaleStageNotice } from "../../components/composites";
import { getCastCheckpointAction } from "../../lib/castCheckpoint";

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

  const visiblePoses = REF_VIEWS.filter(({ pose }) => !failed[pose]);
  if (visiblePoses.length === 0) return null;

  return (
    <div>
      <div className="font-meta text-xs tracking-[0.12em] text-ink-muted mb-3">
        {t("REFERENCE VIEWS")}
        <span className="mt-1 block font-body text-sm tracking-normal text-ink-muted">{t("Selected automatically to suit each shot.")}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {visiblePoses.map(({ pose, label }) => {
          const src = `/api/projects/${encodeURIComponent(projectName)}/files/refs/${encodeURIComponent(charId)}/${pose}.png?t=${encodeURIComponent(timestamp)}`;
          return (
            <div
              key={pose}
              title={`${t(label)} ${t("reference")}`}
              className="relative w-[104px] max-w-full overflow-hidden border border-ink-black/15"
            >
              <img
                src={src}
                alt={`${t(label)} ${t("reference")}`}
                className="aspect-[1/2] w-full object-cover"
                onError={() => setFailed((f) => ({ ...f, [pose]: true }))}
              />
              <span className="block bg-ink-black/5 px-2 py-2 text-center font-meta text-xs tracking-normal text-ink-muted">
                {t(label)}
              </span>
            </div>
          );
        })}
      </div>
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
export function StateRefRow({
  projectName,
  entityId,
  kind,
  states,
  stageRegenerating,
  refreshToken,
}: {
  projectName: string;
  entityId: string;
  kind: "character" | "location";
  states: AppearanceState[] | undefined;
  stageRegenerating: boolean;
  refreshToken: string | null;
}) {
  const { t } = useI18n();
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const [viewer, setViewer] = useState<AppearanceState | null>(null);
  const [restoredAt, setRestoredAt] = useState<Record<string, number>>({});

  const significant = (states ?? []).filter((s) => s.visually_significant);
  const { data: jobs } = useGenerationJobs(projectName, [], significant.length > 0);
  const { data: status } = useProjectStatus(projectName);
  const stateFailure = (stateId: string) => castFailureFor(status?.stages?.cast?.failures, entityId, stateId);
  if (significant.length === 0) return null;
  const stateJob = (stateId: string) => (jobs?.jobs ?? []).filter((job) =>
    job.payload[kind === "character" ? "char_id" : "loc_id"] === `${entityId}:${stateId}`,
  ).reduce<GenerationJob | undefined>((latest, job) =>
    !latest || Date.parse(job.queued_at) >= Date.parse(latest.queued_at) ? job : latest, undefined);
  const version = (stateId: string) => {
    const job = stateJob(stateId);
    return encodeURIComponent(`${refreshToken ?? "current"}${restoredAt[stateId] ? `-restored-${restoredAt[stateId]}` : ""}${job ? `-${job.id}-${job.status}` : ""}`);
  };

  const base = `/api/projects/${encodeURIComponent(projectName)}/files`;
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
          const generating = stageRegenerating || job?.status === "queued" || job?.status === "running";
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
              <div className={frameClass}>
                <img
                  src={src}
                  alt={`${s.label} ${t("reference")}`}
                  loading="lazy"
                  className="h-full w-full object-cover"
                  onError={() => setFailed((f) => ({ ...f, [src]: true }))}
                />
              </div>
              <span className={labelClass}><span className="line-clamp-2" title={s.label}>{s.label}</span><span className="mt-1 block text-xs text-ink-muted">{t("Review & adjust")}</span></span>
            </button>
          );
        })}
      </div>
      {viewer && <StateAppearanceModal projectName={projectName} entityId={entityId} kind={kind}
        state={viewer} failure={stateFailure(viewer.id)} stageRegenerating={stageRegenerating} onClose={() => setViewer(null)}
        onRestored={() => setRestoredAt((previous) => ({ ...previous, [viewer.id]: Date.now() }))} />}

    </div>
  );
}

function StateAppearanceModal({ projectName, entityId, kind, state, failure, stageRegenerating, onClose, onRestored }: {
  projectName: string; entityId: string; kind: "character" | "location";
  state: AppearanceState; failure?: CastFailure; stageRegenerating: boolean; onClose: () => void; onRestored: () => void;
}) {
  const { t } = useI18n();
  const job = useReferenceJob(projectName, kind === "character" ? "char_id" : "loc_id", entityId, state.id);
  const characterRegen = useRegenStateRef();
  const locationRegen = useRegenLocationState();
  const characterEdit = useRegenRefWithInstruction();
  const locationEdit = useRegenPlateWithInstruction();
  const [instruction, setInstruction] = useState<string | null>(null);
  const { data: estimate } = useAssetRegenEstimate(projectName, kind, entityId, state.id);
  const busy = stageRegenerating || job.isSubmitting || !!job.activeJob || characterRegen.isPending || locationRegen.isPending || characterEdit.isPending || locationEdit.isPending;
  const src = `/api/projects/${encodeURIComponent(projectName)}/files/${kind === "character"
    ? `refs/${encodeURIComponent(entityId)}/states/${encodeURIComponent(state.id)}/sheet.png`
    : `plates/${encodeURIComponent(entityId)}/states/${encodeURIComponent(state.id)}.png`}?t=${job.timestamp}`;
  const submit = (text?: string, referenceAssets?: CastReferenceInput[]) => {
    job.setRegenError(null);
    const callbacks = {
      onSuccess: (data: { job: GenerationJob }) => job.setActiveJob(data.job),
      onError: (error: Error) => {
        if (maybeShowInsufficientCredits(error, { actionLabel: "Regenerate appearance", onRetry: () => submit(text, referenceAssets) })) return;
        job.setRegenError(error.message);
      },
    };
    if (text) {
      if (kind === "character") characterEdit.mutate({ project: projectName, charId: entityId, stateId: state.id, instruction: text, referenceAssets }, callbacks);
      else locationEdit.mutate({ project: projectName, locId: entityId, stateId: state.id, instruction: text, referenceAssets }, callbacks);
    } else if (kind === "character") characterRegen.mutate({ project: projectName, charId: entityId, stateId: state.id }, callbacks);
    else locationRegen.mutate({ project: projectName, locId: entityId, stateId: state.id }, callbacks);
  };
  return <ImageModal isOpen onClose={onClose} src={src} alt={state.label} title={state.label}
    imageAvailable={!job.imgFailed} emptyLabel={t("NOT GENERATED")}
    sidebar={<div className="space-y-5">
      <p className="font-body text-sm leading-6 text-ink-black">{state.visual_anchor}</p>
      {failure && !busy && <p role="alert" className="border-l-4 border-hero-red pl-3 font-body text-sm leading-6 text-ink-black">
        <span className="block font-meta text-xs font-bold text-hero-red">{t("LAST ATTEMPT FAILED")}</span>{failure.message}</p>}
      <img src={src} alt="" className="hidden" onError={() => job.setImgFailed(true)} />
      <CastRegenAction projectName={projectName} assetType={kind} assetId={entityId} stateId={state.id}
        assetLabel={state.label} cost={estimate} hasImage={!job.imgFailed} busy={busy}
        busyLabel={job.activeJob ? queuedLabel(job.activeJob) : t("DRAWING…")}
        instruction={instruction ?? job.instructionDraft} onInstructionChange={setInstruction}
        error={job.regenError} onRegenerate={() => submit()} onRegenerateWithInstruction={submit} />
      <RefVersionHistory projectName={projectName} assetType={kind} assetId={entityId} stateId={state.id} busy={busy}
        refreshKey={job.timestamp} onRestored={() => { job.setTimestamp(Date.now()); job.setImgFailed(false); onRestored(); }} />
    </div>} />;
}

/**
 * Re-roll history for a character or location (main or alternate appearance). Renders
 * nothing until at least one prior version has been archived, so it stays out
 * of the way until you've actually re-rolled. Clicking a thumbnail restores it.
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
  const archived = (data?.versions ?? []).filter((v) => !v.current);
  if (isPending) return <p className="font-body text-sm text-ink-muted">{t("Loading version history…")}</p>;
  if (error) return <p role="alert" className="font-body text-sm text-hero-red">{t("Version history could not be loaded.")}</p>;
  if (archived.length === 0) return null;

  const fileUrl = (relPath: string) =>
    `/api/projects/${encodeURIComponent(projectName)}/files/${relPath}`;

  return (
    <div className="mt-1.5">
      <div className="font-meta text-xs tracking-[0.1em] text-ink-muted">
        {t("PREVIOUS VERSIONS")} ({archived.length})
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {archived.map((v) => (
          <button
            key={`${v.version}-${v.image_path}`}
            type="button"
            title={t("Restore") + ` v${v.version}`}
            aria-label={t("Restore") + ` v${v.version}`}
            disabled={busy || restore.isPending}
            onClick={() =>
              restore.mutate(
                { project: projectName, assetType, assetId, version: v.version, stateId },
                { onSuccess: () => onRestored?.() },
              )
            }
            className="relative w-14 overflow-hidden border border-ink-black/20 transition-colors hover:border-ink-black focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red disabled:opacity-50"
          >
            <img src={fileUrl(v.image_path)} alt="" className="aspect-square w-full object-cover" />
            <span className="block bg-bristol px-1 py-1 font-meta text-xs text-ink-muted">v{v.version}</span>
          </button>
        ))}
      {restore.error && <p role="alert" className="mt-2 font-body text-sm text-hero-red">{restore.error.message}</p>}
      </div>
    </div>
  );
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
  const refUrl = `/api/projects/${encodeURIComponent(projectName)}/files/refs/${encodeURIComponent(character.id)}/sheet.png`;
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { imgFailed, setImgFailed, timestamp, setTimestamp, activeJob, setActiveJob, isSubmitting, instructionDraft, regenError, setRegenError } =
    useReferenceJob(projectName, "char_id", character.id);
  const [instruction, setInstruction] = useState<string | null>(null);
  const regenRef = useRegenRef();
  const regenRefInstructed = useRegenRefWithInstruction();
  const { data: regenEstimate } = useAssetRegenEstimate(projectName, "character", character.id, undefined, isModalOpen);
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `refs/${character.id}/sheet.png`,
    isModalOpen,
    timestamp,
  );


  useEffect(() => {
    if (!stageRegenerating) {
      const timer = window.setTimeout(() => {
        setTimestamp(Date.now());
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [stageRegenerating, setTimestamp]);

  const startRegen = () => {
    setRegenError(null);
    regenRef.mutate(
      { project: projectName, charId: character.id },
      {
        onSuccess: (data) => setActiveJob(data.job),
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Regenerate character",
              onRetry: startRegen,
            })
          ) {
            return;
          }
          setRegenError(err.message);
        },
      }
    );
  };

  const submitInstruction = (nextInstruction: string, referenceAssets: CastReferenceInput[]) => {
    const trimmed = nextInstruction.trim();
    if (!trimmed) return;
    setInstruction(trimmed);
    setRegenError(null);
    regenRefInstructed.mutate(
      { project: projectName, charId: character.id, instruction: trimmed, referenceAssets },
      {
        onSuccess: (data) => {
          setActiveJob(data.job);
        },
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Apply & regenerate character",
              onRetry: () => submitInstruction(trimmed, referenceAssets),
            })
          ) {
            return;
          }
          setRegenError(err.message);
        },
      },
    );
  };

  const isInstructionBusy = regenRefInstructed.isPending || isSubmitting;

  const { t } = useI18n();
  const { hasImage, probe } = useLiveStageAsset(refUrl, timestamp, stageRegenerating);
  // A card hides its asset only while that asset is genuinely absent or
  // while this card's own regeneration is in flight.
  const isGenerating = (stageRegenerating && !hasImage) || regenRef.isPending || isInstructionBusy || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <EntityCard
        padding="tight"
        className="group/cast-card min-w-0"
        media={
          <button
            type="button"
            className="relative block w-full cursor-pointer bg-surface-container text-left focus-visible:outline-[3px] focus-visible:outline-offset-[-3px] focus-visible:outline-hero-red disabled:cursor-wait"
            onClick={() => setIsModalOpen(true)}
            disabled={isGenerating}
            aria-label={`${t("Open image")} · ${character.name}`}
          >
            {probe}
            {isGenerating ? (
              <FlowingDotsPlaceholder
                aspect="1 / 1"
                className="h-full"
                label={isQueued ? t("QUEUED") : t("DRAWING…")}
                caption={activeJob ? t("GENERATING NEW REF") : t("REBUILDING CAST REF")}
              />
            ) : imgFailed && !hasImage ? (
              <div className="flex aspect-square w-full flex-col items-center justify-center gap-2 bg-surface-container">
                <div className="font-meta text-xs font-bold tracking-[0.08em] text-ink-muted">{t("NO REF IMAGE")}</div>
                <div className="font-meta text-xs tracking-[0.06em] text-hero-red">{t("OPEN TO GENERATE")}</div>
              </div>
            ) : (
              <>
                <LazyImage
                  preserveAspectBox
                  src={`${refUrl}?t=${timestamp}`}
                  alt={character.name}
                  loading="lazy"
                  width={320}
                  height={320}
                  aspect="1/1"
                  containerClassName="aspect-square w-full"
                  className="object-contain transition-opacity group-hover/cast-card:opacity-90"
                  onError={() => setImgFailed(true)}
                />
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/42 opacity-0 transition-opacity duration-150 group-hover/cast-card:opacity-100">
                  <span className="border border-bristol bg-transparent px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-bristol">
                    ↗ {t("Full size")}
                  </span>
                </div>
              </>
            )}
            <StatusPill tone="red" className="absolute right-4 top-4">
              {t("REF")}
            </StatusPill>
          </button>
        }
      >
        <h3 className="font-display text-2xl font-black leading-tight tracking-[-0.03em] text-ink-black">
          {character.name}
        </h3>
        <details className="mt-4 bg-surface-container px-3"><summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold">{t("Visual details")}</summary><p className="pb-4 break-words text-sm leading-6 text-ink-black">{character.visual_anchor}</p></details>
        <div className="mt-3 font-body text-sm text-ink-muted">
          {[character.age_range, character.gender].filter(Boolean).join(" · ")}
        </div>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {character.distinguishing_features.slice(0, 3).map((f) => (
            <Tag key={f}>{f}</Tag>
          ))}
        </div>
        <StateRefRow
          projectName={projectName}
          entityId={character.id}
          kind="character"
          states={character.appearance_states}
          stageRegenerating={stageRegenerating}
          refreshToken={timestamp.toString()}
        />
        <div className="mt-auto pt-5"><Button variant="outline" size="sm" className="w-full" disabled={isGenerating} onClick={() => setIsModalOpen(true)} aria-label={`${t("Review & adjust")} · ${character.name}`}><ArrowUpRight size={16} aria-hidden="true" />{t("Review & adjust")}</Button></div>
        {regenError && (
          <div role="alert" className="mt-3 border-[2px] border-ink-black bg-hero-red p-2 text-sm leading-relaxed text-bristol">
            <strong className="block">{t("REGENERATION FAILED")}</strong>
            {regenError}
            <span className="mt-1 block">{t("The current reference has not been replaced. Review your change and try again.")}</span>
          </div>
        )}
      </EntityCard>
      <ImageModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        src={`${refUrl}?t=${timestamp}`}
        imageAvailable={!imgFailed}
        emptyLabel={t("NO REF IMAGE")}
        alt={character.name}
        title={character.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <section aria-label={t("VISUAL ANCHOR")}>
              <h3 className="font-meta text-xs text-ink-muted">{t("VISUAL ANCHOR")}</h3>
              <p className="mt-1 break-words text-sm leading-6 text-ink-black">{character.visual_anchor}</p>
            </section>
            <CastRegenAction
              projectName={projectName} assetType="character" assetId={character.id}
              assetLabel={character.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed}
              busy={isGenerating || isInstructionBusy}
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
              busy={isGenerating || isInstructionBusy}
              onRestored={() => {
                setTimestamp(Date.now());
                setImgFailed(false);
              }}
            />
            <StateRefRow projectName={projectName} entityId={character.id} kind="character" states={character.appearance_states} stageRegenerating={stageRegenerating} refreshToken={timestamp} />
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
  const plateUrl = `/api/projects/${encodeURIComponent(projectName)}/files/plates/${encodeURIComponent(location.id)}.png`;
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { imgFailed, setImgFailed, timestamp, setTimestamp, activeJob, setActiveJob, isSubmitting, instructionDraft, regenError, setRegenError: setLocalRegenError } =
    useReferenceJob(projectName, "loc_id", location.id);
  const [instruction, setInstruction] = useState<string | null>(null);
  const regenPlate = useRegenPlate();
  const regenPlateInstructed = useRegenPlateWithInstruction();
  const { data: regenEstimate } = useAssetRegenEstimate(projectName, "location", location.id, undefined, isModalOpen);
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `plates/${location.id}.png`,
    isModalOpen,
    timestamp,
  );


  useEffect(() => {
    if (!stageRegenerating) {
      const timer = window.setTimeout(() => {
        setTimestamp(Date.now());
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [stageRegenerating, setTimestamp]);

  const startRegen = () => {
    setLocalRegenError(null);
    regenPlate.mutate(
      { project: projectName, locId: location.id },
      {
        onSuccess: (data) => setActiveJob(data.job),
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Regenerate location plate",
              onRetry: startRegen,
            })
          ) {
            return;
          }
          setLocalRegenError(err.message);
        },
      }
    );
  };

  const submitInstruction = (nextInstruction: string, referenceAssets: CastReferenceInput[]) => {
    const trimmed = nextInstruction.trim();
    if (!trimmed) return;
    setInstruction(trimmed);
    setLocalRegenError(null);
    regenPlateInstructed.mutate(
      { project: projectName, locId: location.id, instruction: trimmed, referenceAssets },
      {
        onSuccess: (data) => {
          setActiveJob(data.job);
        },
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Apply & regenerate plate",
              onRetry: () => submitInstruction(trimmed, referenceAssets),
            })
          ) {
            return;
          }
          setLocalRegenError(err.message);
        },
      },
    );
  };

  const isInstructionBusy = regenPlateInstructed.isPending || isSubmitting;

  const { t } = useI18n();
  const { hasImage, probe } = useLiveStageAsset(plateUrl, timestamp, stageRegenerating);
  // A card hides its asset only while that asset is genuinely absent or
  // while this card's own regeneration is in flight.
  const isGenerating = (stageRegenerating && !hasImage) || regenPlate.isPending || isInstructionBusy || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <EntityCard
        padding="tight"
        className="group/cast-card min-w-0"
        media={
          <button
            type="button"
            className="relative block w-full cursor-pointer bg-surface-container text-left focus-visible:outline-[3px] focus-visible:outline-offset-[-3px] focus-visible:outline-hero-red disabled:cursor-wait"
            onClick={() => setIsModalOpen(true)}
            disabled={isGenerating}
            aria-label={`${t("Open image")} · ${location.name}`}
          >
            {probe}
            {isGenerating ? (
              <FlowingDotsPlaceholder
                aspect="16 / 9"
                className="h-full"
                label={isQueued ? t("QUEUED") : t("DRAWING…")}
                caption={activeJob ? t("GENERATING NEW PLATE") : t("REBUILDING LOCATION PLATE")}
              />
            ) : imgFailed && !hasImage ? (
              <div className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 bg-surface-container">
                <div className="font-meta text-xs font-bold tracking-[0.08em] text-ink-muted">{t("NO PLATE IMAGE")}</div>
                <div className="font-meta text-xs tracking-[0.06em] text-hero-red">{t("OPEN TO GENERATE")}</div>
              </div>
            ) : (
              <>
                <LazyImage
                  preserveAspectBox
                  src={`${plateUrl}?t=${timestamp}`}
                  alt={location.name}
                  loading="lazy"
                  width={480}
                  height={270}
                  aspect="16/9"
                  containerClassName="aspect-[16/9] w-full"
                  className="object-contain transition-opacity group-hover/cast-card:opacity-90"
                  onError={() => setImgFailed(true)}
                />
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/42 opacity-0 transition-opacity duration-150 group-hover/cast-card:opacity-100">
                  <span className="border border-bristol bg-transparent px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-bristol">
                    ↗ {t("Full size")}
                  </span>
                </div>
              </>
            )}
          </button>
        }
      >
        <h3 className="font-display text-2xl font-black leading-tight tracking-[-0.03em] text-ink-black">
          {location.name}
        </h3>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {location.time_of_day && (
            <Tag>{location.time_of_day}</Tag>
          )}
          <Tag>{location.mood}</Tag>
        </div>
        <StateRefRow
          projectName={projectName}
          entityId={location.id}
          kind="location"
          states={location.appearance_states}
          stageRegenerating={stageRegenerating}
          refreshToken={timestamp.toString()}
        />
        <details className="mt-4 bg-surface-container px-3"><summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold">{t("Visual details")}</summary><p className="pb-4 break-words text-sm leading-6 text-ink-black">{location.visual_anchor}</p></details>
        <div className="mt-auto pt-5"><Button variant="outline" size="sm" className="w-full" disabled={isGenerating} onClick={() => setIsModalOpen(true)} aria-label={`${t("Review & adjust")} · ${location.name}`}><ArrowUpRight size={16} aria-hidden="true" />{t("Review & adjust")}</Button></div>
        {regenError && (
          <div role="alert" className="mt-3 border-[2px] border-ink-black bg-hero-red p-2 text-sm leading-relaxed text-bristol">
            <strong className="block">{t("REGENERATION FAILED")}</strong>
            {regenError}
            <span className="mt-1 block">{t("The current reference has not been replaced. Review your change and try again.")}</span>
          </div>
        )}
      </EntityCard>
      <ImageModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        src={`${plateUrl}?t=${timestamp}`}
        imageAvailable={!imgFailed}
        emptyLabel={t("NO PLATE IMAGE")}
        alt={location.name}
        title={location.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <CastRegenAction
              projectName={projectName} assetType="location" assetId={location.id}
              assetLabel={location.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed}
              busy={isGenerating || isInstructionBusy}
              busyLabel={isQueued ? t("QUEUED") : t("DRAWING…")}
              error={regenError}
              instruction={instruction ?? instructionDraft}
              onInstructionChange={setInstruction}
              onRegenerate={startRegen}
              onRegenerateWithInstruction={submitInstruction}
            />
            <RefVersionHistory projectName={projectName} assetType="location" assetId={location.id}
              refreshKey={timestamp} busy={isGenerating || isInstructionBusy}
              onRestored={() => { setTimestamp(Date.now()); setImgFailed(false); }} />
            <StateRefRow projectName={projectName} entityId={location.id} kind="location" states={location.appearance_states} stageRegenerating={stageRegenerating} refreshToken={timestamp} />
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">VISUAL ANCHOR</div>
              <p className="text-[0.82rem] leading-6 text-ink-black">{location.visual_anchor}</p>
            </div>
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
}: {
  prop: Prop;
  projectName: string;
  stageRegenerating: boolean;
}) {
  const refUrl = `/api/projects/${encodeURIComponent(projectName)}/files/refs/props/${encodeURIComponent(prop.id)}/ref.png`;
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { imgFailed, setImgFailed, timestamp, setTimestamp, activeJob, setActiveJob, isSubmitting, instructionDraft, regenError, setRegenError: setLocalRegenError } =
    useReferenceJob(projectName, "prop_id", prop.id);
  const [instruction, setInstruction] = useState<string | null>(null);
  const regenProp = useRegenProp();
  const regenPropInstructed = useRegenPropWithInstruction();
  const { data: regenEstimate } = useAssetRegenEstimate(projectName, "prop", prop.id, undefined, isModalOpen);
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `refs/props/${prop.id}/ref.png`,
    isModalOpen,
    timestamp,
  );


  useEffect(() => {
    if (!stageRegenerating) {
      const timer = window.setTimeout(() => {
        setTimestamp(Date.now());
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [stageRegenerating, setTimestamp]);

  const startRegen = () => {
    setLocalRegenError(null);
    regenProp.mutate(
      { project: projectName, propId: prop.id },
      {
        onSuccess: (data) => setActiveJob(data.job),
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Regenerate prop",
              onRetry: startRegen,
            })
          ) {
            return;
          }
          setLocalRegenError(err.message);
        },
      }
    );
  };

  const submitInstruction = (nextInstruction: string, referenceAssets: CastReferenceInput[]) => {
    const trimmed = nextInstruction.trim();
    if (!trimmed) return;
    setInstruction(trimmed);
    setLocalRegenError(null);
    regenPropInstructed.mutate(
      { project: projectName, propId: prop.id, instruction: trimmed, referenceAssets },
      {
        onSuccess: (data) => {
          setActiveJob(data.job);
        },
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Apply & regenerate prop",
              onRetry: () => submitInstruction(trimmed, referenceAssets),
            })
          ) {
            return;
          }
          setLocalRegenError(err.message);
        },
      },
    );
  };

  const isInstructionBusy = regenPropInstructed.isPending || isSubmitting;

  const { t } = useI18n();
  const { hasImage, probe } = useLiveStageAsset(refUrl, timestamp, stageRegenerating);
  // A card hides its asset only while that asset is genuinely absent or
  // while this card's own regeneration is in flight.
  const isGenerating = (stageRegenerating && !hasImage) || regenProp.isPending || isInstructionBusy || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <EntityCard
        padding="tight"
        className="group/cast-card h-full"
        media={
          <button
            type="button"
            className="relative block w-full cursor-pointer bg-surface-container text-left focus-visible:outline-[3px] focus-visible:outline-offset-[-3px] focus-visible:outline-hero-red disabled:cursor-wait"
            onClick={() => setIsModalOpen(true)}
            disabled={isGenerating}
            aria-label={`${t("Open image")} · ${prop.name}`}
          >
            {probe}
            {isGenerating ? (
              <FlowingDotsPlaceholder
                aspect="1 / 1"
                className="h-full"
                label={isQueued ? t("QUEUED") : t("DRAWING…")}
                caption={activeJob ? t("GENERATING NEW PROP") : t("REBUILDING PROP REF")}
              />
            ) : imgFailed && !hasImage ? (
              <div className="flex aspect-square w-full flex-col items-center justify-center gap-2 bg-surface-container">
                <div className="font-meta text-xs font-bold tracking-[0.08em] text-ink-muted">{t("NO REF IMAGE")}</div>
                <div className="font-meta text-xs tracking-[0.06em] text-hero-red">{t("OPEN TO GENERATE")}</div>
              </div>
            ) : (
              <>
                <LazyImage
                  preserveAspectBox
                  src={`${refUrl}?t=${timestamp}`}
                  alt={prop.name}
                  loading="lazy"
                  width={400}
                  height={400}
                  aspect="1/1"
                  containerClassName="aspect-square w-full"
                  className="object-contain transition-opacity group-hover/cast-card:opacity-90"
                  onError={() => setImgFailed(true)}
                />
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/42 opacity-0 transition-opacity duration-150 group-hover/cast-card:opacity-100">
                  <span className="border border-bristol bg-transparent px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-bristol">
                    ↗ {t("Full size")}
                  </span>
                </div>
              </>
            )}
            <StatusPill tone="red" className="absolute right-4 top-4">
              {t("PROP")}
            </StatusPill>
          </button>
        }
      >
        <h3 className="font-display text-2xl font-black leading-tight tracking-[-0.03em] text-ink-black">
          {prop.name}
        </h3>
        {prop.first_appearance_scene && (
          <div className="mt-2 font-body text-[0.92rem] font-semibold text-ink-black/55">
            First seen: {prop.first_appearance_scene}
          </div>
        )}
        <details className="mt-4 bg-surface-container px-3"><summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold">{t("Visual details")}</summary><p className="pb-4 break-words text-sm leading-6 text-ink-black">{prop.visual_anchor}</p></details>
        <div className="mt-auto pt-5"><Button variant="outline" size="sm" className="w-full" disabled={isGenerating} onClick={() => setIsModalOpen(true)} aria-label={`${t("Review & adjust")} · ${prop.name}`}><ArrowUpRight size={16} aria-hidden="true" />{t("Review & adjust")}</Button></div>
        {regenError && (
          <div role="alert" className="mt-3 border-[2px] border-ink-black bg-hero-red p-2 text-sm leading-relaxed text-bristol">
            <strong className="block">{t("REGENERATION FAILED")}</strong>
            {regenError}
            <span className="mt-1 block">{t("The current reference has not been replaced. Review your change and try again.")}</span>
          </div>
        )}
      </EntityCard>
      <ImageModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        src={`${refUrl}?t=${timestamp}`}
        imageAvailable={!imgFailed}
        emptyLabel={t("NO REF IMAGE")}
        alt={prop.name}
        title={prop.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <CastRegenAction
              projectName={projectName} assetType="prop" assetId={prop.id}
              assetLabel={prop.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed}
              busy={isGenerating || isInstructionBusy}
              busyLabel={isQueued ? t("QUEUED") : t("DRAWING…")}
              error={regenError}
              instruction={instruction ?? instructionDraft}
              onInstructionChange={setInstruction}
              onRegenerate={startRegen}
              onRegenerateWithInstruction={submitInstruction}
            />
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">VISUAL ANCHOR</div>
              <p className="text-[0.82rem] leading-6 text-ink-black">{prop.visual_anchor}</p>
            </div>
            {prop.first_appearance_scene && (
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">FIRST APPEARANCE</div>
                <p className="text-[0.82rem] text-ink-black">{prop.first_appearance_scene}</p>
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

/** Names each reference that stopped Cast and why, so Resume is never a blind retry. */
export function CastFailureNotice({ failures }: { failures: CastFailure[] }) {
  const { t } = useI18n();
  if (failures.length === 0) return null;
  const anchor = (failure: CastFailure) => failure.asset_type === "character" && failure.entity_id
    ? `#cast-character-${failure.entity_id}`
    : failure.asset_type === "location" ? "#cast-places" : "#cast-props";
  return (
    <section role="alert" aria-labelledby="cast-failures-title" className="border-[3px] border-hero-red bg-surface-container p-4 md:p-5">
      <h2 id="cast-failures-title" className="font-meta text-xs font-bold tracking-[0.12em] text-hero-red">{t("CAST STOPPED")}</h2>
      <p className="mt-2 font-body text-sm text-ink-black">{t("These references did not finish. Everything else is kept.")}</p>
      <ul className="mt-3 space-y-3">
        {failures.map((failure) => (
          <li key={failure.item_id} className="font-body text-sm leading-6 text-ink-black">
            <a href={anchor(failure)} className="font-bold underline decoration-hero-red underline-offset-4">{failure.label}</a>
            <span className="block text-ink-black/80">{failure.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function CastRoom() {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [confirmCast, setConfirmCast] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: bible, isLoading } = useStoryBible(id);
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
  const checkpointAction = getCastCheckpointAction(stageStatus, stageInfo?.approval_blocker);
  const isStageStuck = !!stageInfo?.stale;
  const lastProgressAt = stageInfo?.last_progress_at ?? null;
  const needsApproval = checkpointAction === "approve";
  const canStartCast = stageStatus === "pending";
  const { data: castResumeEstimate } = useStageEstimate(id, "cast", !isCastStageRunning);

  function startCast() {
    if (!id || !status?.style_selected || !castResumeEstimate) return;
    setActionError(null);
    handleRun(id, "cast", {
      actionLabel: canStartCast ? t("Start cast characters & places") : t("Resume cast characters & places"),
      onSuccess: () => setConfirmCast(false),
      onError: (error) => { setConfirmCast(false); setActionError(error.message); },
    });
  }

  function handleContinueToPages() {
    if (!id) return;
    if (checkpointAction === "resume" || canStartCast) {
      setConfirmCast(true);
    } else if (checkpointAction === "approve") {
      approveStage.mutate(
        { project: id, stage: "cast" },
        {
          onSuccess: () => {
            navigate(`/project/${id}/pages`);
          },
          onError: (error) => setActionError(error.message),
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
        kicker="LOOK"
        title="CONFIRM CHARACTERS & PLACES"
        lead="These approved references guide every complete page. Open only the people or places that need a fix."
      />

      <section className="bg-ink-black p-6 text-pulp-paper shadow-paper md:p-8">
        <div className="grid gap-6 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] md:items-end">
          <div>
            <h2 className="font-display text-3xl font-black uppercase leading-tight tracking-[-0.03em] md:text-4xl">{t("Meet your cast")}</h2>
            <p className="mt-3 max-w-[60ch] font-body text-sm leading-7 text-pulp-paper/85">{t("The faces, places and objects that make your story recognizable. Open a reference to inspect it, adjust its direction or explore another version.")}</p>
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
        {search.trim() ? <div className="flex items-center gap-3"><p role="status" className="font-body text-sm text-ink-muted">{t("{count} references found").replace("{count}", String(matchCount))}</p><Button variant="outline" size="xs" onClick={() => setSearch("")}>{t("Clear search")}</Button></div> : <p className="max-w-sm font-body text-xs leading-6 text-ink-muted">{t("Review & adjust opens the image and its creative controls.")}</p>}
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

      {!stageRegenerating && <CastFailureNotice failures={stageInfo?.failures ?? []} />}

      <section className="space-y-10">
        {bible.characters.length > 0 && <CastIdentityReview projectId={id} characters={bible.characters} onShowCharacter={() => setSearch("")}
          onResume={handleContinueStale} busy={stageRegenerating || !status?.style_selected} />}
        <div id="cast-characters" tabIndex={-1} hidden={!!search.trim() && matchingCharacters === 0}>
          <SectionHeader
            variant="underline"
            title="CHARACTER REFS"
            description="Portrait proofs keep faces, clothing, and silhouettes consistent from scene to scene."
          />
          <div className="grid items-start gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {bible.characters.map((char) => (
              <div id={`cast-character-${char.id}`} tabIndex={-1} key={char.id} hidden={!matches(char)} className="min-w-0 scroll-mt-24">
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
          <div className="grid items-start gap-5 md:grid-cols-2 xl:grid-cols-3">
            {bible.locations.map((loc) => (
              <div key={loc.id} hidden={!matches(loc)} className="min-w-0">
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
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {bible.props.map((prop) => (
                <div key={prop.id} hidden={!matches(prop)} className="min-w-0">
                <PropRefCard
                  prop={prop}
                  projectName={id}
                  stageRegenerating={stageRegenerating}
                />
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {(actionError || resetError || approveStage.error) && <p role="alert" className="font-body text-sm text-hero-red">{actionError ?? resetError?.message ?? approveStage.error?.message}</p>}
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
      <ApprovalBar
        next={canStartCast ? t("Start the character and place references when you are ready")
          : checkpointAction === "resume"
          ? stageInfo?.approval_blocker ?? "Some cast references did not finish — resume from the missing images"
          : needsApproval
          ? "Scenewright adapts the book and plans complete pages — automatically"
          : stageStatus === "complete"
            ? "Review complete pages at the Pages station"
            : "Scenewright is drawing your cast"}
        estimateCredits={canStartCast || checkpointAction === "resume"
          ? castResumeEstimate?.estimate_credits
          : needsApproval
            ? chainEstimate?.estimate_credits
            : null}
        primaryLabel={canStartCast ? t("START CAST") : checkpointAction === "resume"
          ? "↺ RESUME CAST"
          : needsApproval
            ? "LOOKS RIGHT — CONTINUE →"
            : "GO TO PAGES →"}
        onPrimary={handleContinueToPages}
        primaryDisabled={approveStage.isPending || isPipelineRunning || (!canStartCast && checkpointAction === "wait") || ((canStartCast || checkpointAction === "resume") && (!status?.style_selected || !castResumeEstimate))}
        busy={approveStage.isPending || isPipelineRunning}
        secondary={<RerunStageAction project={id} stage="cast" label="cast" disabled={stageRegenerating} />}
      />
    </RoomShell>
  );
}
