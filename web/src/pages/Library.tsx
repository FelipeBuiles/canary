import { useLocation, useNavigate } from "react-router-dom";
import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateProject, useDeleteProject, useGenerateProjectCover, useProjects, useImportStory } from "../api/queries";
import { ProjectCard } from "../components/ProjectCard";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { Icon } from "../components/ui/Icon";
import { Button } from "../components/ui/Button";
import { LoadingBlock, StateBlock } from "../components/ui/StateBlock";
import { ConfirmModal, SectionHeader } from "../components/composites";
import { STATIONS } from "../lib/stations";
import { UploadStep } from "../components/wizard/UploadStep";
import type { ConfigOverrides, ProjectSummary } from "../types/api";
import { useI18n } from "../i18n";
import { maybeShowInsufficientCredits } from "../store/insufficientCredits";

function FirstIssueInvitation({ onStart }: { onStart: () => void }) {
  const { t } = useI18n();
  return (
    <section className="grid overflow-hidden border-[3px] border-ink-black bg-bristol shadow-paper lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="px-6 py-8 sm:p-10">
        <h1 className="font-display text-[2.5rem] font-black uppercase leading-[0.95] tracking-[-0.035em] text-ink-black sm:text-[3.25rem]">{t("Your story. Your first issue.")}</h1>
        <p className="mt-5 max-w-[42ch] font-body text-base leading-7 text-ink-muted">{t("Bring a manuscript or choose a sample story. Shape the brief, choose the look, and review your pages before finishing your book.")}</p>
        <Button size="lg" className="mt-7" onClick={onStart}>{t("NEW PRODUCTION")}</Button>
        <p className="mt-3 text-sm text-ink-muted">{t("Prepare your source first. Generation begins only when you choose to start it.")}</p>
        <ol aria-label={t("THE PRODUCTION LINE")} className="mt-8 flex flex-wrap gap-x-5 gap-y-3">
          {STATIONS.map((station) => <li key={station.key} className="flex items-center gap-2 font-body text-sm font-bold"><span className="font-meta text-xs text-ink-muted">{station.number}</span>{t(station.label)}</li>)}
        </ol>
      </div>
      <figure className="bg-pulp-paper p-5 sm:p-8">
        <a href="/marketing/cthulhu-page.webp" target="_blank" rel="noopener noreferrer" aria-label={t("View example comic page at full size")} className="block focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red">
          <img src="/marketing/cthulhu-page.webp" alt={t("Generated comic page from The Call of Cthulhu, with three illustrated and narrated panels")} width={1100} height={1640} className="mx-auto max-h-[640px] w-full object-contain" />
        </a>
        <figcaption className="mt-4 font-body text-sm text-ink-muted"><strong className="text-ink-black">{t("An example generated page")}</strong><br />The Call of Cthulhu · H. P. Lovecraft</figcaption>
      </figure>
    </section>
  );
}

function NewProjectModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const createProject = useCreateProject();
  const importStory = useImportStory();
  const dialogRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();

  const handleCreate = useCallback(
    (file: File, name: string, configOverrides?: Partial<ConfigOverrides>) => {
      createProject.mutate(
        { file, name, configOverrides },
        {
          onSuccess: (data) => {
            queryClient.removeQueries({ queryKey: ["project", data.id] });
            onClose();
            navigate(`/project/${encodeURIComponent(data.id)}/story`);
          },
        },
      );
    },
    [createProject, queryClient, onClose, navigate],
  );

  const handleImport = useCallback(
    (urlOrCode: string, name: string, configOverrides?: Partial<ConfigOverrides>) => {
      importStory.mutate(
        { name, urlOrCode, configOverrides },
        {
          onSuccess: (data) => {
            queryClient.removeQueries({ queryKey: ["project", data.id] });
            onClose();
            navigate(`/project/${encodeURIComponent(data.id)}/story`);
          },
        },
      );
    },
    [importStory, queryClient, onClose, navigate],
  );

  useDialogFocus(dialogRef, { enabled: isOpen, onClose });

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("NEW PRODUCTION")}
        tabIndex={-1}
        className="max-h-[calc(100dvh-2rem)] w-full max-w-[1080px] overflow-y-auto"
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
  const location = useLocation();
  const { t } = useI18n();
  const { data: projects, isLoading, error, refetch } = useProjects();
  const generateCover = useGenerateProjectCover();
  const deleteProject = useDeleteProject();
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [search, setSearch] = useState("");
  const visibleProjects = projects?.filter((project) =>
    `${project.project_name} ${project.author ?? ""}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  );
  const [incompatibleProject, setIncompatibleProject] = useState<ProjectSummary | null>(null);
  const isEmpty = (projects?.length ?? 0) === 0;

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
      {location.state?.projectDeleted && (
        <p role="status" className="bg-narrator-gold p-4 text-sm">
          {t("Project deleted.")} {location.state.projectDeleted}
        </p>
      )}
      {isEmpty ? <FirstIssueInvitation onStart={() => setNewProjectOpen(true)} /> : <section className="relative grid overflow-hidden border-[3px] border-ink-black bg-ink-black text-bristol shadow-paper lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="relative z-10 px-6 py-9 sm:px-9 sm:py-11 lg:px-12">
          <h1 className="max-w-[11ch] font-display text-[3.25rem] font-black uppercase leading-[0.88] tracking-[-0.035em] text-bristol sm:text-[4rem]">
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

        <div className="flex flex-row items-center gap-3 border-t-2 border-bristol/20 px-6 py-5 sm:px-9 lg:flex-col lg:items-start lg:justify-center lg:gap-0 lg:border-l-2 lg:border-t-0 lg:py-7">
          <p className="font-display text-3xl font-black leading-none text-narrator-gold lg:text-6xl">{projects?.length}</p>
          <p className="text-base text-bristol/75 lg:mt-2">{t("Stories in your studio")}</p>
          <p className="mt-5 hidden border-t border-bristol/20 pt-5 text-sm leading-6 text-bristol/75 lg:block">{t("Every story has its own place. Open a production to continue shaping your book.")}</p>
        </div>
      </section>}

      <section className="relative">
        {!isEmpty && (
          <SectionHeader
            variant="underline"
            title={t("ACTIVE PRODUCTIONS")}
            description={t("Pick up at the next decision, with every finished stage kept in place.")}
          />
        )}
        {!isEmpty && (
          <>
          <div className="mb-7 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <label className="block w-full sm:max-w-md">
              <span className="mb-2 block text-sm font-semibold">{t("Find a production")}</span>
              <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search by title or author")}
                className="min-h-12 w-full border-2 border-ink-black/30 bg-bristol px-4 text-base outline-none focus:border-ink-black focus:ring-2 focus:ring-narrator-gold" />
            </label>
            <p role="status" className="text-sm text-ink-muted">{visibleProjects?.length} / {projects?.length} {t("productions")}</p>
          </div>
          {visibleProjects?.length === 0 && <StateBlock title={t("No matching productions")} description={t("Try another title or author.")} action={<Button variant="outline" onClick={() => setSearch("")}>{t("Clear search")}</Button>} />}
          <div className={visibleProjects?.length === 1 ? "max-w-4xl" : "grid grid-cols-[repeat(auto-fill,minmax(min(100%,270px),1fr))] gap-7"}>
            {visibleProjects?.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                expanded={visibleProjects?.length === 1}
                coverPending={
                  (generateCover.isPending && generateCover.variables?.project === project.id) ||
                  project.cover_job?.status === "queued" ||
                  project.cover_job?.status === "running"
                }
                coverFailed={project.cover_job?.status === "failed"}
                coverRetrying={generateCover.isPending && generateCover.variables?.project === project.id}
                onDeleteIncompatible={project.incompatible ? () => setIncompatibleProject(project) : undefined}
                deleteIncompatiblePending={
                  deleteProject.isPending && deleteProject.variables?.id === project.id
                }
                onRetryCover={() => generateCover.mutate(
                  { project: project.id },
                  {
                    onError: (error) => {
                      maybeShowInsufficientCredits(error, { actionLabel: t("Create project cover") });
                    },
                  },
                )}
              />
            ))}
          </div>
          </>
        )}
      </section>

      <NewProjectModal isOpen={newProjectOpen} onClose={() => setNewProjectOpen(false)} />
      <ConfirmModal
        open={incompatibleProject !== null}
        title={t("REMOVE OLD PROJECT")}
        body={t("This project belongs to an older pipeline version and cannot be opened. Deleting it removes its old project data permanently.")}
        confirmInput={incompatibleProject?.project_name}
        confirmLabel={t("REMOVE OLD PROJECT")}
        busy={deleteProject.isPending}
        destructive
        onConfirm={() => {
          if (!incompatibleProject) return;
          deleteProject.mutate(
            { id: incompatibleProject.id },
            { onSuccess: () => setIncompatibleProject(null) },
          );
        }}
        onClose={() => setIncompatibleProject(null)}
      />
    </div>
  );
}
