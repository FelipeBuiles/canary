import { useNavigate } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateProject, useGenerateProjectCover, useProjects, useImportStory } from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { useRunAction } from "../hooks/useRunAction";
import { ProjectCard } from "../components/ProjectCard";
import { Icon } from "../components/ui/Icon";
import { Button } from "../components/ui/Button";
import { STATIONS } from "../lib/stations";
import { UploadStep } from "../components/wizard/UploadStep";
import type { ConfigOverrides } from "../types/api";
import { useI18n } from "../i18n";

const coverRequestedProjects = new Set<string>();

function NewProjectCard({ onClick }: { onClick: () => void }) {
  const { t } = useI18n();

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t("START NEW PROJECT")}
      className="group block h-full w-full text-left focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
    >
      <div className="flex h-full min-h-[390px] flex-col items-center justify-center gap-6 border-[3px] border-dashed border-ink-black/10 bg-transparent p-6 transition-colors duration-150 group-hover:border-ink-black/35 group-hover:bg-bristol/35 group-focus-visible:border-ink-black">
        <div className="flex h-20 w-20 items-center justify-center border-[3px] border-ink-black/38 text-ink-black/55 transition-[background-color,border-color,color,transform,box-shadow] duration-300 ease-out group-hover:scale-105 group-hover:rotate-90 group-hover:border-ink-black group-hover:bg-narrator-gold group-hover:text-ink-black group-hover:shadow-paper-sm group-focus-visible:border-ink-black">
          <Icon name="plus" size={30} />
        </div>
        <div className="text-center">
          <h3 className="font-display text-[1.42rem] font-black uppercase leading-none tracking-[-0.04em] text-ink-black">
            {t("NEW PRODUCTION")}
          </h3>
          <p className="mt-3 font-body text-[0.96rem] font-semibold text-ink-black/45">
            {t("Upload a novel to start")}
          </p>
        </div>
      </div>
    </button>
  );
}

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
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-black/80 p-4 pt-[8vh] backdrop-blur-[3px]"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("NEW PRODUCTION")}
    >
      <div
        className="w-full max-w-[640px] pb-8"
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
        setPendingCovers((current) => {
          const next = new Set(current);
          for (const name of covered) next.delete(name);
          return next;
        });
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pendingCovers, refetch]);

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
          {t("WARMING UP THE DRAWING TABLE…")}
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-hero-red">
          ERROR: {error.message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-16 md:space-y-20">
      <section>
        <div className="inline-flex bg-hero-red px-4 py-1.5 font-meta text-[0.56rem] tracking-[0.22em] text-bristol uppercase">
          {t("STUDIO // ACTIVE PRODUCTIONS")}
        </div>
        <h1 className="mt-5 max-w-[12ch] display-impact uppercase">
          {t("LIBRARY")}
        </h1>
        <p className="mt-7 max-w-[49rem] lead-pulp text-[1rem] font-semibold md:text-[1.1rem]">
          {t("Your productions — pick up where you left off, or start a new one.")}
        </p>
      </section>

      <section className="relative">
        {isEmpty ? (
          <FirstIssueInvitation onStart={() => setNewProjectOpen(true)} />
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-7">
            <NewProjectCard onClick={() => setNewProjectOpen(true)} />

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
