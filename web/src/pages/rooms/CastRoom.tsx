import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useGenerationJobs, useProjectStatus, useStoryBible, useRegenRef, useRegenPlate } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Tag } from "../../components/ui/Tag";
import { Button } from "../../components/ui/Button";
import { DestructiveButton } from "../../components/ui/DestructiveButton";
import { RoomShell } from "../../components/ui/RoomShell";
import { ImageModal } from "../../components/ui/ImageModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StatusPill } from "../../components/ui/StatusPill";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import type { Character, GenerationJob, Location } from "../../types/api";

function queuedLabel(job: GenerationJob | null) {
  if (!job) return "QUEUED";
  if (job.status === "running") return "RUNNING";
  if (job.queue_position) return `QUEUE ${job.queue_position}`;
  return "QUEUED";
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
  const regenRef = useRegenRef();
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

  const handleRegen = (e: React.MouseEvent) => {
    e.stopPropagation();
    setRegenError(null);
    regenRef.mutate(
      { project: projectName, charId: character.id },
      {
        onSuccess: (data) => setActiveJob(data.job),
        onError: (err) => setRegenError(err.message),
      }
    );
  };

  return (
    <>
      <article className="group/cast-card overflow-hidden border-[3px] border-ink-black/8 bg-bristol transition-colors duration-150 hover:border-ink-black">
        <div 
          className="relative cursor-pointer bg-surface-container"
          onClick={() => !imgFailed && setIsModalOpen(true)}
        >
          {imgFailed ? (
            <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 bg-surface-container">
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
              {stageRegenerating ? (
                <>
                  <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-ink-black/50 animate-pulse">
                    REGENERATING…
                  </div>
                  <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/45">
                    REBUILDING CAST REF
                  </div>
                </>
              ) : regenRef.isPending || activeJob ? (
                <>
                  <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-ink-black/50 animate-pulse">
                    {queuedLabel(activeJob)}
                  </div>
                  <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/45">
                    GENERATING NEW REF
                  </div>
                </>
              ) : (
                <>
                  <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">NO REF IMAGE</div>
                  <DestructiveButton size="sm" onClick={handleRegen}>GENERATE</DestructiveButton>
                </>
              )}
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
              {activeJob && (
                <StatusPill tone="gold" className="absolute inset-x-2 bottom-2 justify-center text-center">
                  {queuedLabel(activeJob)}
                </StatusPill>
              )}
              {stageRegenerating && !activeJob && (
                <StatusPill tone="gold" className="absolute inset-x-2 bottom-2 justify-center text-center">
                  CAST STAGE RUNNING
                </StatusPill>
              )}
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/42 opacity-0 transition-opacity duration-150 group-hover/cast-card:opacity-100">
                <span className="border border-bristol bg-transparent px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-bristol">
                  ↗ Full size
                </span>
              </div>
            </>
          )}
          <StatusPill tone="red" className="absolute right-4 top-4">
            REF
          </StatusPill>
        </div>
        <div className="bg-bristol p-5">
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
        </div>
      </article>
      <ImageModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        src={`${refUrl}?t=${timestamp}`}
        alt={character.name}
        title={character.name.toUpperCase()}
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
  const regenPlate = useRegenPlate();
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
        onError: (err) => setLocalRegenError(err.message),
      }
    );
  };

  return (
    <>
      <article className="group/cast-card overflow-hidden border-[3px] border-ink-black/8 bg-bristol transition-colors duration-150 hover:border-ink-black">
        <div 
          className="relative cursor-pointer bg-surface-container"
          onClick={() => !imgFailed && setIsModalOpen(true)}
        >
          {imgFailed ? (
            <div className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 bg-surface-container">
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
              {stageRegenerating ? (
                <>
                  <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-ink-black/50 animate-pulse">
                    REGENERATING…
                  </div>
                  <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/45">
                    REBUILDING LOCATION PLATE
                  </div>
                </>
              ) : regenPlate.isPending || activeJob ? (
                <>
                  <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-ink-black/50 animate-pulse">
                    {queuedLabel(activeJob)}
                  </div>
                  <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/45">
                    GENERATING NEW PLATE
                  </div>
                </>
              ) : (
                <>
                  <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">NO PLATE IMAGE</div>
                  <DestructiveButton size="sm" onClick={handleRegen}>GENERATE</DestructiveButton>
                </>
              )}
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
              {activeJob && (
                <StatusPill tone="gold" className="absolute inset-x-2 bottom-2 justify-center text-center">
                  {queuedLabel(activeJob)}
                </StatusPill>
              )}
              {stageRegenerating && !activeJob && (
                <StatusPill tone="gold" className="absolute inset-x-2 bottom-2 justify-center text-center">
                  CAST STAGE RUNNING
                </StatusPill>
              )}
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/42 opacity-0 transition-opacity duration-150 group-hover/cast-card:opacity-100">
                <span className="border border-bristol bg-transparent px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-bristol">
                  ↗ Full size
                </span>
              </div>
            </>
          )}
        </div>
        <div className="bg-bristol p-5">
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
        </div>
      </article>
      <ImageModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        src={`${plateUrl}?t=${timestamp}`}
        alt={location.name}
        title={location.name.toUpperCase()}
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

export function CastRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: bible, isLoading } = useStoryBible(name);
  const { data: status } = useProjectStatus(name);
  const isCastStageRunning = status?.stages?.cast?.status === "running";
  const stageRegenerating = isCastStageRunning;
  const stageInfo = status?.stages?.cast;
  const stageStatus = stageInfo?.status ?? "pending";

  if (isLoading || (!bible && stageStatus !== "pending")) {
    return <RoomShell isLoading loadingText="LOADING CAST…" />;
  }

  if (!bible || !name) {
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
      <ShowcaseHeader
        label="CAST / CHARACTER & LOCATION REFS"
        title="CASTING CALL"
        lead="Reference sheets and location plates produced by the casting director — each used as the visual anchor for every downstream panel."
        actions={<RerunStageAction project={name} stage="cast" label="Cast" disabled={stageRegenerating} />}
      />

      <section className="grid gap-10 xl:grid-cols-2">
        <div>
          <h2 className="border-b-[2px] border-ink-black pb-3 font-display text-[2.25rem] font-bold uppercase leading-none tracking-[-0.06em] text-ink-black">
            CHARACTER REFS
          </h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            {bible.characters.map((char) => (
              <CharacterCastCard
                key={char.id}
                character={char}
                projectName={name}
                stageRegenerating={stageRegenerating}
              />
            ))}
          </div>
        </div>

        <div>
          <h2 className="border-b-[2px] border-ink-black pb-3 font-display text-[2.25rem] font-bold uppercase leading-none tracking-[-0.06em] text-ink-black">
            LOCATION PLATES
          </h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            {bible.locations.map((loc) => (
              <LocationPlateCard
                key={loc.id}
                location={loc}
                projectName={name}
                stageRegenerating={stageRegenerating}
              />
            ))}
          </div>
        </div>
      </section>
    </RoomShell>
  );
}
