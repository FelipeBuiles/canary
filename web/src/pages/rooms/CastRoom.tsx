import { useEffect, useRef, useState } from "react";
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
  useCharacterRefVersions,
  useRestoreCharacterRefVersion,
  useRegenRefWithInstruction,
  useRegenPlate,
  useRegenPlateWithInstruction,
  useRegenProp,
  useRegenPropWithInstruction,
  useAssetRegenEstimate,
  useImageGenerationMeta,
  useResetStale,
} from "../../api/queries";
import { ApprovalBar, ConfirmDrawer, RegenAction, RoomHeader, RoomShell, RerunStageAction, StagePlaceholder, SectionHeader, EntityCard } from "../../components/composites";
import { useRunAction } from "../../hooks/useRunAction";
import { Tag } from "../../components/ui/Tag";
import { Button } from "../../components/ui/Button";
import { ImageModal } from "../../components/ui/ImageModal";
import { GenerationDetailsPanel } from "../../components/ui/GenerationDetailsModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StatusPill } from "../../components/ui/StatusPill";
import type { AppearanceState, Character, GenerationJob, Location, Prop } from "../../types/api";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { useI18n } from "../../i18n";
import { FlowingDotsPlaceholder } from "../../components/ui/FlowingDotsPlaceholder";
import { StaleStripe } from "../../components/draw/LiveCockpit";
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
function ReferenceViews({ projectName, charId, timestamp }: { projectName: string; charId: string; timestamp: number }) {
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  const visiblePoses = REF_VIEWS.filter(({ pose }) => !failed[pose]);
  if (visiblePoses.length === 0) return null;

  return (
    <div>
      <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1.5">
        REFERENCE VIEWS · SELECTED AUTOMATICALLY BY SHOT
      </div>
      <div className="flex flex-wrap gap-2">
        {visiblePoses.map(({ pose, label }) => {
          const src = `/api/projects/${encodeURIComponent(projectName)}/files/refs/${encodeURIComponent(charId)}/${pose}.png?t=${timestamp}`;
          return (
            <div
              key={pose}
              title={`${label} reference`}
              className="relative w-[72px] overflow-hidden border-[2px] border-ink-black/15"
            >
              <img
                src={src}
                alt={`${label} reference`}
                className="aspect-[1/2] w-full object-cover"
                onError={() => setFailed((f) => ({ ...f, [pose]: true }))}
              />
              <span className="block bg-ink-black/5 px-1 py-0.5 text-center font-meta text-[0.42rem] tracking-[0.1em] text-ink-black/70">
                {label}
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
 * refs/<id>/states/<state>/ (characters) or plates/<state>.png (locations).
 * States whose ref hasn't been generated yet (or failed) show a PENDING chip
 * rather than vanishing, so the gap is visible.
 */
function StateRefRow({
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
  const [viewer, setViewer] = useState<{ src: string; title: string } | null>(null);

  const significant = (states ?? []).filter((s) => s.visually_significant);
  if (significant.length === 0) return null;

  const base = `/api/projects/${encodeURIComponent(projectName)}/files`;
  const thumbUrl = (stateId: string) =>
    kind === "character"
      ? `${base}/refs/${encodeURIComponent(entityId)}/states/${encodeURIComponent(stateId)}/portrait.png?v=${encodeURIComponent(refreshToken ?? "current")}`
      : `${base}/plates/${encodeURIComponent(stateId)}.png?v=${encodeURIComponent(refreshToken ?? "current")}`;
  const fullUrl = (stateId: string) =>
    kind === "character"
      ? `${base}/refs/${encodeURIComponent(entityId)}/states/${encodeURIComponent(stateId)}/sheet.png?v=${encodeURIComponent(refreshToken ?? "current")}`
      : `${base}/plates/${encodeURIComponent(stateId)}.png?v=${encodeURIComponent(refreshToken ?? "current")}`;

  const tileWidth = kind === "character" ? "w-[64px]" : "w-[104px]";
  const imgAspect = kind === "character" ? "aspect-[64/84]" : "aspect-[16/9]";

  return (
    <div className="mt-4">
      <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1.5">
        {t("APPEARANCE STATES")}
      </div>
      <div className="flex flex-wrap gap-2">
        {significant.map((s) =>
          stageRegenerating ? (
            <div
              key={s.id}
              className={`flex ${tileWidth} flex-col items-center justify-center gap-1 border-[2px] border-ink-black/20 bg-surface-container px-1 py-3 text-center`}
            >
              <span className="font-meta text-[0.46rem] leading-tight tracking-[0.12em] text-ink-black/55">
                {s.label}
              </span>
              <span className="font-meta text-[0.42rem] tracking-[0.14em] text-hero-red">
                {t("REBUILDING")}
              </span>
            </div>
          ) : failed[thumbUrl(s.id)] ? (
            <div
              key={s.id}
              title={t("Not generated yet — re-run cast to build this state")}
              className={`flex ${tileWidth} flex-col items-center justify-center gap-1 border-[2px] border-dashed border-ink-black/20 bg-surface-container px-1 py-3 text-center`}
            >
              <span className="font-meta text-[0.46rem] leading-tight tracking-[0.12em] text-ink-black/55">
                {s.label}
              </span>
              <span className="font-meta text-[0.42rem] tracking-[0.14em] text-hero-red">
                {t("PENDING")}
              </span>
            </div>
          ) : (
            <button
              key={s.id}
              type="button"
              title={`${s.label} — ${t("click for full size")}`}
              onClick={() => setViewer({ src: fullUrl(s.id), title: s.label })}
              className={`${tileWidth} overflow-hidden border-[2px] border-ink-black/15 transition-colors hover:border-ink-black/50`}
            >
              <img
                src={thumbUrl(s.id)}
                alt={`${s.label} reference`}
                className={`${imgAspect} w-full object-cover`}
                onError={() => setFailed((f) => ({ ...f, [thumbUrl(s.id)]: true }))}
              />
              <span className="block truncate bg-ink-black/5 px-1 py-0.5 font-meta text-[0.42rem] tracking-[0.1em] text-ink-black/70">
                {s.label}
              </span>
            </button>
          )
        )}
      </div>
      <ImageModal
        isOpen={!!viewer}
        onClose={() => setViewer(null)}
        src={viewer?.src ?? ""}
        alt={viewer?.title ?? ""}
        title={viewer?.title}
      />
    </div>
  );
}

/**
 * Re-roll history for one character ref sheet (canonical or a state). Renders
 * nothing until at least one prior version has been archived, so it stays out
 * of the way until you've actually re-rolled. Clicking a thumbnail restores it.
 */
function RefVersionHistory({
  projectName,
  charId,
  stateId,
  refreshKey,
  onRestored,
  heading,
}: {
  projectName: string;
  charId: string;
  stateId?: string;
  refreshKey?: unknown;
  onRestored?: () => void;
  heading?: string;
}) {
  const { t } = useI18n();
  const { data } = useCharacterRefVersions(projectName, charId, stateId, refreshKey);
  const restore = useRestoreCharacterRefVersion();
  const archived = (data?.versions ?? []).filter((v) => !v.current);
  if (archived.length === 0) return null;

  const fileUrl = (relPath: string) =>
    `/api/projects/${encodeURIComponent(projectName)}/files/${relPath}`;

  return (
    <div className="mt-1.5">
      <div className="font-meta text-[0.46rem] tracking-[0.14em] text-ink-black/45">
        {heading ?? t("PREVIOUS")} ({archived.length})
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {archived.map((v) => (
          <button
            key={`${v.version}-${v.image_path}`}
            type="button"
            title={t("Restore") + ` v${v.version}`}
            disabled={restore.isPending}
            onClick={() =>
              restore.mutate(
                { project: projectName, charId, version: v.version, stateId },
                { onSuccess: () => onRestored?.() },
              )
            }
            className="relative h-9 w-9 overflow-hidden border-[1.5px] border-ink-black/20 transition-colors hover:border-ink-black disabled:opacity-50"
          >
            <img src={fileUrl(v.image_path)} alt={`v${v.version}`} className="h-full w-full object-cover" />
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * One alternate-appearance tile inside the base character's full-size modal:
 * its generated ref thumbnail, or a GENERATE button when the ref is missing
 * (failed/incomplete in the cast run), plus a RE-ROLL. Owns its own regen job
 * lifecycle so each state retries independently.
 */
function StateRefTile({
  projectName,
  charId,
  state,
}: {
  projectName: string;
  charId: string;
  state: AppearanceState;
}) {
  const { t } = useI18n();
  const [imgFailed, setImgFailed] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const [activeJob, setActiveJob] = useState<GenerationJob | null>(null);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const regenState = useRegenStateRef();
  const { data: generationJobs } = useGenerationJobs(projectName, activeJob ? [activeJob.id] : []);
  const { data: regenEstimate } = useAssetRegenEstimate(projectName, "character", charId, state.id);

  useEffect(() => {
    const job = generationJobs?.jobs[0];
    if (!job) return;
    const timer = window.setTimeout(() => {
      if (job.status === "complete") {
        setTimestamp(Date.now());
        setImgFailed(false);
        setActiveJob(null);
        setRegenError(null);
      } else if (job.status === "failed") {
        setActiveJob(null);
        setRegenError(job.error ?? "Regeneration failed");
      } else {
        setActiveJob(job);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs]);

  const thumbUrl = `/api/projects/${encodeURIComponent(projectName)}/files/refs/${encodeURIComponent(charId)}/states/${encodeURIComponent(state.id)}/portrait.png?t=${timestamp}`;

  const startRegen = () => {
    setConfirmRegen(false);
    setRegenError(null);
    regenState.mutate(
      { project: projectName, charId, stateId: state.id },
      {
        onSuccess: (data) => setActiveJob(data.job),
        onError: (err) => {
          if (maybeShowInsufficientCredits(err, { actionLabel: "Regenerate appearance", onRetry: startRegen })) return;
          setRegenError(err.message);
        },
      },
    );
  };

  const busy = regenState.isPending || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <div className="w-[84px]">
      <div className="relative aspect-[64/84] w-full overflow-hidden border-[2px] border-ink-black/15 bg-surface-container">
        {busy ? (
          <FlowingDotsPlaceholder
            compact
            aspect="64 / 84"
            className="!border-0 h-full"
            label={isQueued ? t("QUEUED") : t("DRAWING…")}
          />
        ) : imgFailed ? (
          <div className="flex h-full w-full items-center justify-center px-1 text-center">
            <span className="font-meta text-[0.46rem] leading-tight tracking-[0.12em] text-hero-red">{t("NOT GENERATED")}</span>
          </div>
        ) : (
          <img
            src={thumbUrl}
            alt={`${state.label} reference`}
            className="h-full w-full object-cover"
            onError={() => setImgFailed(true)}
          />
        )}
      </div>
      <div className="mt-1 truncate font-meta text-[0.46rem] tracking-[0.1em] text-ink-black/70" title={state.label}>
        {state.label}
      </div>
      <button
        type="button"
        onClick={() => setConfirmRegen(true)}
        disabled={busy || !regenEstimate}
        className="mt-1 w-full border-[1.5px] border-ink-black/25 bg-bristol px-1.5 py-1 font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/70 transition-colors hover:border-ink-black hover:text-ink-black disabled:opacity-50"
      >
        {busy ? queuedLabel(activeJob) : imgFailed ? t("GENERATE") : t("REGENERATE")}
      </button>
      <RefVersionHistory
        projectName={projectName}
        charId={charId}
        stateId={state.id}
        refreshKey={timestamp}
        onRestored={() => {
          setTimestamp(Date.now());
          setImgFailed(false);
        }}
      />
      {regenError && <div className="mt-1 text-[0.5rem] leading-tight text-hero-red">{regenError}</div>}
      <ConfirmDrawer
        open={confirmRegen}
        title={imgFailed ? t("Generate image") : t("Try another version")}
        body={imgFailed
          ? t("Scenewright will create this image from its saved visual brief.")
          : t("Scenewright will create a new image from the same saved brief. The current version stays in history.")}
        cost={regenEstimate}
        confirmLabel={imgFailed ? t("GENERATE IMAGE") : t("TRY ANOTHER VERSION")}
        onConfirm={startRegen}
        onClose={() => setConfirmRegen(false)}
        busy={busy}
      />
    </div>
  );
}

/** Alternate-appearance refs for a character, shown inside its full-size modal. */
function AppearanceStatesPanel({
  projectName,
  charId,
  states,
}: {
  projectName: string;
  charId: string;
  states: AppearanceState[] | undefined;
}) {
  const { t } = useI18n();
  const significant = (states ?? []).filter((s) => s.visually_significant);
  if (significant.length === 0) return null;
  return (
    <div>
      <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1.5">
        {t("ALTERNATE APPEARANCES")}
      </div>
      <div className="flex flex-wrap gap-3">
        {significant.map((s) => (
          <StateRefTile key={s.id} projectName={projectName} charId={charId} state={s} />
        ))}
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
  const [imgFailed, setImgFailed] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const [activeJob, setActiveJob] = useState<GenerationJob | null>(null);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const [lastAddendum, setLastAddendum] = useState<string | null>(null);
  const regenRef = useRegenRef();
  const regenRefInstructed = useRegenRefWithInstruction();
  const { data: generationJobs } = useGenerationJobs(projectName, activeJob ? [activeJob.id] : []);
  const { data: regenEstimate } = useAssetRegenEstimate(projectName, "character", character.id, undefined, isModalOpen);
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `refs/${character.id}/sheet.png`,
    isModalOpen,
    timestamp,
  );

  useEffect(() => {
    const job = generationJobs?.jobs[0];
    if (!job) return;
    const timer = window.setTimeout(() => {
      if (job.status === "complete") {
        setTimestamp(Date.now());
        setImgFailed(false);
        setActiveJob(null);
        setRegenError(null);
      } else if (job.status === "failed") {
        setActiveJob(null);
        setRegenError(job.error ?? "Regeneration failed");
      } else {
        setActiveJob(job);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs]);

  useEffect(() => {
    if (!stageRegenerating) {
      const timer = window.setTimeout(() => {
        setTimestamp(Date.now());
        setImgFailed(false);
      }, 0);
      return () => window.clearTimeout(timer);
    }

    const interval = window.setInterval(() => {
      setTimestamp(Date.now());
    }, 2000);
    return () => window.clearInterval(interval);
  }, [stageRegenerating]);

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

  const submitInstruction = (nextInstruction = instruction) => {
    const trimmed = nextInstruction.trim();
    if (!trimmed) {
      setInstructionError("Add a short visual instruction first.");
      return;
    }
    setInstructionError(null);
    setRegenError(null);
    regenRefInstructed.mutate(
      { project: projectName, charId: character.id, instruction: trimmed },
      {
        onSuccess: (data) => {
          setActiveJob(data.job);
          setLastAddendum(data.addendum);
          setInstruction("");
        },
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Apply & regenerate character",
              onRetry: () => submitInstruction(trimmed),
            })
          ) {
            return;
          }
          setInstructionError(err.message);
        },
      },
    );
  };

  const isInstructionBusy = regenRefInstructed.isPending;

  const { t } = useI18n();
  const isGenerating = stageRegenerating || regenRef.isPending || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <EntityCard
        padding="tight"
        className="group/cast-card"
        media={
          <button
            type="button"
            className="relative block w-full cursor-pointer bg-surface-container text-left focus-visible:outline-[3px] focus-visible:outline-offset-[-3px] focus-visible:outline-hero-red disabled:cursor-wait"
            onClick={() => setIsModalOpen(true)}
            disabled={isGenerating}
            aria-label={`${t("Open image")} · ${character.name}`}
          >
            {stageRegenerating && (
              <img
                key={timestamp}
                src={`${refUrl}?t=${timestamp}`}
                className="hidden"
                onLoad={() => setImgFailed(false)}
                alt=""
                aria-hidden="true"
              />
            )}
            {isGenerating ? (
              <FlowingDotsPlaceholder
                aspect="4 / 5"
                className="h-full"
                label={isQueued ? t("QUEUED") : t("DRAWING…")}
                caption={activeJob ? t("GENERATING NEW REF") : t("REBUILDING CAST REF")}
              />
            ) : imgFailed ? (
              <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 bg-surface-container">
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">{t("NO REF IMAGE")}</div>
                <div className="font-meta text-[0.5rem] tracking-[0.14em] text-hero-red">{t("OPEN TO GENERATE")}</div>
              </div>
            ) : (
              <>
                <LazyImage
                  src={`${refUrl}?t=${timestamp}`}
                  alt={character.name}
                  loading="lazy"
                  width={320}
                  height={400}
                  aspect="4/5"
                  containerClassName="aspect-[4/5] w-full"
                  className="object-cover transition-opacity group-hover/cast-card:opacity-90"
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
        <div className="font-display text-[1.35rem] font-bold uppercase leading-none tracking-[-0.04em] text-ink-black">
          {character.name}
        </div>
        <div className="mt-2 font-body text-[0.92rem] font-semibold text-ink-black/55">
          {character.age_range} &middot; {character.gender}
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
          refreshToken={stageRegenerating ? null : timestamp.toString()}
        />
        {regenError && (
          <div className="mt-3 border-[2px] border-ink-black bg-hero-red p-2 text-[0.72rem] leading-relaxed text-bristol">
            {regenError}
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
            <RegenAction
              assetLabel={character.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed}
              busy={isGenerating || isInstructionBusy}
              busyLabel={isQueued ? t("QUEUED") : t("DRAWING…")}
              error={regenError ?? instructionError}
              lastInstruction={lastAddendum}
              onRegenerate={startRegen}
              onRegenerateWithInstruction={submitInstruction}
            />
            <ReferenceViews projectName={projectName} charId={character.id} timestamp={timestamp} />
            <RefVersionHistory
              projectName={projectName}
              charId={character.id}
              refreshKey={timestamp}
              heading="PREVIOUS VERSIONS"
              onRestored={() => {
                setTimestamp(Date.now());
                setImgFailed(false);
              }}
            />
            <AppearanceStatesPanel
              projectName={projectName}
              charId={character.id}
              states={character.appearance_states}
            />
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1">HOW THEY'LL LOOK</div>
              <p className="text-[0.82rem] leading-6 text-ink-black">{character.visual_anchor}</p>
            </div>
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

function LocationStateTile({
  projectName,
  locId,
  state,
}: {
  projectName: string;
  locId: string;
  state: AppearanceState;
}) {
  const { t } = useI18n();
  const [imgFailed, setImgFailed] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const [activeJob, setActiveJob] = useState<GenerationJob | null>(null);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const regenState = useRegenLocationState();
  const { data: generationJobs } = useGenerationJobs(projectName, activeJob ? [activeJob.id] : []);
  const { data: regenEstimate } = useAssetRegenEstimate(projectName, "location", locId, state.id);

  useEffect(() => {
    const job = generationJobs?.jobs[0];
    if (!job) return;
    const timer = window.setTimeout(() => {
      if (job.status === "complete") {
        setTimestamp(Date.now());
        setImgFailed(false);
        setActiveJob(null);
        setRegenError(null);
      } else if (job.status === "failed") {
        setActiveJob(null);
        setRegenError(job.error ?? "Regeneration failed");
      } else {
        setActiveJob(job);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs]);

  const imageUrl = `/api/projects/${encodeURIComponent(projectName)}/files/plates/${encodeURIComponent(state.id)}.png?t=${timestamp}`;
  const busy = regenState.isPending || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  const startRegen = () => {
    setConfirmRegen(false);
    setRegenError(null);
    regenState.mutate(
      { project: projectName, locId, stateId: state.id },
      {
        onSuccess: (data) => setActiveJob(data.job),
        onError: (err) => {
          if (maybeShowInsufficientCredits(err, { actionLabel: "Regenerate location appearance", onRetry: startRegen })) return;
          setRegenError(err.message);
        },
      },
    );
  };

  return (
    <div className="w-[132px] max-w-full">
      <div className="relative aspect-[16/9] w-full overflow-hidden border-[2px] border-ink-black/15 bg-surface-container">
        {busy ? (
          <FlowingDotsPlaceholder
            compact
            aspect="16 / 9"
            className="h-full !border-0"
            label={isQueued ? t("QUEUED") : t("DRAWING…")}
          />
        ) : imgFailed ? (
          <div className="flex h-full w-full items-center justify-center px-2 text-center">
            <span className="font-meta text-[0.46rem] leading-tight tracking-[0.12em] text-hero-red">{t("NOT GENERATED")}</span>
          </div>
        ) : (
          <img
            src={imageUrl}
            alt={`${state.label} location reference`}
            className="h-full w-full object-cover"
            onError={() => setImgFailed(true)}
          />
        )}
      </div>
      <div className="mt-1 truncate font-meta text-[0.46rem] tracking-[0.1em] text-ink-black/70" title={state.label}>
        {state.label}
      </div>
      <button
        type="button"
        onClick={() => setConfirmRegen(true)}
        disabled={busy || !regenEstimate}
        className="mt-1 min-h-11 w-full border-[1.5px] border-ink-black/25 bg-bristol px-2 py-1.5 font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/70 transition-colors hover:border-ink-black hover:text-ink-black disabled:opacity-50"
      >
        {busy ? queuedLabel(activeJob) : imgFailed ? t("GENERATE") : t("REGENERATE")}
      </button>
      {regenError && <div className="mt-1 text-[0.5rem] leading-tight text-hero-red">{regenError}</div>}
      <ConfirmDrawer
        open={confirmRegen}
        title={imgFailed ? t("Generate image") : t("Try another version")}
        body={imgFailed
          ? t("Scenewright will create this image from its saved visual brief.")
          : t("Scenewright will create a new image from the same saved brief. The current version stays in history.")}
        cost={regenEstimate}
        confirmLabel={imgFailed ? t("GENERATE IMAGE") : t("TRY ANOTHER VERSION")}
        onConfirm={startRegen}
        onClose={() => setConfirmRegen(false)}
        busy={busy}
      />
    </div>
  );
}

function LocationAppearanceStatesPanel({
  projectName,
  locId,
  states,
}: {
  projectName: string;
  locId: string;
  states: AppearanceState[] | undefined;
}) {
  const { t } = useI18n();
  const significant = (states ?? []).filter((state) => state.visually_significant);
  if (significant.length === 0) return null;
  return (
    <div>
      <div className="mb-1.5 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">
        {t("ALTERNATE APPEARANCES")}
      </div>
      <div className="flex flex-wrap gap-3">
        {significant.map((state) => (
          <LocationStateTile
            key={state.id}
            projectName={projectName}
            locId={locId}
            state={state}
          />
        ))}
      </div>
    </div>
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
  const [imgFailed, setImgFailed] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const [activeJob, setActiveJob] = useState<GenerationJob | null>(null);
  const [localRegenError, setLocalRegenError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const [lastAddendum, setLastAddendum] = useState<string | null>(null);
  const regenPlate = useRegenPlate();
  const regenPlateInstructed = useRegenPlateWithInstruction();
  const { data: generationJobs } = useGenerationJobs(projectName, activeJob ? [activeJob.id] : []);
  const { data: regenEstimate } = useAssetRegenEstimate(projectName, "location", location.id, undefined, isModalOpen);
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `plates/${location.id}.png`,
    isModalOpen,
    timestamp,
  );

  const regenError = localRegenError;

  useEffect(() => {
    const job = generationJobs?.jobs[0];
    if (!job) return;
    const timer = window.setTimeout(() => {
      if (job.status === "complete") {
        setTimestamp(Date.now());
        setImgFailed(false);
        setActiveJob(null);
        setLocalRegenError(null);
      } else if (job.status === "failed") {
        setActiveJob(null);
        setLocalRegenError(job.error ?? "Regeneration failed");
      } else {
        setActiveJob(job);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs]);

  useEffect(() => {
    if (!stageRegenerating) {
      const timer = window.setTimeout(() => {
        setTimestamp(Date.now());
        setImgFailed(false);
      }, 0);
      return () => window.clearTimeout(timer);
    }

    const interval = window.setInterval(() => {
      setTimestamp(Date.now());
    }, 2000);
    return () => window.clearInterval(interval);
  }, [stageRegenerating]);

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

  const submitInstruction = (nextInstruction = instruction) => {
    const trimmed = nextInstruction.trim();
    if (!trimmed) {
      setInstructionError("Add a short visual instruction first.");
      return;
    }
    setInstructionError(null);
    setLocalRegenError(null);
    regenPlateInstructed.mutate(
      { project: projectName, locId: location.id, instruction: trimmed },
      {
        onSuccess: (data) => {
          setActiveJob(data.job);
          setLastAddendum(data.addendum);
          setInstruction("");
        },
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Apply & regenerate plate",
              onRetry: () => submitInstruction(trimmed),
            })
          ) {
            return;
          }
          setInstructionError(err.message);
        },
      },
    );
  };

  const isInstructionBusy = regenPlateInstructed.isPending;

  const { t } = useI18n();
  const isGenerating = stageRegenerating || regenPlate.isPending || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <EntityCard
        padding="tight"
        className="group/cast-card"
        media={
          <button
            type="button"
            className="relative block w-full cursor-pointer bg-surface-container text-left focus-visible:outline-[3px] focus-visible:outline-offset-[-3px] focus-visible:outline-hero-red disabled:cursor-wait"
            onClick={() => setIsModalOpen(true)}
            disabled={isGenerating}
            aria-label={`${t("Open image")} · ${location.name}`}
          >
            {stageRegenerating && (
              <img
                key={timestamp}
                src={`${plateUrl}?t=${timestamp}`}
                className="hidden"
                onLoad={() => setImgFailed(false)}
                alt=""
                aria-hidden="true"
              />
            )}
            {isGenerating ? (
              <FlowingDotsPlaceholder
                aspect="16 / 9"
                className="h-full"
                label={isQueued ? t("QUEUED") : t("DRAWING…")}
                caption={activeJob ? t("GENERATING NEW PLATE") : t("REBUILDING LOCATION PLATE")}
              />
            ) : imgFailed ? (
              <div className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 bg-surface-container">
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">{t("NO PLATE IMAGE")}</div>
                <div className="font-meta text-[0.5rem] tracking-[0.14em] text-hero-red">{t("OPEN TO GENERATE")}</div>
              </div>
            ) : (
              <>
                <LazyImage
                  src={`${plateUrl}?t=${timestamp}`}
                  alt={location.name}
                  loading="lazy"
                  width={480}
                  height={270}
                  aspect="16/9"
                  containerClassName="aspect-[16/9] w-full"
                  className="object-cover transition-opacity group-hover/cast-card:opacity-90"
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
        <div className="font-display text-[1.35rem] font-bold uppercase leading-none tracking-[-0.04em] text-ink-black">
          {location.name}
        </div>
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
          refreshToken={stageRegenerating ? null : timestamp.toString()}
        />
        {regenError && (
          <div className="mt-3 border-[2px] border-ink-black bg-hero-red p-2 text-[0.72rem] leading-relaxed text-bristol">
            {regenError}
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
            <RegenAction
              assetLabel={location.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed}
              busy={isGenerating || isInstructionBusy}
              busyLabel={isQueued ? t("QUEUED") : t("DRAWING…")}
              error={regenError ?? instructionError}
              lastInstruction={lastAddendum}
              onRegenerate={startRegen}
              onRegenerateWithInstruction={submitInstruction}
            />
            <LocationAppearanceStatesPanel
              projectName={projectName}
              locId={location.id}
              states={location.appearance_states}
            />
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
  const [imgFailed, setImgFailed] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const [activeJob, setActiveJob] = useState<GenerationJob | null>(null);
  const [localRegenError, setLocalRegenError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const [lastAddendum, setLastAddendum] = useState<string | null>(null);
  const regenProp = useRegenProp();
  const regenPropInstructed = useRegenPropWithInstruction();
  const { data: generationJobs } = useGenerationJobs(projectName, activeJob ? [activeJob.id] : []);
  const { data: regenEstimate } = useAssetRegenEstimate(projectName, "prop", prop.id, undefined, isModalOpen);
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(
    projectName,
    `refs/props/${prop.id}/ref.png`,
    isModalOpen,
    timestamp,
  );

  const regenError = localRegenError;

  useEffect(() => {
    const job = generationJobs?.jobs[0];
    if (!job) return;
    const timer = window.setTimeout(() => {
      if (job.status === "complete") {
        setTimestamp(Date.now());
        setImgFailed(false);
        setActiveJob(null);
        setLocalRegenError(null);
      } else if (job.status === "failed") {
        setActiveJob(null);
        setLocalRegenError(job.error ?? "Regeneration failed");
      } else {
        setActiveJob(job);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [generationJobs]);

  useEffect(() => {
    if (!stageRegenerating) {
      const timer = window.setTimeout(() => {
        setTimestamp(Date.now());
        setImgFailed(false);
      }, 0);
      return () => window.clearTimeout(timer);
    }

    const interval = window.setInterval(() => {
      setTimestamp(Date.now());
    }, 2000);
    return () => window.clearInterval(interval);
  }, [stageRegenerating]);

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

  const submitInstruction = (nextInstruction = instruction) => {
    const trimmed = nextInstruction.trim();
    if (!trimmed) {
      setInstructionError("Add a short visual instruction first.");
      return;
    }
    setInstructionError(null);
    setLocalRegenError(null);
    regenPropInstructed.mutate(
      { project: projectName, propId: prop.id, instruction: trimmed },
      {
        onSuccess: (data) => {
          setActiveJob(data.job);
          setLastAddendum(data.addendum);
          setInstruction("");
        },
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Apply & regenerate prop",
              onRetry: () => submitInstruction(trimmed),
            })
          ) {
            return;
          }
          setInstructionError(err.message);
        },
      },
    );
  };

  const isInstructionBusy = regenPropInstructed.isPending;

  const { t } = useI18n();
  const isGenerating = stageRegenerating || regenProp.isPending || !!activeJob;
  const isQueued = activeJob?.status === "queued" || (activeJob && activeJob.queue_position);

  return (
    <>
      <EntityCard
        padding="tight"
        className="group/cast-card"
        media={
          <button
            type="button"
            className="relative block w-full cursor-pointer bg-surface-container text-left focus-visible:outline-[3px] focus-visible:outline-offset-[-3px] focus-visible:outline-hero-red disabled:cursor-wait"
            onClick={() => setIsModalOpen(true)}
            disabled={isGenerating}
            aria-label={`${t("Open image")} · ${prop.name}`}
          >
            {stageRegenerating && (
              <img
                key={timestamp}
                src={`${refUrl}?t=${timestamp}`}
                className="hidden"
                onLoad={() => setImgFailed(false)}
                alt=""
                aria-hidden="true"
              />
            )}
            {isGenerating ? (
              <FlowingDotsPlaceholder
                aspect="1 / 1"
                className="h-full"
                label={isQueued ? t("QUEUED") : t("DRAWING…")}
                caption={activeJob ? t("GENERATING NEW PROP") : t("REBUILDING PROP REF")}
              />
            ) : imgFailed ? (
              <div className="flex aspect-square w-full flex-col items-center justify-center gap-2 bg-surface-container">
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">{t("NO REF IMAGE")}</div>
                <div className="font-meta text-[0.5rem] tracking-[0.14em] text-hero-red">{t("OPEN TO GENERATE")}</div>
              </div>
            ) : (
              <>
                <LazyImage
                  src={`${refUrl}?t=${timestamp}`}
                  alt={prop.name}
                  loading="lazy"
                  width={400}
                  height={400}
                  aspect="1/1"
                  containerClassName="aspect-square w-full"
                  className="object-cover transition-opacity group-hover/cast-card:opacity-90"
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
        <div className="font-display text-[1.35rem] font-bold uppercase leading-none tracking-[-0.04em] text-ink-black">
          {prop.name}
        </div>
        {prop.first_appearance_scene && (
          <div className="mt-2 font-body text-[0.92rem] font-semibold text-ink-black/55">
            First seen: {prop.first_appearance_scene}
          </div>
        )}
        {regenError && (
          <div className="mt-3 border-[2px] border-ink-black bg-hero-red p-2 text-[0.72rem] leading-relaxed text-bristol">
            {regenError}
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
            <RegenAction
              assetLabel={prop.name}
              cost={regenEstimate}
              instructionCost={regenEstimate?.instruction_estimate}
              hasImage={!imgFailed}
              busy={isGenerating || isInstructionBusy}
              busyLabel={isQueued ? t("QUEUED") : t("DRAWING…")}
              error={regenError ?? instructionError}
              lastInstruction={lastAddendum}
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


export function CastRoom() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: bible, isLoading } = useStoryBible(id);
  const { data: status } = useProjectStatus(id);
  const approveStage = useApproveStage();
  const { mutate: resetStale, isPending: isResetting } = useResetStale();
  const { handleRun, isPending: isPipelineRunning } = useRunAction();
  // The estimate for "adapt" covers the whole auto chain: adapt → plan →
  // storyboard → direct (the backend sums chained stages).
  const { data: chainEstimate } = useStageEstimate(id, "adapt");
  const isCastStageRunning = status?.stages?.cast?.status === "running";
  const stageRegenerating = isCastStageRunning;
  const stageInfo = status?.stages?.cast;
  const stageStatus = stageInfo?.status ?? "pending";
  const checkpointAction = getCastCheckpointAction(stageStatus);
  const isStageStuck = !!stageInfo?.stale;
  const lastProgressAt = stageInfo?.last_progress_at ?? null;
  const needsApproval = stageStatus === "awaiting_review";
  const { data: castResumeEstimate } = useStageEstimate(id, "cast", checkpointAction === "resume");
  const adaptStarted = status?.stages?.adapt?.status != null && status.stages.adapt.status !== "pending";
  const autoStartedCast = useRef<string | null>(null);

  // Manual ref generation writes the assets but does not advance the cast
  // stage lifecycle. Reconcile a pending cast stage on room entry so those
  // assets can be reviewed and approved (and any missing assets are filled).
  useEffect(() => {
    if (!id || !bible || !status?.style_selected || stageStatus !== "pending") return;
    if (autoStartedCast.current === id) return;
    autoStartedCast.current = id;
    handleRun(id, "cast", { actionLabel: "Cast characters & places" });
  }, [id, bible, status?.style_selected, stageStatus, handleRun]);

  function handleContinueToPanels() {
    if (!id) return;
    if (checkpointAction === "resume") {
      // A normal stage run preserves successful cast artifacts. The Cast
      // stage skips existing files and generates only what the interrupted
      // run left behind.
      handleRun(id, "cast", { actionLabel: "Resume cast characters & places" });
    } else if (checkpointAction === "approve") {
      approveStage.mutate(
        { project: id, stage: "cast" },
        {
          onSuccess: () => {
            // Cast approval kicks the auto chain; the user watches it from
            // the Panels station, where "Draw all panels" comes next.
            if (!adaptStarted) handleRun(id, "adapt", { actionLabel: "Plan shots and write prompts" });
            navigate(`/project/${id}/draw`);
          },
        },
      );
    } else if (checkpointAction === "continue") {
      navigate(`/project/${id}/draw`);
    }
  }

  function handleResetStale() {
    if (!id) return;
    resetStale({ project: id });
  }

  function handleContinueStale() {
    if (!id) return;
    handleRun(id, "cast", { actionLabel: "Continue CAST" });
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
        />
      </RoomShell>
    );
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker="LOOK"
        title="CONFIRM CHARACTERS & PLACES"
        lead="These references guide every panel. Open only the people or places that need a fix."
      />

      {isStageStuck && (
        <StaleStripe
          lastProgressAt={lastProgressAt}
          onContinue={handleContinueStale}
          onReset={handleResetStale}
          continuing={isPipelineRunning}
          resetting={isResetting}
          stageLabel="CAST"
          itemLabel="cast images"
        />
      )}

      <section className="space-y-10">
        <div>
          <SectionHeader
            variant="underline"
            title="CHARACTER REFS"
            description="Portrait proofs keep faces, clothing, and silhouettes consistent from scene to scene."
          />
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {bible.characters.map((char) => (
              <CharacterCastCard
                key={char.id}
                character={char}
                projectName={id}
                stageRegenerating={stageRegenerating}
              />
            ))}
          </div>
        </div>

        <div>
          <SectionHeader
            variant="underline"
            title="LOCATION PLATES"
            description="Wide environment plates anchor geography, architecture, light, and atmosphere."
          />
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {bible.locations.map((loc) => (
              <LocationPlateCard
                key={loc.id}
                location={loc}
                projectName={id}
                stageRegenerating={stageRegenerating}
              />
            ))}
          </div>
        </div>

        {bible.props.length > 0 && (
          <div>
            <SectionHeader variant="underline" title="PROP REFS" />
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {bible.props.map((prop) => (
                <PropRefCard
                  key={prop.id}
                  prop={prop}
                  projectName={id}
                  stageRegenerating={stageRegenerating}
                />
              ))}
            </div>
          </div>
        )}
      </section>

      <ApprovalBar
        next={checkpointAction === "resume"
          ? "Some cast references did not finish — resume from the missing images"
          : needsApproval
          ? "Scenewright plans shots and writes prompts — automatically"
          : stageStatus === "complete"
            ? "Draw your panels at the Panels station"
            : "Scenewright is drawing your cast"}
        estimateCredits={checkpointAction === "resume"
          ? castResumeEstimate?.estimate_credits
          : needsApproval
            ? chainEstimate?.estimate_credits
            : null}
        primaryLabel={checkpointAction === "resume"
          ? "↺ RESUME CAST"
          : needsApproval
            ? "LOOKS RIGHT — CONTINUE →"
            : "GO TO PANELS →"}
        onPrimary={handleContinueToPanels}
        primaryDisabled={approveStage.isPending || isPipelineRunning || checkpointAction === "wait"}
        busy={approveStage.isPending || isPipelineRunning}
        secondary={<RerunStageAction project={id} stage="cast" label="cast" disabled={stageRegenerating} />}
      />
    </RoomShell>
  );
}
