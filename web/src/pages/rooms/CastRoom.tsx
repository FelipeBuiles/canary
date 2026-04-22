import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useGenerationJobs, useProjectStatus, useStoryBible, useRegenRef, useRegenPlate } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { SectionDivider } from "../../components/SectionDivider";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { Button } from "../../components/ui/Button";
import { RoomShell } from "../../components/ui/RoomShell";
import { ImageModal } from "../../components/ui/ImageModal";
import { LazyImage } from "../../components/ui/LazyImage";
import { StatusPill } from "../../components/ui/StatusPill";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
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
      <Card>
        <div 
          className="relative border-b-[2px] border-ink-black bg-ink-black cursor-pointer group"
          onClick={() => !imgFailed && setIsModalOpen(true)}
        >
          {stageRegenerating ? (
            <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
              <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                REGENERATING…
              </div>
              <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
                REBUILDING CAST REF
              </div>
            </div>
          ) : imgFailed ? (
            <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
              {regenRef.isPending || activeJob ? (
                <>
                  <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                    {queuedLabel(activeJob)}
                  </div>
                  <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
                    GENERATING NEW REF
                  </div>
                </>
              ) : (
                <>
                  <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/40">NO REF IMAGE</div>
                  <div className="font-meta text-[0.44rem] tracking-[0.14em] text-bristol/25">RUN CAST</div>
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
                className="object-cover hover:opacity-90 transition-opacity"
                onError={() => setImgFailed(true)}
              />
              {activeJob && (
                <StatusPill tone="gold" className="absolute inset-x-2 bottom-2 justify-center text-center">
                  {queuedLabel(activeJob)}
                </StatusPill>
              )}
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/60 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                <span className="border-[2px] border-bristol bg-ink-black px-3 py-2 font-meta text-[0.62rem] tracking-[0.16em] text-bristol">
                  FULL SIZE
                </span>
              </div>
            </>
          )}
          <StatusPill tone="red" className="absolute right-2 top-2">
            REF
          </StatusPill>
        </div>
        <div className="p-3">
          <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black">
            {character.name}
          </div>
          <div className="mt-1 font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/55">
            {character.age_range} &middot; {character.gender}
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
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
      </Card>
      <ImageModal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        src={`${refUrl}?t=${timestamp}`} 
        alt={character.name} 
        actions={(
          <Button
            size="md"
            onClick={handleRegen}
            disabled={regenRef.isPending || !!activeJob}
          >
            {regenRef.isPending || activeJob ? queuedLabel(activeJob) : "REGENERATE"}
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
      <Card>
        <div 
          className="relative border-b-[2px] border-ink-black bg-ink-black cursor-pointer group"
          onClick={() => !imgFailed && setIsModalOpen(true)}
        >
          {stageRegenerating ? (
            <div className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
              <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                REGENERATING…
              </div>
              <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
                REBUILDING LOCATION PLATE
              </div>
            </div>
          ) : imgFailed ? (
            <div className="flex aspect-[16/9] w-full flex-col items-center justify-center gap-2 bg-ink-black/40">
              {regenPlate.isPending || activeJob ? (
                <>
                  <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                    {queuedLabel(activeJob)}
                  </div>
                  <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
                    GENERATING NEW PLATE
                  </div>
                </>
              ) : (
                <>
                  <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/40">NO PLATE IMAGE</div>
                  <div className="font-meta text-[0.44rem] tracking-[0.14em] text-bristol/25">RUN CAST</div>
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
                className="object-cover hover:opacity-90 transition-opacity"
                onError={() => setImgFailed(true)}
              />
              {activeJob && (
                <StatusPill tone="gold" className="absolute inset-x-2 bottom-2 justify-center text-center">
                  {queuedLabel(activeJob)}
                </StatusPill>
              )}
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/60 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                <span className="border-[2px] border-bristol bg-ink-black px-3 py-2 font-meta text-[0.62rem] tracking-[0.16em] text-bristol">
                  FULL SIZE
                </span>
              </div>
            </>
          )}
        </div>
        <div className="p-3">
          <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black">
            {location.name}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
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
      </Card>
      <ImageModal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        src={`${plateUrl}?t=${timestamp}`} 
        alt={location.name} 
        actions={(
          <Button
            size="md"
            onClick={handleRegen}
            disabled={regenPlate.isPending || !!activeJob}
          >
            {regenPlate.isPending || activeJob ? queuedLabel(activeJob) : "REGENERATE"}
          </Button>
        )}
      />
    </>
  );
}

export function CastRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: bible, isLoading } = useStoryBible(name);
  const { data: status } = useProjectStatus(name);
  const isCastStageRunning = status?.stages?.index?.status === "running";
  const stageRegenerating = isCastStageRunning;

  if (isLoading) {
    return <RoomShell isLoading loadingText="LOADING CAST…" />;
  }

  if (!bible || !name) {
    return (
      <RoomShell
        isEmpty
        emptyTitle="CAST NOT AVAILABLE"
        emptyDescription="Complete EXTRACT and CAST first."
      />
    );
  }

  return (
    <RoomShell>
      <ShowcaseHeader
        label="CAST / CHARACTER & LOCATION REFS"
        title="CASTING CALL"
        lead="Reference sheets and location plates produced by the casting director — each used as the visual anchor for every downstream panel."
        actions={<RerunStageAction project={name} stage="index" label="Cast" disabled={stageRegenerating} />}
      />

      <section className="grid gap-6 xl:grid-cols-2">
        <div>
          <SectionDivider number={1} label="DRAMATIS PERSONAE" />
          <h2 className="mt-3 font-display text-[2.25rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
            CHARACTER REFS
          </h2>
          <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
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
          <SectionDivider number={2} label="THE WORLD STAGE" />
          <h2 className="mt-3 font-display text-[2.25rem] font-bold leading-none tracking-[-0.06em] text-ink-black">
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
