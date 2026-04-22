import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { SectionLabel } from "../SectionLabel";
import { useRegenPlate, useRegenRef, useStoryBible } from "../../api/queries";
import { ImageModal } from "../ui/ImageModal";
import { LazyImage } from "../ui/LazyImage";
import { StyleCallout } from "./StyleCallout";
import { useActiveRegens, useRegenStore } from "../../store/regen";
import { useJobPoller } from "../../hooks/useJobPoller";
import { useState } from "react";
import { useI18n } from "../../i18n";

interface ReviewCastStepProps {
  project: string;
  onApprove: () => void;
  isApproving: boolean;
}

export function ReviewCastStep({ project, onApprove, isApproving }: ReviewCastStepProps) {
  const { t } = useI18n();
  const { data: storyBible } = useStoryBible(project);
  const [modalImage, setModalImage] = useState<{ src: string; alt: string } | null>(null);
  const regenRef = useRegenRef();
  const regenPlate = useRegenPlate();

  const activeMap = useActiveRegens(project);
  const bustTimestamps = useRegenStore((s) => s.bustTimestamps);
  const errors = useRegenStore((s) => s.errors);
  const begin = useRegenStore((s) => s.begin);
  const attachJob = useRegenStore((s) => s.attachJob);
  const failRegen = useRegenStore((s) => s.fail);

  useJobPoller(project);

  const regenError = Object.entries(errors)
    .filter(([k]) => k.startsWith(`${project}/`))
    .map(([, v]) => v)[0] ?? null;

  function startRefRegen(id: string) {
    const key = `ref:${id}`;
    begin(project, key);
    regenRef.mutate(
      { project, charId: id },
      {
        onSuccess: (data) => attachJob(project, key, data.job),
        onError: (err) => failRegen(project, key, err.message),
      },
    );
  }

  function startPlateRegen(id: string) {
    const key = `plate:${id}`;
    begin(project, key);
    regenPlate.mutate(
      { project, locId: id },
      {
        onSuccess: (data) => attachJob(project, key, data.job),
        onError: (err) => failRegen(project, key, err.message),
      },
    );
  }

  const activeList = Object.values(activeMap);
  const runningCount = activeList.filter((r) => r.status === "running").length;
  const queuedCount = activeList.length - runningCount;
  const isRegenerating = activeList.length > 0 || regenRef.isPending || regenPlate.isPending;

  return (
    <div className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="sage">{t("REVIEW CHECKPOINT")}</SectionLabel>
        <h1 className="mt-4 display-headline">{t("CAST & LOCATIONS")}</h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          Review character reference sheets and location plates.
          These visuals anchor every downstream image generation.
        </p>
        {activeList.length > 0 && (
          <div className="mt-4 border-[2px] border-ink-black bg-narrator-gold p-3">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 animate-pulse bg-hero-red" />
              <span className="font-meta text-[0.48rem] tracking-[0.16em]">
                {t("REGENERATION QUEUE")}
              </span>
            </div>
            <div className="mt-1 font-display text-[1rem] font-bold tracking-[-0.04em]">
              {runningCount} running / {queuedCount} queued
            </div>
          </div>
        )}
        {regenError && (
          <div className="mt-4 border-[2px] border-ink-black bg-hero-red p-3 text-bristol">
            <div className="font-meta text-[0.48rem] tracking-[0.16em]">{t("REGENERATION FAILED")}</div>
            <div className="mt-1 text-[0.78rem] leading-relaxed">{regenError}</div>
          </div>
        )}
      </Card>

      <Card className="p-5">
        <div className="space-y-2">
          <div className="border-b-[2px] border-ink-black pb-2 font-display text-[1rem] font-bold tracking-[-0.04em]">
            {t("CHARACTER REFS")}
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {storyBible?.characters.map((c) => {
              const key = `ref:${c.id}`;
              const bust = bustTimestamps[`${project}/${key}`] ?? 0;
              const src = `/api/projects/${encodeURIComponent(project)}/files/refs/${c.id}/sheet.png${bust ? `?t=${bust}` : ""}`;
              const active = activeMap[key];
              return (
                <div key={c.id} className="border-[2px] border-ink-black bg-pulp-paper">
                  <div
                    className="relative flex aspect-square cursor-pointer items-center justify-center bg-ink-black/5"
                    onClick={() => setModalImage({ src, alt: c.name })}
                  >
                    <LazyImage
                      src={src}
                      alt={c.name}
                      containerClassName="h-full w-full"
                      className="h-full w-full object-cover hover:opacity-90 transition-opacity"
                      loading="lazy"
                    />
                    {active && (
                      <div className="absolute inset-0 flex items-center justify-center bg-ink-black/65">
                        <div className="text-center">
                          <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-narrator-gold animate-pulse">
                            {active.status === "running" ? t("RUNNING") : t("QUEUED")}
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
                      onClick={() => startRefRegen(c.id)}
                    >
                      {active ? t("QUEUED") : t("REGEN")}
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
            {t("LOCATION PLATES")}
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {storyBible?.locations.map((l) => {
              const key = `plate:${l.id}`;
              const bust = bustTimestamps[`${project}/${key}`] ?? 0;
              const src = `/api/projects/${encodeURIComponent(project)}/files/plates/${l.id}.png${bust ? `?t=${bust}` : ""}`;
              const active = activeMap[key];
              return (
                <div key={l.id} className="border-[2px] border-ink-black bg-pulp-paper">
                  <div
                    className="relative flex aspect-video cursor-pointer items-center justify-center bg-ink-black/5"
                    onClick={() => setModalImage({ src, alt: l.name })}
                  >
                    <LazyImage
                      src={src}
                      alt={l.name}
                      containerClassName="h-full w-full"
                      className="h-full w-full object-cover hover:opacity-90 transition-opacity"
                      loading="lazy"
                    />
                    {active && (
                      <div className="absolute inset-0 flex items-center justify-center bg-ink-black/65">
                        <div className="text-center">
                          <div className="font-display text-[1rem] font-bold tracking-[-0.04em] text-narrator-gold animate-pulse">
                            {active.status === "running" ? t("RUNNING") : t("QUEUED")}
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
                      onClick={() => startPlateRegen(l.id)}
                    >
                      {active ? t("QUEUED") : t("REGEN")}
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
          {isApproving ? t("APPROVING…") : t("APPROVE & CONTINUE")}
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
