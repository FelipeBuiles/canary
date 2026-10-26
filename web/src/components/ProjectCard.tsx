import { useState } from "react";
import { Link } from "react-router-dom";
import type { ProjectSummary } from "../types/api";
import { LazyImage } from "./ui/LazyImage";
import { Icon } from "./ui/Icon";
import { projectCoverColor, projectShelfState, projectStation } from "../lib/projectShelf";
import { useI18n } from "../i18n";
import { partProjectKey, projectFileUrl } from "../api/projectScope";


interface Props {
  project: ProjectSummary;
  coverPending?: boolean;
  coverFailed?: boolean;
  coverRetrying?: boolean;
  onRetryCover?: () => void;
  onDeleteIncompatible?: () => void;
  deleteIncompatiblePending?: boolean;
}

export function ProjectCard({
  project,
  coverPending = false,
  coverFailed = false,
  coverRetrying = false,
  onRetryCover,
  onDeleteIncompatible,
  deleteIncompatiblePending = false,
}: Props) {
  const { t } = useI18n();
  const state = projectShelfState(project);
  const station = projectStation(project);
  // Each part has its own cover; the card shows the first part's.
  const coverUrl = projectFileUrl(partProjectKey(project.id, project.cover_part_id), "cover/cover.png");
  const coverComplete = project.has_cover && project.cover_job?.status === "complete";
  const [coverTransition, setCoverTransition] = useState({ project: project.id, complete: coverComplete, reveal: false });
  if (coverTransition.project !== project.id || coverTransition.complete !== coverComplete) {
    setCoverTransition({
      project: project.id,
      complete: coverComplete,
      reveal: coverTransition.project === project.id && !coverTransition.complete && coverComplete,
    });
  }

  const coverBg = projectCoverColor(project);
  const showRetry = coverFailed && !project.has_cover && !coverPending && Boolean(onRetryCover);
  const title = (
    <h3 className="break-words font-display font-black uppercase leading-[0.92] tracking-[-0.025em]">
      {project.project_name}
    </h3>
  );

  // The cover is the card: a whole 3:4 issue with its title printed on it.
  const cover = (
    <div className={`relative aspect-[3/4] overflow-hidden bg-ink-black shadow-[0_1px_2px_rgb(27_28_21/0.25),0_16px_30px_-16px_rgb(27_28_21/0.55)] transition-[translate,box-shadow] duration-200 ease-[cubic-bezier(.22,1,.36,1)] group-hover:-translate-x-0.5 group-hover:-translate-y-[3px] group-hover:shadow-[4px_5px_0_var(--color-ink-black),0_22px_36px_-18px_rgb(27_28_21/0.55)] group-focus-visible:-translate-x-0.5 group-focus-visible:-translate-y-[3px] group-focus-visible:shadow-[4px_5px_0_var(--color-ink-black)] ${state === "reset" ? "opacity-55 grayscale" : ""}`}>
      {project.has_cover ? (
        <>
          <LazyImage
            src={coverUrl}
            alt=""
            aspect="3 / 4"
            loading="lazy"
            containerClassName={`absolute inset-0 w-full${coverTransition.reveal ? " animate-proof-reveal" : ""}`}
            className="transition-transform duration-500 ease-[cubic-bezier(.22,1,.36,1)] group-hover:scale-[1.03]"
          />
          <div className="absolute inset-x-0 top-0 bg-gradient-to-b from-[rgb(14_14_10/0.86)] via-[rgb(14_14_10/0.55)] to-transparent px-3.5 pb-10 pt-3.5 text-pulp-paper [text-shadow:0_1px_10px_rgb(0_0_0/0.5)] [&_h3]:text-[1.3rem]">
            {title}
          </div>
        </>
      ) : coverPending ? (
        <div className="benday-paper absolute inset-0 px-3.5 pt-3.5 text-ink-black [&_h3]:text-[1.3rem]">
          {title}
        </div>
      ) : (
        <div className="benday-ink absolute inset-0 flex flex-col justify-end px-3.5 pb-12 pt-3.5 text-pulp-paper [&_h3]:text-[1.85rem]" style={{ backgroundColor: coverBg }}>
          {title}
          {project.author && <p className="mt-2 font-body text-xs font-semibold text-pulp-paper/70">{project.author}</p>}
        </div>
      )}

      {coverPending ? (
        <div className="absolute inset-x-0 bottom-0 flex h-[30px] items-center gap-2 whitespace-nowrap bg-narrator-gold px-3 font-meta text-[0.6875rem] font-bold tracking-[0.06em] text-ink-black">
          <span aria-hidden="true" className="animate-press-blink inline-block h-[7px] w-[7px] bg-hero-red" />
          {t("DRAWING COVER…")}
        </div>
      ) : state === "working" ? (
        <div className="absolute inset-x-0 bottom-0 flex h-[30px] items-center gap-2 whitespace-nowrap bg-ink-black px-3 font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-pulp-paper">
          <span aria-hidden="true" className="animate-press-blink inline-block h-[7px] w-[7px] bg-hero-red" />
          {station ? `${t("Working")} · ${t(station.label)}` : t("Working")}
        </div>
      ) : state === "needs" && !showRetry ? (
        <span className="absolute bottom-2.5 left-2.5 inline-flex h-6 items-center gap-[7px] border border-ink-black bg-narrator-gold px-2 font-meta text-[0.6875rem] font-bold uppercase tracking-[0.06em] text-ink-black shadow-[2px_2px_0_var(--color-ink-black)]">
          <span aria-hidden="true" className="inline-block h-[7px] w-[7px] bg-ink-black" />
          {project.furthest_stage ? t("Needs you") : t("Not started")}
        </span>
      ) : null}

      {state === "done" && (
        <span aria-hidden="true" className="absolute bottom-2.5 right-2.5 inline-flex h-7 translate-y-1 items-center gap-1.5 border border-ink-black bg-pulp-paper px-2.5 font-meta text-xs font-semibold text-ink-black opacity-0 transition-[opacity,translate] duration-150 group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:translate-y-0 group-focus-visible:opacity-100">
          {t("Open")}
          <Icon name="arrow-right" size={13} />
        </span>
      )}
    </div>
  );

  return (
    <div className="relative flex min-w-0 flex-col gap-2.5">
      {state === "reset" ? (
        <div aria-label={`${t("PROJECT CANNOT OPEN")}: ${project.project_name}`}>{cover}</div>
      ) : (
        <Link
          to={`/project/${encodeURIComponent(project.id)}`}
          aria-label={`${t("OPEN FILE")}: ${project.project_name}`}
          className="group block focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
        >
          {cover}
        </Link>
      )}

      {showRetry && (
        <button
          type="button"
          className="absolute bottom-[calc(1.125rem+10px+0.625rem)] left-3.5 z-10 inline-flex min-h-7 items-center gap-1.5 border border-ink-black bg-pulp-paper px-2.5 font-meta text-xs font-semibold text-ink-black transition-colors hover:bg-narrator-gold disabled:cursor-wait disabled:opacity-75"
          onClick={onRetryCover}
          disabled={coverRetrying}
        >
          <Icon name="reset" size={13} />
          {coverRetrying ? t("RETRYING COVER…") : t("Retry cover")}
        </button>
      )}

      <div className="flex min-w-0 items-baseline justify-between gap-2 font-body text-[0.8125rem] leading-[1.125rem] text-ink-soft">
        {state === "reset" ? (
          <>
            <span className="font-meta text-xs font-semibold uppercase tracking-[0.06em] text-ink-muted">{t("Needs reset")}</span>
            {onDeleteIncompatible && (
              <button
                type="button"
                className="min-h-7 border border-hero-red bg-bristol px-2.5 font-meta text-xs font-semibold text-status-blocked-text transition-colors hover:bg-chip-red disabled:cursor-wait disabled:opacity-75"
                onClick={onDeleteIncompatible}
                disabled={deleteIncompatiblePending}
              >
                {deleteIncompatiblePending ? t("REMOVING…") : t("Remove")}
              </button>
            )}
          </>
        ) : (
          <>
            <span className="truncate">{project.author ?? ""}</span>
            {state !== "done" && station && <span className="flex-none font-meta text-xs text-ink-muted">{t(station.label)}</span>}
          </>
        )}
      </div>
    </div>
  );
}
