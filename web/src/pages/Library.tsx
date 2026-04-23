import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { useGenerateProjectCover, useProjects } from "../api/queries";
import { ProjectCard } from "../components/ProjectCard";
import { SectionLabel } from "../components/SectionLabel";
import { SectionDivider } from "../components/SectionDivider";
import { Card } from "../components/ui/Card";
import { StatRow } from "../components/ui/StatRow";
import { Icon } from "../components/ui/Icon";
import { useI18n } from "../i18n";

const coverRequestedProjects = new Set<string>();

function NewProjectCard() {
  const { t } = useI18n();

  return (
    <Link
      to="/new"
      aria-label={t("START NEW PROJECT")}
      className="group block h-full focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
    >
      <div className="flex h-full min-h-[280px] flex-col items-center justify-center gap-4 border-[2px] border-dashed border-ink-black/30 bg-bristol p-8 transition-colors duration-150 group-hover:border-ink-black/60 group-hover:bg-ghost-shadow/20 group-focus-visible:border-ink-black">
        <div className="flex h-14 w-14 items-center justify-center border-[2px] border-ink-black/25 text-ink-black/35 transition-colors duration-150 group-hover:border-ink-black group-hover:bg-narrator-gold group-hover:text-ink-black">
          <Icon name="plus" size={24} />
        </div>
        <div className="text-center">
          <h3 className="font-display text-[1.1rem] font-bold uppercase leading-none tracking-[-0.03em] text-ink-black">
            {t("NEW PRODUCTION")}
          </h3>
          <p className="mt-1.5 font-body text-[0.78rem] text-ink-black/50">
            {t("Upload a novel to start")}
          </p>
        </div>
      </div>
    </Link>
  );
}

export function Library() {
  const { t } = useI18n();
  const { data: projects, isLoading, error, refetch } = useProjects();
  const generateCover = useGenerateProjectCover();
  const [pendingCovers, setPendingCovers] = useState<Set<string>>(new Set());
  const totalCost = projects?.reduce((sum, p) => sum + p.total_cost_usd, 0) ?? 0;
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
    <div className="space-y-8">
      <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
        <div>
          <SectionLabel tone="red">{t("STUDIO // ACTIVE PRODUCTIONS")}</SectionLabel>
          <h1 className="mt-4 max-w-[10ch] display-impact">{t("LIBRARY")}</h1>
          <p className="mt-5 lead-pulp max-w-[44rem]">
            {t("Your narrative multiverse — active productions, archived issues, and new story seeds waiting to be drawn.")}
          </p>
        </div>

        <Card className="p-4 md:p-5" shadow="lg">
          <div className="mb-4 flex items-center justify-between border-b-[2px] border-ink-black pb-3">
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/45">
                {t("INDEX SIGNALS")}
              </div>
              <div className="mt-1 font-display text-[1.15rem] font-bold uppercase leading-none tracking-[-0.04em]">
                {t("Studio telemetry")}
              </div>
            </div>
            <Icon name="archive" size={18} className="text-hero-red" />
          </div>
          <div className="space-y-3">
            <StatRow label="ARCHIVE FILES">{projects?.length ?? 0}</StatRow>
            <StatRow label="LIVE BOARDS">{runningCount}</StatRow>
            <StatRow label="TOTAL INK USAGE">${totalCost.toFixed(2)}</StatRow>
          </div>
          <p className="mt-3 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/50">
            {t("Ink usage = total AI generation cost")}
          </p>
        </Card>
      </section>

      <section>
        <SectionDivider number={1} label="ACTIVE PRODUCTIONS" />
        <div className="mt-5 grid gap-5 grid-cols-[repeat(auto-fill,minmax(220px,1fr))]">
          <NewProjectCard />

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
    </div>
  );
}
