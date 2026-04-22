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
      <Card className="h-full overflow-hidden transition-transform duration-150 group-hover:-translate-y-[2px] group-focus-visible:-translate-y-[2px]">
        <div className="relative border-b-[2px] border-ink-black bg-bristol">
          <div className="flex aspect-[4/5] flex-col justify-between benday-paper p-4">
            <div className="flex items-center justify-between">
              <div className="border-[2px] border-ink-black bg-hero-red px-2 py-1 font-meta text-[0.48rem] tracking-[0.18em] text-bristol">
                {t("NEW FILE")}
              </div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/45">
                00/07
              </div>
            </div>

            <div className="mx-auto flex h-20 w-20 items-center justify-center border-[2px] border-dashed border-ink-black bg-pulp-paper text-ink-black/50 transition-colors duration-150 group-hover:bg-narrator-gold group-hover:text-ink-black">
              <Icon name="plus" size={28} />
            </div>

            <div>
              <div className="font-meta text-[0.48rem] tracking-[0.18em] text-ink-black/55">
                {t("PROJECT SEED")}
              </div>
              <h3 className="mt-1 max-w-[9ch] font-display text-[2.15rem] font-bold leading-[0.9] tracking-[-0.06em] text-ink-black">
                {t("Start new project")}
              </h3>
            </div>
          </div>
        </div>

        <div className="p-3">
          <div className="grid grid-cols-[1fr_auto] gap-4">
            <p className="text-[0.78rem] leading-6 text-ink-black/72">
              {t("Initialize a new novel-to-comic production pipeline.")}
            </p>
            <div className="text-right">
              <div className="font-display text-[1.8rem] font-bold leading-none tracking-[-0.05em] text-ink-black">
                0
              </div>
              <div className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/45">
                {t("OF")} 7
              </div>
            </div>
          </div>

          <div className="mt-4 h-3 border-[2px] border-ink-black bg-pulp-paper">
            <div className="h-full bg-archive-sage" style={{ width: "0%" }} />
          </div>

          <div className="mt-4 space-y-2 border-t-[2px] border-ink-black pt-3">
            <div className="flex items-center justify-between text-[0.66rem]">
              <span className="font-meta tracking-[0.16em] text-ink-black/45">
                {t("STATUS")}
              </span>
              <span className="font-body text-ink-black/78">{t("READY")}</span>
            </div>
            <div className="flex items-center justify-between text-[0.66rem]">
              <span className="font-meta tracking-[0.16em] text-ink-black/45">
                {t("CHECKPOINT")}
              </span>
              <span className="font-body text-ink-black/78">{t("UPLOAD")}</span>
            </div>
            <div className="flex items-center justify-between text-[0.66rem]">
              <span className="font-meta tracking-[0.16em] text-ink-black/45">
                {t("SPEND")}
              </span>
              <span className="font-body text-ink-black/78 tabular-nums">$0.00</span>
            </div>
          </div>

          <div className="mt-3 flex items-center justify-between border-t border-ink-black/20 pt-3 font-meta text-[0.56rem] tracking-[0.16em] text-hero-red">
            <span>{t("OPEN INTAKE")}</span>
            <span aria-hidden="true">-&gt;</span>
          </div>
        </div>
      </Card>
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

        <Card className="p-4 md:p-5" shadow="sm">
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
              coverFailed={project.cover_job?.status === "failed"}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
