import { useNavigate } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateProject, useGenerateProjectCover, useProjects, useRunPipeline } from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { ProjectCard } from "../components/ProjectCard";
import { StatRow } from "../components/ui/StatRow";
import { Icon } from "../components/ui/Icon";
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
        <div className="flex h-20 w-20 items-center justify-center border-[3px] border-ink-black/38 text-ink-black/55 transition-colors duration-150 group-hover:border-ink-black group-hover:bg-narrator-gold group-hover:text-ink-black">
          <Icon name="plus" size={30} />
        </div>
        <div className="text-center">
          <h3 className="font-display text-[1.42rem] font-black uppercase leading-none tracking-[-0.055em] text-ink-black">
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

function NewProjectModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const createProject = useCreateProject();
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);
  const { t } = useI18n();

  const handleCreate = useCallback(
    (file: File, name: string, configOverrides?: Partial<ConfigOverrides>) => {
      createProject.mutate(
        { file, name, configOverrides },
        {
          onSuccess: (data) => {
            queryClient.removeQueries({ queryKey: ["project", data.name] });
            clearEvents();
            // Start the pipeline, then navigate to the first stage room
            runPipeline.mutate(
              { project: data.name },
              {
                onSuccess: () => {
                  connect(data.name);
                  onClose();
                  navigate(`/project/${encodeURIComponent(data.name)}/extract`);
                },
              },
            );
          },
        },
      );
    },
    [createProject, runPipeline, queryClient, clearEvents, connect, onClose, navigate],
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
          isPending={createProject.isPending}
          error={null}
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
  const runningCount = projects?.filter((p) => p.is_running).length ?? 0;

  useEffect(() => {
    if (!projects?.length) return;
    for (const project of projects) {
      if (
        !project.furthest_stage ||
        project.has_cover ||
        project.cover_job?.status === "queued" ||
        project.cover_job?.status === "running" ||
        coverRequestedProjects.has(project.name)
      ) {
        continue;
      }
      coverRequestedProjects.add(project.name);
      window.setTimeout(() => {
        setPendingCovers((current) => new Set(current).add(project.name));
      }, 0);
      generateCover.mutate(
        { project: project.name },
        {
          onSuccess: (data) => {
            if (data.status === "exists") {
              setPendingCovers((current) => {
                const next = new Set(current);
                next.delete(project.name);
                return next;
              });
            }
          },
          onError: () => {
            setPendingCovers((current) => {
              const next = new Set(current);
              next.delete(project.name);
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
            .map((project) => project.name),
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
          {t("BUILDING STUDIO INDEX…")}
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
    <div className="space-y-20">
      <section className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_330px] lg:items-start">
        <div>
          <div className="inline-flex bg-hero-red px-4 py-1.5 font-meta text-[0.56rem] tracking-[0.22em] text-bristol uppercase">
            {t("STUDIO // ACTIVE PRODUCTIONS")}
          </div>
          <h1 className="mt-5 max-w-[10ch] font-display text-[clamp(5.25rem,11vw,9rem)] font-black uppercase leading-[0.78] tracking-[-0.065em] text-ink-black">
            {t("LIBRARY")}
          </h1>
          <p className="mt-9 max-w-[49rem] border-l-[4px] border-hero-red pl-8 text-[1.28rem] font-semibold leading-10 text-ink-black/68">
            {t("Your narrative multiverse — active productions, archived issues, and new story seeds waiting to be drawn.")}
          </p>
        </div>

        <aside className="border-[3px] border-ink-black bg-bristol px-7 py-7">
          <div className="mb-5 flex items-center justify-between border-b border-panel-line pb-5">
            <div>
              <div className="font-meta text-[0.7rem] tracking-[0.24em] text-ink-black/45">
                {t("INDEX SIGNALS")}
              </div>
              <div className="mt-1 font-display text-[1.35rem] font-black uppercase leading-none tracking-[-0.04em]">
                {t("Studio telemetry")}
              </div>
            </div>
            <Icon name="sparkles" size={18} className="text-narrator-gold" />
          </div>
          <div className="space-y-3">
            <StatRow label="ARCHIVE FILES">{projects?.length ?? 0}</StatRow>
            <StatRow label="LIVE BOARDS">{runningCount}</StatRow>
            <StatRow label="CREDITED RUNS">{projects?.filter((p) => p.total_cost_usd > 0).length ?? 0}</StatRow>
          </div>
          <p className="mt-3 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/50">
            {t("Ink usage = total AI generation cost")}
          </p>
        </aside>
      </section>

      <section>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-7">
          <NewProjectCard onClick={() => setNewProjectOpen(true)} />

          {projects?.map((project) => (
            <ProjectCard
              key={project.name}
              project={project}
              coverPending={
                pendingCovers.has(project.name) ||
                project.cover_job?.status === "queued" ||
                project.cover_job?.status === "running"
              }
            />
          ))}
        </div>
      </section>

      <NewProjectModal isOpen={newProjectOpen} onClose={() => setNewProjectOpen(false)} />
    </div>
  );
}
