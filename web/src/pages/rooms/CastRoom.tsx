import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useGenerationJobs,
  usePrimaryRefs,
  useProjectStatus,
  useSetPrimaryRef,
  useStageEstimate,
  useStoryBible,
  useRegenRef,
  useRegenRefWithInstruction,
  useRegenPlate,
  useRegenPlateWithInstruction,
  useRegenProp,
  useRegenPropWithInstruction,
} from "../../api/queries";
import { ApprovalBar, RoomHeader, RoomShell, RerunStageAction, StagePlaceholder, SectionHeader, EntityCard } from "../../components/composites";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import { useRunAction } from "../../hooks/useRunAction";
import { Tag } from "../../components/ui/Tag";
import { Button } from "../../components/ui/Button";
import { DestructiveButton } from "../../components/ui/DestructiveButton";
import { ImageModal } from "../../components/ui/ImageModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StatusPill } from "../../components/ui/StatusPill";
import type { Character, GenerationJob, Location, Prop } from "../../types/api";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { useI18n } from "../../i18n";
import { FlowingDotsPlaceholder } from "../../components/ui/FlowingDotsPlaceholder";

function queuedLabel(job: GenerationJob | null) {
  if (!job) return "QUEUED";
  if (job.status === "running") return "RUNNING";
  if (job.queue_position) return `QUEUE ${job.queue_position}`;
  return "QUEUED";
}

const REF_POSES = [
  { pose: "front", label: "Front" },
  { pose: "three_quarter", label: "¾ view" },
  { pose: "profile", label: "Profile" },
  { pose: "gesture", label: "Gesture" },
] as const;

/**
 * Reference sheet: the pose crops PULP sends to the image model. Click one
 * to set it as the primary — it then wins ref selection for every panel.
 */
function RefSheet({ projectName, charId, timestamp }: { projectName: string; charId: string; timestamp: number }) {
  const { data: primaryData } = usePrimaryRefs(projectName);
  const setPrimary = useSetPrimaryRef();
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const primaryPose = primaryData?.primary_refs?.[charId];

  const visiblePoses = REF_POSES.filter(({ pose }) => !failed[pose]);
  if (visiblePoses.length === 0) return null;

  return (
    <div>
      <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1.5">
        REFERENCE SHEET · CLICK TO SET PRIMARY
      </div>
      <div className="flex flex-wrap gap-2">
        {visiblePoses.map(({ pose, label }) => {
          const isPrimary = primaryPose === pose;
          const src = `/api/projects/${encodeURIComponent(projectName)}/files/refs/${encodeURIComponent(charId)}/${pose}.png?t=${timestamp}`;
          return (
            <button
              key={pose}
              type="button"
              title={isPrimary ? `${label} — primary ref` : `Set ${label} as primary`}
              onClick={() => setPrimary.mutate({ project: projectName, charId, pose: isPrimary ? null : pose })}
              disabled={setPrimary.isPending}
              className={`relative w-[64px] overflow-hidden border-[2px] transition-colors ${
                isPrimary ? "border-hero-red" : "border-ink-black/15 hover:border-ink-black/50"
              }`}
            >
              <img
                src={src}
                alt={`${label} reference`}
                className="aspect-[64/84] w-full object-cover"
                onError={() => setFailed((f) => ({ ...f, [pose]: true }))}
              />
              {isPrimary && (
                <span className="absolute inset-x-0 bottom-0 bg-hero-red py-0.5 text-center font-meta text-[0.42rem] tracking-[0.14em] text-bristol">
                  PRIMARY
                </span>
              )}
            </button>
          );
        })}
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

  const handleRegen = (e: React.MouseEvent) => {
    e.stopPropagation();
    startRegen();
  };

  const submitInstruction = () => {
    const trimmed = instruction.trim();
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
              onRetry: submitInstruction,
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
        interactive={!isGenerating && !imgFailed}
        padding="tight"
        className="group/cast-card"
        media={
          <div
            className="relative cursor-pointer bg-surface-container"
            onClick={() => !imgFailed && !isGenerating && setIsModalOpen(true)}
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
                <DestructiveButton size="sm" onClick={handleRegen}>{t("GENERATE")}</DestructiveButton>
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
          </div>
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
        alt={character.name}
        title={character.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1.5">REQUEST A FIX</div>
              {lastAddendum && (
                <details className="mb-2 border-[2px] border-archive-sage/40 bg-archive-sage/8">
                  <summary className="cursor-pointer px-2 py-1.5 font-meta text-[0.55rem] tracking-[0.16em] text-archive-sage">
                    APPLIED ON LAST REGEN ↓
                  </summary>
                  <p className="px-2 pb-2 pt-1 text-[0.72rem] leading-5 text-ink-black/70">
                    {lastAddendum}
                  </p>
                </details>
              )}
              <textarea
                value={instruction}
                onChange={(e) => {
                  setInstruction(e.target.value);
                  if (instructionError) setInstructionError(null);
                }}
                maxLength={500}
                rows={2}
                className="w-full resize-none border-[2px] border-ink-black/25 bg-bristol px-3 py-2 font-body text-[0.82rem] leading-5 text-ink-black outline-none focus:border-ink-black"
                placeholder="Describe what to change visually…"
                disabled={isInstructionBusy || !!activeJob}
              />
              {instructionError && (
                <p className="mt-1 text-[0.72rem] text-hero-red">{instructionError}</p>
              )}
              <Button
                className="mt-2 w-full"
                size="sm"
                onClick={submitInstruction}
                disabled={isInstructionBusy || !!activeJob || !instruction.trim()}
              >
                {isInstructionBusy ? "APPLYING..." : "APPLY & REGEN"}
              </Button>
            </div>
            <RefSheet projectName={projectName} charId={character.id} timestamp={timestamp} />
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
          </div>
        )}
        actions={(
          <>
            <Button variant="outline" size="sm" onClick={() => setIsModalOpen(false)}>
              CLOSE
            </Button>
            <DestructiveButton
              size="sm"
              onClick={handleRegen}
              disabled={regenRef.isPending || !!activeJob}
            >
              {regenRef.isPending || activeJob ? queuedLabel(activeJob) : "REGENERATE"}
            </DestructiveButton>
          </>
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

  const handleRegen = (e: React.MouseEvent) => {
    e.stopPropagation();
    setLocalRegenError(null);
    regenPlate.mutate(
      { project: projectName, locId: location.id },
      {
        onSuccess: (data) => setActiveJob(data.job),
        onError: (err) => {
          if (
            maybeShowInsufficientCredits(err, {
              actionLabel: "Regenerate location plate",
            })
          ) {
            return;
          }
          setLocalRegenError(err.message);
        },
      }
    );
  };

  const submitInstruction = () => {
    const trimmed = instruction.trim();
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
              onRetry: submitInstruction,
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
        interactive={!isGenerating && !imgFailed}
        padding="tight"
        className="group/cast-card"
        media={
          <div
            className="relative cursor-pointer bg-surface-container"
            onClick={() => !imgFailed && !isGenerating && setIsModalOpen(true)}
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
                <DestructiveButton size="sm" onClick={handleRegen}>{t("GENERATE")}</DestructiveButton>
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
          </div>
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
        alt={location.name}
        title={location.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1.5">REQUEST A FIX</div>
              {lastAddendum && (
                <details className="mb-2 border-[2px] border-archive-sage/40 bg-archive-sage/8">
                  <summary className="cursor-pointer px-2 py-1.5 font-meta text-[0.55rem] tracking-[0.16em] text-archive-sage">
                    APPLIED ON LAST REGEN ↓
                  </summary>
                  <p className="px-2 pb-2 pt-1 text-[0.72rem] leading-5 text-ink-black/70">
                    {lastAddendum}
                  </p>
                </details>
              )}
              <textarea
                value={instruction}
                onChange={(e) => {
                  setInstruction(e.target.value);
                  if (instructionError) setInstructionError(null);
                }}
                maxLength={500}
                rows={2}
                className="w-full resize-none border-[2px] border-ink-black/25 bg-bristol px-3 py-2 font-body text-[0.82rem] leading-5 text-ink-black outline-none focus:border-ink-black"
                placeholder="Describe what to change visually…"
                disabled={isInstructionBusy || !!activeJob}
              />
              {instructionError && (
                <p className="mt-1 text-[0.72rem] text-hero-red">{instructionError}</p>
              )}
              <Button
                className="mt-2 w-full"
                size="sm"
                onClick={submitInstruction}
                disabled={isInstructionBusy || !!activeJob || !instruction.trim()}
              >
                {isInstructionBusy ? "APPLYING..." : "APPLY & REGEN"}
              </Button>
            </div>
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
          </div>
        )}
        actions={(
          <>
            <Button variant="outline" size="sm" onClick={() => setIsModalOpen(false)}>
              CLOSE
            </Button>
            <DestructiveButton
              size="sm"
              onClick={handleRegen}
              disabled={regenPlate.isPending || !!activeJob}
            >
              {regenPlate.isPending || activeJob ? queuedLabel(activeJob) : "REGENERATE"}
            </DestructiveButton>
          </>
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

  const handleRegen = (e: React.MouseEvent) => {
    e.stopPropagation();
    startRegen();
  };

  const submitInstruction = () => {
    const trimmed = instruction.trim();
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
              onRetry: submitInstruction,
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
        interactive={!isGenerating && !imgFailed}
        padding="tight"
        className="group/cast-card"
        media={
          <div
            className="relative cursor-pointer bg-surface-container"
            onClick={() => !imgFailed && !isGenerating && setIsModalOpen(true)}
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
                <DestructiveButton size="sm" onClick={handleRegen}>{t("GENERATE")}</DestructiveButton>
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
          </div>
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
        alt={prop.name}
        title={prop.name.toUpperCase()}
        sidebar={(
          <div className="space-y-5">
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40 mb-1.5">REQUEST A FIX</div>
              {lastAddendum && (
                <details className="mb-2 border-[2px] border-archive-sage/40 bg-archive-sage/8">
                  <summary className="cursor-pointer px-2 py-1.5 font-meta text-[0.55rem] tracking-[0.16em] text-archive-sage">
                    APPLIED ON LAST REGEN ↓
                  </summary>
                  <p className="px-2 pb-2 pt-1 text-[0.72rem] leading-5 text-ink-black/70">
                    {lastAddendum}
                  </p>
                </details>
              )}
              <textarea
                value={instruction}
                onChange={(e) => {
                  setInstruction(e.target.value);
                  if (instructionError) setInstructionError(null);
                }}
                maxLength={500}
                rows={2}
                className="w-full resize-none border-[2px] border-ink-black/25 bg-bristol px-3 py-2 font-body text-[0.82rem] leading-5 text-ink-black outline-none focus:border-ink-black"
                placeholder="Describe what to change visually…"
                disabled={isInstructionBusy || !!activeJob}
              />
              {instructionError && (
                <p className="mt-1 text-[0.72rem] text-hero-red">{instructionError}</p>
              )}
              <Button
                className="mt-2 w-full"
                size="sm"
                onClick={submitInstruction}
                disabled={isInstructionBusy || !!activeJob || !instruction.trim()}
              >
                {isInstructionBusy ? "APPLYING..." : "APPLY & REGEN"}
              </Button>
            </div>
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
          </div>
        )}
        actions={(
          <>
            <Button variant="outline" size="sm" onClick={() => setIsModalOpen(false)}>
              CLOSE
            </Button>
            <DestructiveButton
              size="sm"
              onClick={handleRegen}
              disabled={regenProp.isPending || !!activeJob}
            >
              {regenProp.isPending || activeJob ? queuedLabel(activeJob) : "REGENERATE"}
            </DestructiveButton>
          </>
        )}
      />
    </>
  );
}


export function CastRoom() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { isCompact, toggle } = useHeaderMode();
  const { data: bible, isLoading } = useStoryBible(id);
  const { data: status } = useProjectStatus(id);
  const approveStage = useApproveStage();
  const { handleRun, isPending: isPipelineRunning } = useRunAction();
  // The estimate for "adapt" covers the whole auto chain: adapt → plan →
  // storyboard → direct (the backend sums chained stages).
  const { data: chainEstimate } = useStageEstimate(id, "adapt");
  const isCastStageRunning = status?.stages?.cast?.status === "running";
  const stageRegenerating = isCastStageRunning;
  const stageInfo = status?.stages?.cast;
  const stageStatus = stageInfo?.status ?? "pending";
  const needsApproval = stageStatus === "awaiting_review";
  const adaptStarted = status?.stages?.adapt?.status != null && status.stages.adapt.status !== "pending";

  function handleContinueToPanels() {
    if (!id) return;
    if (needsApproval) {
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
    } else {
      navigate(`/project/${id}/draw`);
    }
  }

  if (isLoading || (!bible && stageStatus !== "pending")) {
    return (
      <RoomShell
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
      <RoomShell>
        <StagePlaceholder
          stage="cast"
          status={stageStatus}
          itemsDone={stageInfo?.items_done}
          itemsTotal={stageInfo?.items_total}
        />
      </RoomShell>
    );
  }

  return (
    <RoomShell>
      <RoomHeader
        kicker="LOOK"
        compact={isCompact}
        onToggle={toggle}
        title="CHARACTERS & PLACES"
        lead="How your cast and settings will look in every panel. Re-roll any one of them, or open it to request a fix."
      />

      <section className="space-y-10">
        <div className="grid gap-10 xl:grid-cols-2">
          <div>
            <SectionHeader variant="underline" title="CHARACTER REFS" />
            <div className="grid gap-5 sm:grid-cols-2">
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
            <SectionHeader variant="underline" title="LOCATION PLATES" />
            <div className="grid gap-5 sm:grid-cols-2">
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
        next={needsApproval
          ? "PULP plans shots and writes prompts — automatically"
          : stageStatus === "complete"
            ? "Draw your panels at the Panels station"
            : "PULP is drawing your cast"}
        estimateCredits={needsApproval ? chainEstimate?.estimate_credits : null}
        primaryLabel={needsApproval ? "LOOKS RIGHT — CONTINUE →" : "GO TO PANELS →"}
        onPrimary={handleContinueToPanels}
        primaryDisabled={approveStage.isPending || isPipelineRunning || isCastStageRunning || stageStatus === "pending"}
        busy={approveStage.isPending}
        secondary={<RerunStageAction project={id} stage="cast" label="Re-cast" disabled={stageRegenerating} />}
      />
    </RoomShell>
  );
}
