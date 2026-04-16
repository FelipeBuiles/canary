import { useProjects } from "../api/queries";
import { ProjectCard } from "../components/ProjectCard";
import { SectionLabel } from "../components/SectionLabel";
import { Card } from "../components/ui/Card";
import { StatRow } from "../components/ui/StatRow";

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
    <div className="space-y-8">
      <section>
        <SectionLabel>COLLECTION VIEW</SectionLabel>
        <h1 className="mt-4 max-w-[10ch] font-display text-[3.5rem] font-bold leading-[0.86] tracking-[-0.08em] text-ink-black md:text-[6rem]">
          LIBRARY
        </h1>
        <p className="mt-4 max-w-[38rem] border-l-[4px] border-hero-red pl-4 text-[0.95rem] leading-7 text-ink-black/74">
          Your narrative multiverse — active productions, archived issues, and
          new story seeds waiting to be drawn.
        </p>
      </section>

      <section>
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {/* Start new project card */}
          <Card className="flex min-h-[320px] flex-col items-center justify-center border-dashed p-5">
            <div className="flex h-14 w-14 items-center justify-center border-[2px] border-dashed border-ink-black text-[1.5rem] text-ink-black/30">
              +
            </div>
            <div className="mt-4 font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black/40">
              START NEW PROJECT
            </div>
            <p className="mt-2 max-w-[20ch] text-center text-[0.78rem] text-ink-black/35">
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
          <Card className="p-4 md:p-5">
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
