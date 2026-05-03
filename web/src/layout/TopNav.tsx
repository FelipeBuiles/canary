import { Link, useParams, useLocation } from "react-router-dom";
import { useRunAction } from "../hooks/useRunAction";
import { UI_STAGES } from "../lib/uiStages";
import { Button } from "../components/ui/Button";
import { useI18n } from "../i18n";

function ProfileIcon({ to }: { to: string }) {
  return (
    <Link
      to={to}
      aria-label="Settings"
      className="flex h-8 w-8 items-center justify-center rounded-full border-[2px] border-ink-black hover:bg-pulp-paper"
    >
      <span className="block h-2.5 w-2.5 rounded-full border border-ink-black" />
    </Link>
  );
}

export function TopNav() {
  const { id } = useParams();
  const location = useLocation();
  const { handleRun, isPending } = useRunAction();
  const { t } = useI18n();

  const currentRoom = location.pathname.split("/").pop() ?? "";
  const settingsPath = id ? `/project/${encodeURIComponent(id)}/settings` : "/settings";

  return (
    <header className="shrink-0 border-b-[2px] border-ink-black bg-pulp-paper">
      <div className="flex min-h-[70px] items-center justify-between gap-5 px-4 lg:px-5">
        <Link to="/" className="font-display text-[1.1rem] font-bold tracking-[-0.06em] lg:text-[1.35rem]">
          {t("THE NARRATIVE FRAME")}
        </Link>

        <nav className="hidden flex-1 items-end justify-center gap-5 xl:flex">
          {UI_STAGES.map((stage) => {
            const isActive = stage.route === currentRoom;
            const route = stage.route;
            const to = id ? `/project/${encodeURIComponent(id)}/${route}` : "/";

            return id ? (
              <Link
                key={stage.key}
                to={to}
                className={`border-b-[3px] pb-1 font-display text-[0.8rem] tracking-[-0.03em] ${
                  isActive
                    ? "border-hero-red text-hero-red"
                    : "border-transparent text-ink-black/45 hover:text-ink-black/70"
                }`}
              >
                {stage.label.toUpperCase()}
              </Link>
            ) : (
              <span
                key={stage.key}
                className="border-b-[3px] pb-1 font-display text-[0.8rem] tracking-[-0.03em] border-transparent text-ink-black/45"
              >
                {stage.label.toUpperCase()}
              </span>
            );
          })}
        </nav>

        <div className="flex items-center gap-4">
          <Button
            onClick={() => id && handleRun(id)}
            disabled={!id || isPending}
            size="lg"
            className="px-7"
          >
            {isPending ? t("RUNNING…") : t("RENDER")}
          </Button>
          <ProfileIcon to={settingsPath} />
        </div>
      </div>
    </header>
  );
}
