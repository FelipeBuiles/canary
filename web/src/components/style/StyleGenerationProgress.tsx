import { useEffect, useState } from "react";
import type { GenerationJob } from "../../types/api";
import { useI18n } from "../../i18n";
import { Icon } from "../ui/Icon";
import { RoomNotice } from "../composites/RoomNotice";
import { proofCounts, shortlistOf, STEPS, stylePhaseOf, type StylePhase } from "./styleBatch";

/**
 * Look's running view: which step a style batch is on and why it takes time.
 *
 * Everything comes from the batch job's durable payload (`style_phase`,
 * `style_shortlist`, `proofs`), so a reloaded room shows the same step.
 */

const PHASE_COPY: Record<StylePhase, string> = {
  queued: "Waiting for a free generation slot. Your batch starts automatically.",
  directions: "Reading your story and weighing a dozen visual directions. The six most distinct make the cut, each with its own medium and character design.",
  production: "Giving each chosen direction its own lettering and page framing, so every proof shows a finished comic page.",
  proofs: "Painting the same scene in every style, so you compare looks, not subjects. Each proof appears as soon as it's done.",
};

function useElapsedSeconds(since: string | null | undefined): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!since) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [since]);
  if (!since) return null;
  const started = Date.parse(since);
  return Number.isFinite(started) ? Math.max(0, Math.floor((now - started) / 1000)) : null;
}

function formatElapsed(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function StyleGenerationProgress({
  job, fallbackPhase, title, compact = false,
}: {
  job: GenerationJob | undefined;
  /** Used when no batch job carries a phase (for example a pipeline-run Style stage). */
  fallbackPhase: StylePhase;
  title: string;
  /** One line in the room's notice row, for when proofs already fill the table. */
  compact?: boolean;
}) {
  const { t } = useI18n();
  const phase = stylePhaseOf(job, fallbackPhase);
  const step = STEPS.findIndex((item) => item.phase === phase);
  const elapsed = useElapsedSeconds(job?.status === "running" ? job.started_at : null);
  const shortlist = shortlistOf(job);
  const { done, total } = proofCounts(job);

  const clock = elapsed !== null && (
    <span className="font-meta text-xs font-medium tabular-nums text-ink-muted"
      aria-label={t("Elapsed {time}", { time: formatElapsed(elapsed) })}>
      {formatElapsed(elapsed)}
    </span>
  );
  const body = (
    <>
      <ol aria-label={t("Style generation steps")} className="grid grid-cols-1 gap-1 @min-[22rem]:grid-cols-3">
        {STEPS.map((item, index) => (
          <li key={item.phase} aria-current={index === step ? "step" : undefined}
            className={`flex min-h-9 min-w-0 items-center gap-2 px-2.5 py-1.5 font-meta text-xs font-medium leading-tight ${
              index < step ? "bg-ink-black text-bristol"
                : index === step ? "bg-chip-gold text-ink-black" : "bg-surface-container text-ink-soft"
            }`}>
            <Icon name={index < step ? "check" : index === step ? "loader" : "circle"} size={13}
              className={index === step ? "shrink-0 motion-safe:animate-spin" : "shrink-0"} />
            <span className="min-w-0 [overflow-wrap:anywhere]">
              {t(item.label)}
              {item.phase === "proofs" && index === step && total > 0 && (
                <span className="tabular-nums"> {done}<wbr />/{total}</span>
              )}
            </span>
          </li>
        ))}
      </ol>

      <p role={compact ? undefined : "status"} aria-live={compact ? undefined : "polite"} className="mt-3 font-body text-sm leading-6">
        {t(PHASE_COPY[phase])}
        {phase === "queued" && job?.queue_position ? ` ${t("Position {n} in line.", { n: String(job.queue_position) })}` : ""}
      </p>
      {phase !== "queued" && (
        <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
          {t("A full batch usually takes a couple of minutes. You can leave this room; the proofs keep painting.")}
        </p>
      )}

      {phase === "production" && shortlist.length > 0 && (
        <ul aria-label={t("Chosen directions")} className="mt-3 grid gap-1 sm:grid-cols-2">
          {shortlist.map((entry) => (
            <li key={`${entry.role}:${entry.label}`} className="min-w-0 border border-ink-black/10 px-3 py-2">
              <div className="truncate font-display text-sm font-bold leading-tight">{entry.label}</div>
              <div className="mt-0.5 truncate font-meta text-xs text-ink-muted">{entry.medium}</div>
              {entry.story_fit && (
                <p className="mt-1 line-clamp-2 font-body text-xs leading-5 text-ink-black/75">{entry.story_fit}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );

  if (compact) {
    const current = step >= 0 ? STEPS[step] : null;
    const stepText = current
      ? `${t(current.label)}${current.phase === "proofs" && total > 0 ? ` ${done}/${total}` : ""}`
      : t("Waiting to start");
    return (
      <section aria-label={t("Style generation progress")}>
        <RoomNotice tone="working" title={title}
          label={<>{title} · {stepText}{elapsed !== null && <> · <span className="tabular-nums">{formatElapsed(elapsed)}</span></>}</>}>
          <div className="@container">{body}</div>
        </RoomNotice>
      </section>
    );
  }

  return (
    <section aria-label={t("Style generation progress")}
      className="@container w-full max-w-[40rem] border border-ink-black bg-bristol p-5 text-ink-black shadow-float">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex min-w-0 items-center gap-2 font-meta text-sm font-semibold">
          <span aria-hidden className="animate-press-blink size-2 shrink-0 bg-hero-red" />
          <span className="min-w-0 [overflow-wrap:anywhere]">{title}</span>
        </h2>
        {clock}
      </div>
      {body}
    </section>
  );
}
