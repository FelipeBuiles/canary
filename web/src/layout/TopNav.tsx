import { Link, useParams, useLocation } from "react-router-dom";
import { useRunAction } from "../hooks/useRunAction";
import { STAGE_ORDER, STAGE_ROUTES } from "../types/api";
import { Button } from "../components/ui/Button";
import { LANGUAGES, useI18n } from "../i18n";

function ProfileIcon() {
  return (
    <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-full border-[2px] border-ink-black">
      <span className="block h-2.5 w-2.5 rounded-full border border-ink-black" />
    </span>
  );
}

export function TopNav() {
  const { name } = useParams();
  const location = useLocation();
  const { handleRun, isPending } = useRunAction();
  const { language, setLanguage, stageName, t } = useI18n();

  const currentRoom = location.pathname.split("/").pop() ?? "";
  const activeRouteStage = Object.entries(STAGE_ROUTES).find(
    ([, route]) => route === currentRoom,
  )?.[0];

  return (
    <header className="shrink-0 border-b-[2px] border-ink-black bg-pulp-paper">
      <div className="flex min-h-[70px] items-center justify-between gap-5 px-4 lg:px-5">
        <Link to="/" className="font-display text-[1.1rem] font-bold tracking-[-0.06em] lg:text-[1.35rem]">
          {t("THE NARRATIVE FRAME")}
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
                {stageName(stage)}
              </Link>
            ) : (
              <span
                key={stage}
                className="border-b-[3px] pb-1 font-display text-[0.8rem] tracking-[-0.03em] border-transparent text-ink-black/45"
              >
                {stageName(stage)}
              </span>
            );
          })}
        </nav>

        <div className="flex items-center gap-4">
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as typeof language)}
            className="hidden border-[2px] border-ink-black bg-bristol px-2 py-1.5 font-meta text-[0.62rem] tracking-[0.1em] md:block"
            aria-label="Language"
          >
            {LANGUAGES.map((item) => (
              <option key={item.code} value={item.code}>{item.label}</option>
            ))}
          </select>
          <Button
            onClick={() => name && handleRun(name)}
            disabled={!name || isPending}
            size="lg"
            className="px-7"
          >
            {isPending ? t("RUNNING…") : t("RENDER")}
          </Button>
          <ProfileIcon />
        </div>
      </div>
    </header>
  );
}
