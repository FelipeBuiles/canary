import { useLocation, useNavigate } from "react-router-dom";
import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateProject, useDeleteProject, useGenerateProjectCover, useProjects, useImportStory } from "../api/queries";
import { ProjectCard } from "../components/ProjectCard";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { useBackdropDismiss } from "../hooks/useBackdropDismiss";
import { Icon } from "../components/ui/Icon";
import { Button } from "../components/ui/Button";
import { LoadingBlock, StateBlock } from "../components/ui/StateBlock";
import { ConfirmModal } from "../components/composites";
import { STATIONS } from "../lib/stations";
import { UploadStep } from "../components/wizard/UploadStep";
import { clearManuscriptDraft } from "../lib/manuscriptDraft";
import type { ConfigOverrides, ProjectSummary } from "../types/api";
import { useI18n } from "../i18n";
import { maybeShowInsufficientCredits } from "../store/insufficientCredits";
import { partProjectKey, splitProjectKey } from "../api/projectScope";

function FirstIssueInvitation({ onStart }: { onStart: () => void }) {
  const { t } = useI18n();
  return (
    <section className="grid overflow-hidden border-[3px] border-ink-black bg-bristol shadow-paper lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="px-6 py-8 sm:p-10">
        <h1 className="font-display text-[2.5rem] font-black uppercase leading-[0.95] tracking-[-0.035em] text-ink-black sm:text-[3.25rem]">{t("Your story. Your first issue.")}</h1>
        <p className="mt-5 font-body text-base leading-7 text-ink-muted">{t("Bring a manuscript or choose a sample story. Shape the brief, choose the look, and review your pages before finishing your book.")}</p>
        <Button size="lg" className="mt-7" onClick={onStart}>{t("New production")}</Button>
        <p className="mt-3 text-sm text-ink-muted">{t("Prepare your source first. Generation begins only when you choose to start it.")}</p>
        <ol aria-label={t("THE PRODUCTION LINE")} className="mt-8 flex flex-wrap gap-x-5 gap-y-3">
          {STATIONS.map((station) => <li key={station.key} className="flex items-center gap-2 font-body text-sm font-bold"><span className="font-meta text-xs text-ink-muted">{station.number}</span>{t(station.label)}</li>)}
        </ol>
      </div>
      <figure className="bg-pulp-paper p-5 sm:p-8">
        <a href="/marketing/elm-and-keep-page-12.webp" target="_blank" rel="noopener noreferrer" aria-label={t("View example comic page at full size")} className="block focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red">
          <img src="/marketing/elm-and-keep-page-12.webp" alt={t("Generated comic page from Elm and Keep, showing a goblin examining a coin in two illustrated panels")} width={1024} height={1536} className="mx-auto max-h-[640px] w-full object-contain" />
        </a>
        <figcaption className="mt-4 font-body text-sm text-ink-muted"><strong className="text-ink-black">{t("An example generated page")}</strong><br />Elm and Keep · @strnglft (CC0)</figcaption>
      </figure>
    </section>
  );
}

function NewProjectModal({ isOpen, onClose, initialStoryCode }: { isOpen: boolean; onClose: () => void; initialStoryCode?: string | null }) {
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
            clearManuscriptDraft();
            onClose();
            navigate(`/project/${encodeURIComponent(partProjectKey(data.id, data.part_id))}/story`);
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
  const backdrop = useBackdropDismiss(onClose);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex bg-pulp-paper"
      {...backdrop}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("New production")}
        tabIndex={-1}
        className="h-dvh w-full focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <UploadStep
          onSubmit={handleCreate}
          onSubmitImport={handleImport}
          isPending={createProject.isPending || importStory.isPending}
          error={createProject.error || importStory.error || null}
          onCancel={onClose}
          initialStoryCode={initialStoryCode}
        />
      </div>
    </div>
  );
}

const coverProject = (key: string | undefined) => (key ? splitProjectKey(key).id : undefined);

export function Library() {
  const location = useLocation();
  const navigate = useNavigate();
  const requestedSample = new URLSearchParams(location.search).get("sample");
  const { t } = useI18n();
  const { data: projects, isLoading, error, refetch } = useProjects();
  const generateCover = useGenerateProjectCover();
  const deleteProject = useDeleteProject();
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const modalOpen = newProjectOpen || Boolean(requestedSample);

  function closeNewProject() {
    setNewProjectOpen(false);
    if (requestedSample) {
      const params = new URLSearchParams(location.search);
      params.delete("sample");
      navigate({ pathname: location.pathname, search: params.toString() }, { replace: true });
    }
  }
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
      <div className="mx-auto flex min-h-[40vh] max-w-lg items-center px-4">
        <ErrorNotice error={error} operation="load" title="Projects could not be loaded." onRetry={() => void refetch()} />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1540px] space-y-6 pb-10">
      {location.state?.projectDeleted && (
        <p role="status" className="bg-narrator-gold p-4 text-sm">
          {t("Project deleted.")} {location.state.projectDeleted}
        </p>
      )}
      {isEmpty ? <FirstIssueInvitation onStart={() => setNewProjectOpen(true)} /> : (
        <section aria-labelledby="library-title" className="space-y-6">
          {/* One header row: the room's name, its count, search and the one primary. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <h1 id="library-title" className="font-display text-[1.75rem] font-black uppercase leading-[0.95] tracking-[-0.03em] text-ink-black studio-desktop:text-[1.625rem]">
              {t("Library")}
            </h1>
            <p role="status" className="font-meta text-xs text-ink-soft">
              {search.trim()
                ? `${visibleProjects?.length} / ${projects?.length} ${t("productions")}`
                : t("{count, plural, one {# production} other {# productions}}", { count: projects?.length ?? 0 })}
            </p>
            <div className="ml-auto flex w-full flex-wrap items-center gap-2 sm:w-auto">
              <label className="relative min-w-0 flex-1 sm:w-72 sm:flex-none">
                <span className="sr-only">{t("Find a production")}</span>
                <Icon name="search" size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-soft" />
                <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search by title or author")}
                  className="h-10 w-full border border-ink-black/55 bg-bristol pl-9 pr-3 font-body text-sm outline-none placeholder:text-ink-soft focus:border-transparent focus:outline-2 focus:outline-offset-[-1px] focus:outline-hero-red" />
              </label>
              <Button onClick={() => setNewProjectOpen(true)}>
                <Icon name="plus" size={15} />
                {t("New production")}
              </Button>
            </div>
          </div>
          {visibleProjects?.length === 0 && <StateBlock title={t("No matching productions")} description={t("Try another title or author.")} action={<Button variant="outline" onClick={() => setSearch("")}>{t("Clear search")}</Button>} />}
          <div className={visibleProjects?.length === 1 ? "max-w-4xl" : "grid grid-cols-[repeat(auto-fill,minmax(min(100%,220px),1fr))] gap-x-5 gap-y-7"}>
            {visibleProjects?.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                expanded={visibleProjects?.length === 1}
                coverPending={
                  (generateCover.isPending && coverProject(generateCover.variables?.project) === project.id) ||
                  project.cover_job?.status === "queued" ||
                  project.cover_job?.status === "running"
                }
                coverFailed={project.cover_job?.status === "failed"}
                coverRetrying={generateCover.isPending && coverProject(generateCover.variables?.project) === project.id}
                onDeleteIncompatible={project.incompatible ? () => setIncompatibleProject(project) : undefined}
                deleteIncompatiblePending={
                  deleteProject.isPending && deleteProject.variables?.id === project.id
                }
                onRetryCover={() => generateCover.mutate(
                  // Covers belong to a part; the card shows the first part's.
                  { project: partProjectKey(project.id, project.cover_part_id) },
                  {
                    onError: (error) => {
                      maybeShowInsufficientCredits(error, { actionLabel: t("Create project cover") });
                    },
                  },
                )}
              />
            ))}
          </div>
        </section>
      )}

      <NewProjectModal isOpen={modalOpen} onClose={closeNewProject} initialStoryCode={requestedSample} />
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
import { ErrorNotice } from "../components/composites/ErrorNotice";
