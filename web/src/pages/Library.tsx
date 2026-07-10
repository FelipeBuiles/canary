import { useNavigate } from "react-router-dom";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateProject, useGenerateProjectCover, useProjects, useImportStory } from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { useRunAction } from "../hooks/useRunAction";
import { ProjectCard } from "../components/ProjectCard";
import { Icon } from "../components/ui/Icon";
import { Button } from "../components/ui/Button";
import { LoadingBlock, StateBlock } from "../components/ui/StateBlock";
import { SectionHeader } from "../components/composites";
import { STATIONS } from "../lib/stations";
import { UploadStep } from "../components/wizard/UploadStep";
import type { ConfigOverrides } from "../types/api";
import { useI18n } from "../i18n";

const coverRequestedProjects = new Set<string>();

function FirstIssueInvitation({ onStart }: { onStart: () => void }) {
  const { t } = useI18n();

  return (
    <div className="border-[3px] border-ink-black bg-bristol p-9 shadow-paper-sm sm:p-12">
      <div className="inline-flex bg-hero-red px-3.5 py-1.5 font-meta text-[0.6rem] tracking-[0.24em] text-bristol uppercase">
        {t("ISSUE #0")}
      </div>
      <p className="mt-6 max-w-[36rem] font-display text-[1.8rem] font-black uppercase leading-[0.95] tracking-[-0.04em] text-ink-black sm:text-[2.4rem]">
        {t("Every production starts with a manuscript.")}
      </p>
      <div className="mt-10">
        <div className="font-meta text-[0.56rem] tracking-[0.24em] text-ink-black/45">
          {t("THE PRODUCTION LINE")}
        </div>
        <ol className="mt-4 flex flex-wrap gap-2.5">
          {STATIONS.map((station) => (
            <li
              key={station.key}
              className="flex items-center gap-2 border-[2px] border-ink-black bg-pulp-paper px-3 py-2"
            >
              <span className="font-display text-[0.78rem] font-black leading-none text-ink-black/40">
                {station.number}
              </span>
              <span className="font-meta text-[0.58rem] uppercase leading-none tracking-[0.14em] text-ink-black">
                {t(station.label)}
              </span>
            </li>
          ))}
        </ol>
      </div>
      <div className="mt-10">
        <Button size="lg" onClick={onStart}>{t("START NEW PROJECT")}</Button>
      </div>
    </div>
  );
}

function NewProjectModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const createProject = useCreateProject();
  const importStory = useImportStory();
  const { handleRun } = useRunAction();
  const clearEvents = usePipelineStore((s) => s.clearEvents);
  const { t } = useI18n();

  const handleCreate = useCallback(
    (file: File, name: string, configOverrides?: Partial<ConfigOverrides>) => {
      createProject.mutate(
        { file, name, configOverrides },
        {
          onSuccess: (data) => {
            queryClient.removeQueries({ queryKey: ["project", data.id] });
            clearEvents();
            onClose();
            navigate(`/project/${encodeURIComponent(data.id)}/extract`);
            handleRun(data.id, "extract", { actionLabel: "Run EXTRACT" });
          },
        },
      );
    },
    [createProject, handleRun, queryClient, clearEvents, onClose, navigate],
  );

  const handleImport = useCallback(
    (urlOrCode: string, name: string, configOverrides?: Partial<ConfigOverrides>) => {
      importStory.mutate(
        { name, urlOrCode, configOverrides },
        {
          onSuccess: (data) => {
            queryClient.removeQueries({ queryKey: ["project", data.id] });
            clearEvents();
            onClose();
            navigate(`/project/${encodeURIComponent(data.id)}/extract`);
            handleRun(data.id, "extract", { actionLabel: "Run EXTRACT" });
          },
        },
      );
    },
    [importStory, handleRun, queryClient, clearEvents, onClose, navigate],
  );

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  // Prevent body scroll
  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-black/80 p-4 pt-[8vh]"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("NEW PRODUCTION")}
    >
      <div
        className="animate-comic-pop w-full max-w-[640px] pb-8"
        onClick={(e) => e.stopPropagation()}
      >
        <UploadStep
          onSubmit={handleCreate}
          onSubmitImport={handleImport}
          isPending={createProject.isPending || importStory.isPending}
          error={createProject.error?.message || importStory.error?.message || null}
          onCancel={onClose}
        />
      </div>
    </div>
  );
}

export function Library() {
  const { t } = useI18n();
  const { data: projects, isLoading, error, refetch } = useProjects();
  const generateCover = useGenerateProjectCover();
  const [pendingCovers, setPendingCovers] = useState<Set<string>>(new Set());
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const coverRevealTimers = useRef<Map<string, number>>(new Map());
  const isEmpty = (projects?.length ?? 0) === 0;

  useEffect(() => {
    if (!projects?.length) return;
    for (const project of projects) {
      if (
        !project.furthest_stage ||
        project.has_cover ||
        project.cover_job?.status === "queued" ||
        project.cover_job?.status === "running" ||
        coverRequestedProjects.has(project.id)
      ) {
        continue;
      }
      coverRequestedProjects.add(project.id);
      window.setTimeout(() => {
        setPendingCovers((current) => new Set(current).add(project.id));
      }, 0);
      generateCover.mutate(
        { project: project.id },
        {
          onSuccess: (data) => {
            if (data.status === "exists") {
              setPendingCovers((current) => {
                const next = new Set(current);
                next.delete(project.id);
                return next;
              });
            }
          },
          onError: () => {
            setPendingCovers((current) => {
              const next = new Set(current);
              next.delete(project.id);
              return next;
            });
          },
        },
      );
    }
  }, [projects, generateCover]);

  useEffect(() => {
    if (!pendingCovers.size) return;
    const timer = window.setInterval(() => {
      refetch().then((result) => {
        const covered = new Set(
          (result.data ?? [])
            .filter((project) => project.has_cover || project.cover_job?.status === "failed")
            .map((project) => project.id),
        );
        if (!covered.size) return;
        for (const name of covered) {
          if (coverRevealTimers.current.has(name)) continue;
          const timer = window.setTimeout(() => {
            setPendingCovers((current) => {
              const next = new Set(current);
              next.delete(name);
              return next;
            });
            coverRevealTimers.current.delete(name);
          }, 700);
          coverRevealTimers.current.set(name, timer);
        }
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pendingCovers, refetch]);

  useEffect(() => () => {
    for (const timer of coverRevealTimers.current.values()) window.clearTimeout(timer);
    coverRevealTimers.current.clear();
  }, []);

  if (isLoading) {
    return <LoadingBlock label={t("WARMING UP THE DRAWING TABLE…")} />;
  }

  if (error) {
    return (
      <StateBlock
        tone="danger"
        icon="alert"
        title={t("THE LIBRARY COULD NOT OPEN")}
        description={error.message}
        action={<Button variant="outline" size="sm" onClick={() => refetch()}>{t("TRY AGAIN")}</Button>}
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1540px] space-y-12 pb-10 md:space-y-14">
      <section className="relative grid overflow-hidden border-[3px] border-ink-black bg-ink-black text-bristol shadow-paper lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="relative z-10 px-6 py-9 sm:px-9 sm:py-11 lg:px-12">
          <div className="inline-flex bg-hero-red px-3 py-1.5 font-meta text-[0.58rem] font-bold tracking-[0.14em] text-bristol uppercase">
            {t("STUDIO // ACTIVE PRODUCTIONS")}
          </div>
          <h1 className="mt-5 max-w-[11ch] font-display text-[3.25rem] font-black uppercase leading-[0.88] tracking-[-0.035em] text-bristol sm:text-[4rem]">
            {t("LIBRARY")}
          </h1>
          <p className="mt-6 max-w-[42rem] font-body text-[1rem] font-semibold leading-7 text-bristol/75">
            {t("Your productions — pick up where you left off, or start a new one.")}
          </p>
          <div className="mt-8">
            <Button variant="onInk" size="lg" onClick={() => setNewProjectOpen(true)}>
              <Icon name="plus" size={16} />
              {t("NEW PRODUCTION")}
            </Button>
          </div>
        </div>

        <div className="relative hidden place-items-center overflow-hidden bg-hero-red px-8 py-9 lg:grid">
          <div aria-hidden="true" className="absolute inset-y-8 left-8 right-0 bg-[radial-gradient(circle_at_1px_1px,rgba(27,28,21,0.2)_1.5px,transparent_1.7px)] [background-size:16px_16px]" />
          <div className="relative w-full -rotate-1 border-[3px] border-ink-black bg-pulp-paper p-5 text-ink-black shadow-[8px_8px_0_0_rgba(27,28,21,0.35)]">
            <div className="flex items-center justify-between border-b-[2px] border-ink-black pb-3 font-meta text-[0.56rem] font-bold tracking-[0.1em]">
              <span>{t("PRESS ROUTE")}</span>
              <span>{String(projects?.length ?? 0).padStart(2, "0")}</span>
            </div>
            <ol className="mt-4 space-y-2">
              {STATIONS.map((station) => (
                <li key={station.key} className="flex items-center gap-3 bg-surface-container px-3 py-2.5">
                  <span className="flex h-7 w-7 items-center justify-center bg-ink-black font-meta text-[0.54rem] font-bold text-bristol">
                    {station.number}
                  </span>
                  <span
                    aria-hidden="true"
                    data-station-label={t(station.label)}
                    className="font-body text-[0.78rem] font-bold before:content-[attr(data-station-label)]"
                  />
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <section className="relative">
        {!isEmpty && (
          <SectionHeader
            variant="underline"
            title={t("ACTIVE PRODUCTIONS")}
            description={t("Pick up at the next decision, with every finished stage kept in place.")}
          />
        )}
        {isEmpty ? (
          <FirstIssueInvitation onStart={() => setNewProjectOpen(true)} />
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-7">
            {projects?.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                coverPending={
                  pendingCovers.has(project.id) ||
                  project.cover_job?.status === "queued" ||
                  project.cover_job?.status === "running"
                }
              />
            ))}
          </div>
        )}
      </section>

      <NewProjectModal isOpen={newProjectOpen} onClose={() => setNewProjectOpen(false)} />
    </div>
  );
}
