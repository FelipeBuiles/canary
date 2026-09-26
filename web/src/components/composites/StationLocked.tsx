import { ArrowRight, Check, LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import { getRoomAccess, type RoomAccess } from "../../lib/stationAccess";
import { STATIONS, stationForRoute, type Station } from "../../lib/stations";
import type { ProjectStatus } from "../../types/api";
import { EntityCard } from "./EntityCard";

export function StationLocked({ project, station, access, status }: {
  project: string;
  station: Station;
  access: Extract<RoomAccess, { state: "locked" }>;
  status: ProjectStatus;
}) {
  const { t } = useI18n();
  const nextStation = stationForRoute(access.route)!;
  return (
    <section className="mx-auto flex min-h-[60vh] max-w-3xl items-center py-8" aria-labelledby="station-locked-title">
      <EntityCard className="w-full shadow-paper" padding="comfortable">
        <div className="flex flex-col items-start gap-4 sm:flex-row sm:gap-6">
          <LockKeyhole className="mt-1 shrink-0 text-ink-muted" size={28} aria-hidden="true" />
          <div className="min-w-0">
            <h1 id="station-locked-title" className="font-display text-3xl font-black uppercase leading-tight tracking-[-0.03em] sm:text-4xl">
              {t("Coming up: {station}", { station: t(station.label) })}
            </h1>
            <p className="mt-4 max-w-prose font-body text-base leading-7 text-ink-muted">
              {station.key === "book"
                ? t("Your finished pages come together here for final checks and export.")
                : station.key === "pages"
                  ? t("Follow your story from comic script to complete pages, then review each page here.")
                  : t("Your visual direction, characters, and places take shape here.")}
            </p>
          </div>
        </div>
        <ol className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label={t("Production steps")}>
          {STATIONS.map((step) => {
            const available = getRoomAccess(step.primaryRoute, status).state === "available";
            const current = step.key === nextStation.key;
            return <li key={step.key} aria-current={current ? "step" : undefined}
              className={`flex items-center gap-2 px-3 py-4 font-body text-sm font-bold ${current ? "bg-narrator-gold text-ink-black" : "bg-surface-container text-ink-muted"}`}>
              {available && !current ? <Check size={16} aria-hidden="true" /> : <span className="font-meta text-xs">{step.number}</span>}
              {t(step.label)}
            </li>;
          })}
        </ol>
        <div className="mt-8">
          <p className="font-body text-base font-semibold leading-7">{t(access.message)}</p>
          <Link to={`/project/${encodeURIComponent(project)}/${access.route}`}
            className="mt-5 inline-flex min-h-12 items-center justify-center gap-3 border-2 border-ink-black bg-hero-red px-5 py-3 font-meta text-sm font-bold text-bristol shadow-ink-sm hover:bg-ink-black">
            {t("Continue in {station}", { station: t(nextStation.label) })}
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
          <p className="mt-4 font-body text-sm leading-6 text-ink-muted">{t("This station opens automatically when the earlier steps are ready.")}</p>
        </div>
      </EntityCard>
    </section>
  );
}
