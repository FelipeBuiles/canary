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
      setPendingCovers((current) => new Set(current).add(project.name));
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
    <div className="space-y-10">
      <section>
        <SectionLabel tone="red">{t("COLLECTION VIEW // ARCHIVE")}</SectionLabel>
        <h1 className="mt-4 max-w-[10ch] display-impact">{t("LIBRARY")}</h1>
        <p className="mt-5 lead-pulp max-w-[44rem]">
          {t("Your narrative multiverse — active productions, archived issues, and new story seeds waiting to be drawn.")}
        </p>
      </section>

      <section>
        <SectionDivider number={1} label="ACTIVE PRODUCTIONS" />
        <div className="mt-5 grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
          <Link to="/new">
            <Card className="flex min-h-[320px] flex-col items-center justify-center border-dashed p-5">
              <div className="flex h-14 w-14 items-center justify-center border-[2px] border-dashed border-ink-black text-ink-black/40">
                <Icon name="plus" size={22} />
              </div>
              <div className="mt-4 font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black/50">
                {t("START NEW PROJECT")}
              </div>
              <p className="mt-2 max-w-[20ch] text-center text-[0.78rem] text-ink-black/40">
                {t("Initialize a new novel-to-comic production pipeline.")}
              </p>
            </Card>
          </Link>

          {projects?.map((project) => (
            <ProjectCard
              key={project.name}
              project={project}
              coverPending={
                pendingCovers.has(project.name) ||
                project.cover_job?.status === "queued" ||
                project.cover_job?.status === "running"
              }
              coverFailed={project.cover_job?.status === "failed"}
            />
          ))}
        </div>
      </section>

      {projects && projects.length > 0 && (
        <section>
          <SectionDivider number={2} label="STUDIO TELEMETRY" />
          <Card className="mt-5 p-5">
            <div className="space-y-3">
              <StatRow label="ARCHIVE FILES">{projects.length}</StatRow>
              <StatRow label="LIVE BOARDS">{runningCount}</StatRow>
              <StatRow label="TOTAL INK USAGE">${totalCost.toFixed(2)}</StatRow>
            </div>
          </Card>
        </section>
      )}
    </div>
  );
}
