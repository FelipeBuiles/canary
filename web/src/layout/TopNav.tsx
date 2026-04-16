import { Link, useParams, useLocation } from "react-router-dom";
import { useRunPipeline } from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { STAGE_DISPLAY_NAMES, STAGE_ORDER, STAGE_ROUTES } from "../types/api";
import { Button } from "../components/ui/Button";

function ProfileIcon() {
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-full border-[2px] border-ink-black">
      <span className="block h-2.5 w-2.5 rounded-full border border-ink-black" />
    </span>
  );
}

export function TopNav() {
  const { name } = useParams();
  const location = useLocation();
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);

  const currentRoom = location.pathname.split("/").pop() ?? "";
  const activeRouteStage = Object.entries(STAGE_ROUTES).find(
    ([, route]) => route === currentRoom,
  )?.[0];

  const handleRun = () => {
    if (!name) return;
    clearEvents();
    runPipeline.mutate(
      { project: name },
      { onSuccess: () => connect(name) },
    );
  };

  return (
    <header className="shrink-0 border-b-[2px] border-ink-black bg-pulp-paper">
      <div className="flex min-h-[70px] items-center justify-between gap-5 px-4 lg:px-5">
        <Link to="/" className="font-display text-[1.1rem] font-bold tracking-[-0.06em] lg:text-[1.35rem]">
          THE NARRATIVE FRAME
        </Link>

        <nav className="hidden flex-1 items-end justify-center gap-5 xl:flex">
          {STAGE_ORDER.map((stage) => {
            const isActive = stage === activeRouteStage;
            const route = STAGE_ROUTES[stage];
            const to = name ? `/project/${encodeURIComponent(name)}/${route}` : "/";

            return name ? (
              <Link
                key={stage}
                to={to}
                className={`border-b-[3px] pb-1 font-display text-[0.8rem] tracking-[-0.03em] ${
                  isActive
                    ? "border-hero-red text-hero-red"
                    : "border-transparent text-ink-black/45 hover:text-ink-black/70"
                }`}
              >
                {STAGE_DISPLAY_NAMES[stage]}
              </Link>
            ) : (
              <span
                key={stage}
                className="border-b-[3px] pb-1 font-display text-[0.8rem] tracking-[-0.03em] border-transparent text-ink-black/45"
              >
                {STAGE_DISPLAY_NAMES[stage]}
              </span>
            );
          })}
        </nav>

        <div className="flex items-center gap-4">
          <Button
            onClick={handleRun}
            disabled={!name || runPipeline.isPending}
            size="lg"
            className="px-7"
          >
            {runPipeline.isPending ? "RUNNING" : "RENDER"}
          </Button>
          <ProfileIcon />
        </div>
      </div>
    </header>
  );
}
