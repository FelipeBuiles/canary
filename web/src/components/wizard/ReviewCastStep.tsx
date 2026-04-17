import { useEffect, useState } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { SectionLabel } from "../SectionLabel";
import { useGenerationJobs, useRegenPlate, useRegenRef, useStoryBible } from "../../api/queries";
import { ImageModal } from "../ui/ImageModal";
import { StyleCallout } from "./StyleCallout";

interface ReviewCastStepProps {
  project: string;
  onApprove: () => void;
  isApproving: boolean;
}

type RegenType = "ref" | "plate";

interface ActiveRegen {
  key: string;
  type: RegenType;
  id: string;
  label: string;
  jobId: string | null;
  status: "queued" | "running";
  queuePosition: number | null;
}

export function ReviewCastStep({ project, onApprove, isApproving }: ReviewCastStepProps) {
  const { data: storyBible } = useStoryBible(project);
  const [modalImage, setModalImage] = useState<{ src: string; alt: string } | null>(null);
  const [activeRegens, setActiveRegens] = useState<Record<string, ActiveRegen>>({});
  const [regenError, setRegenError] = useState<string | null>(null);
  const [cacheBusters, setCacheBusters] = useState<Record<string, number>>({});
  const regenRef = useRegenRef();
  const regenPlate = useRegenPlate();
  const regenJobIds = Object.values(activeRegens)
    .map((regen) => regen.jobId)
    .filter((jobId): jobId is string => !!jobId);
  const { data: generationJobs } = useGenerationJobs(project, regenJobIds);

  useEffect(() => {
    if (!generationJobs?.jobs.length) return;

    const activeByJobId = new Map(
      Object.values(activeRegens)
        .filter((regen) => regen.jobId)
        .map((regen) => [regen.jobId, regen] as const),
    );

    for (const job of generationJobs.jobs) {
      const active = activeByJobId.get(job.id);
      if (!active) continue;

      if (job.status === "complete") {
        setActiveRegens((current) => {
          const { [active.key]: _done, ...rest } = current;
          return rest;
        });
        setCacheBusters((busters) => ({ ...busters, [active.key]: Date.now() }));
        setRegenError(null);
      } else if (job.status === "failed") {
        setActiveRegens((current) => {
          const { [active.key]: _failed, ...rest } = current;
          return rest;
        });
        setRegenError(`${active.label}: ${job.error ?? "Regeneration failed"}`);
      } else {
        const nextStatus = job.status === "running" ? "running" : "queued";
        setActiveRegens((current) => {
          const currentActive = current[active.key];
          if (!currentActive) return current;
          if (
            currentActive.status === nextStatus &&
            currentActive.queuePosition === job.queue_position
          ) {
            return current;
          }
          return {
            ...current,
            [active.key]: {
              ...currentActive,
              status: nextStatus,
              queuePosition: job.queue_position,
            },
          };
        });
      }
    }
  }, [generationJobs, activeRegens]);

  function beginRegen(type: RegenType, id: string, label: string) {
    const key = `${type}:${id}`;
    setActiveRegens((current) => ({
      ...current,
      [key]: { key, type, id, label, jobId: null, status: "queued", queuePosition: null },
    }));
    setRegenError(null);
    return key;
  }

  function attachJob(key: string, jobId: string, status: "queued" | "running", queuePosition: number | null) {
    setActiveRegens((current) => {
      const active = current[key];
      if (!active) return current;
      return {
        ...current,
        [key]: {
          ...active,
          jobId,
          status,
          queuePosition,
        },
      };
    });
  }

  function failRegen(key: string, message: string) {
    setActiveRegens((current) => {
      const { [key]: _failed, ...rest } = current;
      return rest;
    });
    setRegenError(message);
  }

  function startRefRegen(id: string, label: string) {
    const key = beginRegen("ref", id, label);
    regenRef.mutate(
      { project, charId: id },
      {
        onSuccess: (data) => attachJob(
          key,
          data.job.id,
          data.job.status === "running" ? "running" : "queued",
          data.job.queue_position,
        ),
        onError: (err) => {
          failRegen(key, err.message);
        },
      },
    );
  }

  function startPlateRegen(id: string, label: string) {
    const key = beginRegen("plate", id, label);
    regenPlate.mutate(
      { project, locId: id },
      {
        onSuccess: (data) => attachJob(
          key,
          data.job.id,
          data.job.status === "running" ? "running" : "queued",
          data.job.queue_position,
        ),
        onError: (err) => {
          failRegen(key, err.message);
        },
      },
    );
  }

  const activeList = Object.values(activeRegens);
  const runningCount = activeList.filter((regen) => regen.status === "running").length;
  const queuedCount = activeList.length - runningCount;
  const isRegenerating = activeList.length > 0 || regenRef.isPending || regenPlate.isPending;

  return (
    <div className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="sage">REVIEW CHECKPOINT</SectionLabel>
        <h1 className="mt-4 display-headline">CAST & LOCATIONS</h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          Review character reference sheets and location plates.
          These visuals anchor every downstream image generation.
        </p>
        {activeList.length > 0 && (
          <div className="mt-4 border-[2px] border-ink-black bg-narrator-gold p-3">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 animate-pulse bg-hero-red" />
              <span className="font-meta text-[0.48rem] tracking-[0.16em]">
                REGENERATION QUEUE
              </span>
            </div>
            <div className="mt-1 font-display text-[1rem] font-bold tracking-[-0.04em]">
              {runningCount} running / {queuedCount} queued
            </div>
          </div>
        )}
        {regenError && (
          <div className="mt-4 border-[2px] border-ink-black bg-hero-red p-3 text-bristol">
            <div className="font-meta text-[0.48rem] tracking-[0.16em]">REGENERATION FAILED</div>
            <div className="mt-1 text-[0.78rem] leading-relaxed">{regenError}</div>
          </div>
        )}
      </Card>

      <Card className="p-5">
        <div className="space-y-2">
          <div className="border-b-[2px] border-ink-black pb-2 font-display text-[1rem] font-bold tracking-[-0.04em]">
            CHARACTER REFS
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {storyBible?.characters.map((c) => {
              const bust = cacheBusters[`ref:${c.id}`] ?? 0;
              const src = `/api/projects/${encodeURIComponent(project)}/files/refs/${c.id}/sheet.png${bust ? `?t=${bust}` : ""}`;
              const active = activeRegens[`ref:${c.id}`];
              return (
                <div key={c.id} className="border-[2px] border-ink-black bg-pulp-paper">
                  <div 
                    className="relative flex aspect-square cursor-pointer items-center justify-center bg-ink-black/5"
                    onClick={() => setModalImage({ src, alt: c.name })}
                  >
                    <img
                      src={src}
                      alt={c.name}
                      className="h-full w-full object-cover hover:opacity-90 transition-opacity"
                      loading="lazy"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = "none";
                      }}
                    />
                    {active && (
                      <div className="absolute inset-0 flex items-center justify-center bg-ink-black/65">
                        <div className="text-center">
                          <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-narrator-gold animate-pulse">
                            {active.status === "running" ? "RUNNING" : "QUEUED"}
                          </div>
                          {active.queuePosition && (
                            <div className="mt-1 font-meta text-[0.48rem] tracking-[0.16em] text-bristol/70">
                              POSITION {active.queuePosition}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center justify-between gap-2 p-2">
                    <div className="font-display text-[0.82rem] font-bold tracking-[-0.03em]">{c.name}</div>
                    <Button
                      size="xs"
                      variant="secondary"
                      disabled={!!active}
                      onClick={() => startRefRegen(c.id, c.name)}
                    >
                      {active ? "QUEUED" : "REGEN"}
                    </Button>
                  </div>
                </div>
              );
            }) ?? (
              <div className="col-span-full py-4 text-center text-[0.78rem] text-ink-black/40">
                No character data available.
              </div>
            )}
          </div>
        </div>
      </Card>

      <Card className="p-5">
        <div className="space-y-2">
          <div className="border-b-[2px] border-ink-black pb-2 font-display text-[1rem] font-bold tracking-[-0.04em]">
            LOCATION PLATES
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {storyBible?.locations.map((l) => {
              const bust = cacheBusters[`plate:${l.id}`] ?? 0;
              const src = `/api/projects/${encodeURIComponent(project)}/files/plates/${l.id}.png${bust ? `?t=${bust}` : ""}`;
              const active = activeRegens[`plate:${l.id}`];
              return (
                <div key={l.id} className="border-[2px] border-ink-black bg-pulp-paper">
                  <div 
                    className="relative flex aspect-video cursor-pointer items-center justify-center bg-ink-black/5"
                    onClick={() => setModalImage({ src, alt: l.name })}
                  >
                    <img
                      src={src}
                      alt={l.name}
                      className="h-full w-full object-cover hover:opacity-90 transition-opacity"
                      loading="lazy"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = "none";
                      }}
                    />
                    {active && (
                      <div className="absolute inset-0 flex items-center justify-center bg-ink-black/65">
                        <div className="text-center">
                          <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-narrator-gold animate-pulse">
                            {active.status === "running" ? "RUNNING" : "QUEUED"}
                          </div>
                          {active.queuePosition && (
                            <div className="mt-1 font-meta text-[0.48rem] tracking-[0.16em] text-bristol/70">
                              POSITION {active.queuePosition}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center justify-between gap-2 p-2">
                    <div className="font-display text-[0.82rem] font-bold tracking-[-0.03em]">{l.name}</div>
                    <Button
                      size="xs"
                      variant="secondary"
                      disabled={!!active}
                      onClick={() => startPlateRegen(l.id, l.name)}
                    >
                      {active ? "QUEUED" : "REGEN"}
                    </Button>
                  </div>
                </div>
              );
            }) ?? (
              <div className="col-span-full py-4 text-center text-[0.78rem] text-ink-black/40">
                No location data available.
              </div>
            )}
          </div>
        </div>
      </Card>

      <div className="flex items-center gap-4">
        <StyleCallout project={project} />
        <Button size="lg" onClick={onApprove} disabled={isApproving || isRegenerating}>
          {isApproving ? "APPROVING…" : "APPROVE & CONTINUE"}
        </Button>
        <span className="text-[0.72rem] text-ink-black/40">
          Regenerate any reference that does not match the story bible before continuing.
        </span>
      </div>

      <ImageModal 
        isOpen={!!modalImage} 
        onClose={() => setModalImage(null)} 
        src={modalImage?.src ?? ""} 
        alt={modalImage?.alt ?? ""} 
      />
    </div>
  );
}
