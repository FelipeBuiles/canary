import { useProjects } from "../api/queries";
import { ProjectCard } from "../components/ProjectCard";
import { SectionLabel } from "../components/SectionLabel";
import { SectionDivider } from "../components/SectionDivider";
import { Card } from "../components/ui/Card";
import { StatRow } from "../components/ui/StatRow";
import { Icon } from "../components/ui/Icon";

export function Library() {
  const { data: projects, isLoading, error } = useProjects();
  const totalCost = projects?.reduce((sum, p) => sum + p.total_cost_usd, 0) ?? 0;
  const runningCount = projects?.filter((p) => p.is_running).length ?? 0;

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
          BUILDING STUDIO INDEX...
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
        <SectionLabel tone="red">COLLECTION VIEW // ARCHIVE</SectionLabel>
        <h1 className="mt-4 max-w-[10ch] display-impact">LIBRARY</h1>
        <p className="mt-5 lead-pulp max-w-[44rem]">
          Your narrative multiverse — active productions, archived issues, and
          new story seeds waiting to be drawn.
        </p>
      </section>

      <section>
        <SectionDivider number={1} label="ACTIVE PRODUCTIONS" />
        <div className="mt-5 grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
          <Card className="flex min-h-[320px] flex-col items-center justify-center border-dashed p-5">
            <div className="flex h-14 w-14 items-center justify-center border-[2px] border-dashed border-ink-black text-ink-black/40">
              <Icon name="plus" size={22} />
            </div>
            <div className="mt-4 font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black/50">
              START NEW PROJECT
            </div>
            <p className="mt-2 max-w-[20ch] text-center text-[0.78rem] text-ink-black/40">
              Initialize a new novel-to-comic production pipeline.
            </p>
          </Card>

          {projects?.map((project) => (
            <ProjectCard key={project.name} project={project} />
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
