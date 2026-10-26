import { Link, useLocation, useNavigate } from "react-router-dom";
import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateProject, useDeleteProject, useGenerateProjectCover, useProjects, useImportStory } from "../api/queries";
import { ProjectCard } from "../components/ProjectCard";
import { projectCoverColor, projectShelfState, projectStation, type ProjectShelfState } from "../lib/projectShelf";
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
import { partProjectKey, projectFileUrl, splitProjectKey } from "../api/projectScope";

function FirstIssueInvitation({ onStart }: { onStart: () => void }) {
  const { t } = useI18n();
  return (
    <section className="benday-ink grid items-center gap-10 overflow-hidden px-6 py-10 text-pulp-paper sm:px-12 sm:py-14 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div className="max-w-xl">
        <span className="inline-flex h-[26px] items-center bg-narrator-gold px-2.5 font-meta text-[0.6875rem] font-bold uppercase tracking-[0.1em] text-ink-black">{t("Your library")}</span>
        <h1 className="mt-4 font-display text-[2.75rem] font-black uppercase leading-[0.86] tracking-[-0.035em] sm:text-[4rem]">{t("Your first comic starts here")}</h1>
        <p className="mt-5 font-body text-[1.0625rem] leading-7 text-pulp-paper/75">{t("Bring a chapter, a short story or a whole book.")}</p>
        <div className="mt-7 flex flex-wrap items-center gap-5">
          <Button size="lg" className="border-pulp-paper shadow-[3px_3px_0_var(--color-pulp-paper)]" onClick={onStart}>
            <Icon name="plus" size={15} />
            {t("New production")}
          </Button>
          <Link to="/samples" className="font-meta text-sm font-medium text-pulp-paper underline underline-offset-4 hover:text-narrator-gold">{t("or try a sample story")}</Link>
        </div>
      </div>
      <figure className="mx-auto w-full max-w-[22rem] lg:rotate-[2deg]">
        <a href="/marketing/elm-and-keep-page-12.webp" target="_blank" rel="noopener noreferrer" aria-label={t("View example comic page at full size")} className="block shadow-[7px_7px_0_var(--color-narrator-gold)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red">
          <img src="/marketing/elm-and-keep-page-12.webp" alt={t("Generated comic page from Elm and Keep, showing a goblin examining a coin in two illustrated panels")} width={1024} height={1536} className="block w-full" />
        </a>
        <figcaption className="mt-4 font-meta text-xs text-pulp-paper/60">{t("An example generated page")} · Elm and Keep · @strnglft (CC0)</figcaption>
      </figure>
    </section>
  );
}

/** The production waiting on the user, raised off the shelf onto the desk. */
function DeskPanel({ project }: { project: ProjectSummary }) {
  const { t } = useI18n();
  const station = projectStation(project);
  const current = station ? STATIONS.indexOf(station) : 0;
  const href = `/project/${encodeURIComponent(project.id)}`;
  return (
    <section aria-labelledby="desk-title" className="benday-ink grid items-center gap-8 overflow-hidden px-6 py-8 text-pulp-paper sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-11 sm:px-10 sm:py-9 lg:grid-cols-[14.25rem_minmax(0,1fr)]">
      <Link to={href} tabIndex={-1} aria-hidden="true" className="hidden aspect-[3/4] overflow-hidden bg-ink-black shadow-[7px_7px_0_var(--color-narrator-gold)] sm:block">
        {project.has_cover ? (
          <img src={projectFileUrl(partProjectKey(project.id, project.cover_part_id), "cover/cover.png")} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="benday-ink flex h-full items-end p-4 font-display text-[1.75rem] font-black uppercase leading-[0.9] tracking-[-0.03em]" style={{ backgroundColor: projectCoverColor(project) }}>{project.project_name}</div>
        )}
      </Link>
      <div className="flex min-w-0 flex-col gap-6">
        <div>
          <span className="inline-flex h-[26px] items-center gap-2 bg-narrator-gold px-2.5 font-meta text-[0.6875rem] font-bold uppercase tracking-[0.1em] text-ink-black">
            <span aria-hidden="true" className="inline-block h-[7px] w-[7px] bg-ink-black" />
            {t("Waiting on you")}
          </span>
          <h2 id="desk-title" className="mt-3.5 break-words font-display text-[2.5rem] font-black uppercase leading-[0.88] tracking-[-0.035em] lg:text-[3.75rem]">{project.project_name}</h2>
          {project.author && <p className="mt-2.5 font-body text-base text-pulp-paper/70">{project.author}</p>}
        </div>
        <ol aria-label={t("Progress")} className="flex max-w-[40rem] flex-wrap items-center gap-x-3.5 gap-y-2">
          {STATIONS.map((item, index) => {
            const done = index < current;
            const now = index === current;
            return (
              <li key={item.key} aria-current={now ? "step" : undefined} className="contents">
                {index > 0 && <span aria-hidden="true" className="hidden h-px min-w-5 flex-1 bg-pulp-paper/20 sm:block" />}
                <span className={`flex items-center gap-2.5 font-display text-sm font-black uppercase tracking-[-0.01em] ${done || now ? "text-pulp-paper" : "text-pulp-paper/55"}`}>
                  <span className={`inline-flex h-[26px] w-[26px] items-center justify-center border font-meta text-[0.6875rem] font-semibold tracking-normal ${done ? "border-ready bg-ready text-pulp-paper" : now ? "border-narrator-gold bg-narrator-gold text-ink-black" : "border-pulp-paper/35 text-pulp-paper/75"}`}>
                    {done ? <Icon name="check" size={13} /> : item.number}
                  </span>
                  {t(item.label)}
                </span>
              </li>
            );
          })}
        </ol>
        <div>
          <Link to={href} className="inline-flex h-10 items-center gap-2 border-2 border-pulp-paper bg-hero-red px-4 font-meta text-sm font-semibold text-bristol shadow-[3px_3px_0_var(--color-pulp-paper)] transition-[translate,box-shadow,background-color] hover:-translate-x-px hover:-translate-y-px hover:bg-hero-red-press hover:shadow-[4px_4px_0_var(--color-pulp-paper)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold">
            {station ? t("Continue in {station}", { station: t(station.label) }) : t("Continue")}
            <Icon name="arrow-right" size={15} />
          </Link>
        </div>
      </div>
    </section>
  );
}

type ShelfFilter = "all" | ProjectShelfState;

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
  const [filter, setFilter] = useState<ShelfFilter>("all");
  // Newest first; the list endpoint carries no last-activity time yet.
  const sorted = [...(projects ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const counts: Record<ProjectShelfState, number> = { needs: 0, working: 0, done: 0, reset: 0 };
  for (const project of sorted) counts[projectShelfState(project)] += 1;
  const visibleProjects = sorted.filter((project) =>
    (filter === "all" || projectShelfState(project) === filter) &&
    `${project.project_name} ${project.author ?? ""}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  );
  const groups = filter === "all"
    ? [
        { key: "active", title: t("In progress"), items: visibleProjects.filter((project) => projectShelfState(project) !== "done") },
        { key: "done", title: t("Finished"), items: visibleProjects.filter((project) => projectShelfState(project) === "done") },
      ].filter((group) => group.items.length > 0)
    : [{ key: filter, title: "", items: visibleProjects }];
  // The desk raises one production that waits on the user, once there is a shelf to raise it from.
  const desk = sorted.length > 1 && !search.trim() && filter === "all"
    ? sorted.find((project) => projectShelfState(project) === "needs" && project.furthest_stage)
    : undefined;
  const filters: { key: ShelfFilter; label: string; count: number }[] = [
    { key: "all", label: t("All"), count: sorted.length },
    { key: "needs", label: t("Needs you"), count: counts.needs },
    { key: "working", label: t("Working"), count: counts.working },
    { key: "done", label: t("Finished"), count: counts.done },
    { key: "reset", label: t("Needs reset"), count: counts.reset },
  ];
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
    <div className="mx-auto w-full max-w-[1440px] space-y-6 pb-16">
      {location.state?.projectDeleted && (
        <p role="status" className="bg-narrator-gold p-4 text-sm">
          {t("Project deleted.")} {location.state.projectDeleted}
        </p>
      )}
      {isEmpty ? <FirstIssueInvitation onStart={() => setNewProjectOpen(true)} /> : (
        <section aria-labelledby="library-title" className="space-y-7">
          {/* One header row: the room's name, search and the one primary. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <h1 id="library-title" className="font-display text-[2.125rem] font-black uppercase leading-[0.9] tracking-[-0.03em] text-ink-black">
              {t("Library")}
            </h1>
            <p role="status" className={search.trim() ? "font-meta text-xs text-ink-soft" : "sr-only"}>
              {search.trim()
                ? `${visibleProjects.length} / ${sorted.length} ${t("productions")}`
                : t("{count, plural, one {# production} other {# productions}}", { count: sorted.length })}
            </p>
            <div className="ml-auto flex w-full flex-wrap items-center gap-2.5 sm:w-auto">
              <label className="relative min-w-0 flex-1 sm:w-72 sm:flex-none">
                <span className="sr-only">{t("Find a production")}</span>
                <Icon name="search" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-soft" />
                <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search titles and authors")}
                  className="h-10 w-full border border-ink-black/45 bg-bristol pl-9 pr-3 font-body text-sm outline-none placeholder:text-ink-soft focus:border-transparent focus:outline-2 focus:outline-offset-[-1px] focus:outline-hero-red" />
              </label>
              <Button onClick={() => setNewProjectOpen(true)}>
                <Icon name="plus" size={15} />
                {t("New production")}
              </Button>
            </div>
          </div>

          {desk && <DeskPanel project={desk} />}

          {sorted.length > 1 && (
            <div role="group" aria-label={t("Show")} className="inline-flex flex-wrap border border-ink-black/55 bg-bristol">
              {filters.filter((item) => item.key === "all" || item.count > 0).map((item) => (
                <button key={item.key} type="button" aria-pressed={filter === item.key} onClick={() => setFilter(item.key)}
                  className={`inline-flex h-9 items-center gap-2 px-3.5 font-meta text-[0.8125rem] font-medium transition-colors [&+&]:border-l [&+&]:border-ink-black/18 ${filter === item.key ? "bg-ink-black text-pulp-paper" : "text-ink-muted hover:bg-sidebar-tint hover:text-ink-black"}`}>
                  {item.label}
                  <span className="text-xs opacity-70">{item.count}</span>
                </button>
              ))}
            </div>
          )}

          {visibleProjects.length === 0 && <StateBlock title={t("No matching productions")} description={t("Try another title or author.")} action={<Button variant="outline" onClick={() => { setSearch(""); setFilter("all"); }}>{t("Clear search")}</Button>} />}
          <div className="space-y-14">
            {groups.map((group) => (
              <section key={group.key} aria-label={group.title || undefined}>
                {group.title && groups.length > 1 && (
                  <div className="relative mb-6 flex items-baseline gap-3 border-b border-ink-black/15 pb-3 after:absolute after:-bottom-px after:left-0 after:h-0.5 after:w-8 after:bg-hero-red">
                    <h2 className="font-display text-xl font-black uppercase tracking-[-0.02em] text-ink-black">{group.title}</h2>
                    <span className="font-meta text-[0.8125rem] text-ink-soft">{group.items.length}</span>
                  </div>
                )}
                <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,11.75rem),1fr))] gap-x-7 gap-y-9">
                  {group.items.map((project) => (
                    <ProjectCard
                      key={project.id}
                      project={project}
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
