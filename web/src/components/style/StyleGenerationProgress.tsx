import { useEffect, useState } from "react";
import type { GenerationJob } from "../../types/api";
import { useI18n } from "../../i18n";
import { Icon } from "../ui/Icon";

/**
 * Look's running view: which step a style batch is on and why it takes time.
 *
 * Everything comes from the batch job's durable payload (`style_phase`,
 * `style_shortlist`, `proofs`), so a reloaded room shows the same step.
 */

type StylePhase = "queued" | "directions" | "production" | "proofs";

interface ShortlistEntry {
  label: string;
  medium: string;
  role: string;
  palette?: string;
  story_fit?: string;
}

const STEPS: { phase: Exclude<StylePhase, "queued">; label: string }[] = [
  { phase: "directions", label: "Choose directions" },
  { phase: "production", label: "Design lettering" },
  { phase: "proofs", label: "Paint proofs" },
];

const PHASE_COPY: Record<StylePhase, string> = {
  queued: "Waiting for a free generation slot. Your batch starts automatically.",
  directions: "Reading your story and weighing a dozen visual directions. The six most distinct make the cut, each with its own medium and character design.",
  production: "Giving each chosen direction its own lettering and page framing, so every proof shows a finished comic page.",
  proofs: "Painting the same scene in every style, so you compare looks, not subjects. Each proof appears as soon as it's done.",
};

function stylePhaseOf(job: GenerationJob | undefined, fallback: StylePhase): StylePhase {
  if (job?.status === "queued") return "queued";
  const phase = job?.payload.style_phase;
  return phase === "directions" || phase === "production" || phase === "proofs" ? phase : fallback;
}

function shortlistOf(job: GenerationJob | undefined): ShortlistEntry[] {
  const entries = job?.payload.style_shortlist;
  return Array.isArray(entries)
    ? entries.filter((entry): entry is ShortlistEntry =>
      !!entry && typeof entry === "object" && typeof (entry as ShortlistEntry).label === "string")
    : [];
}

function proofCounts(job: GenerationJob | undefined): { done: number; total: number } {
  const proofs = job?.payload.proofs;
  if (!proofs || typeof proofs !== "object") return { done: 0, total: 0 };
  const values = Object.values(proofs as Record<string, { status?: string }>);
  return { done: values.filter((proof) => proof?.status === "complete").length, total: values.length };
}

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
  job, fallbackPhase, title,
}: {
  job: GenerationJob | undefined;
  /** Used when no batch job carries a phase (for example a pipeline-run Style stage). */
  fallbackPhase: StylePhase;
  title: string;
}) {
  const { t } = useI18n();
  const phase = stylePhaseOf(job, fallbackPhase);
  const step = STEPS.findIndex((item) => item.phase === phase);
  const elapsed = useElapsedSeconds(job?.status === "running" ? job.started_at : null);
  const shortlist = shortlistOf(job);
  const { done, total } = proofCounts(job);

  return (
    <section aria-label={t("Style generation progress")}
      className="mt-4 border-[2px] border-ink-black bg-narrator-gold p-3 text-ink-black md:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span aria-hidden className="animate-press-blink h-2.5 w-2.5 bg-hero-red" />
          <span className="font-meta text-[0.7rem] font-bold tracking-[0.08em]">{title}</span>
        </div>
        {elapsed !== null && (
          <span className="font-meta text-[0.68rem] font-bold tabular-nums tracking-[0.08em]"
            aria-label={t("Elapsed {time}", { time: formatElapsed(elapsed) })}>
            {formatElapsed(elapsed)}
          </span>
        )}
      </div>

      <ol aria-label={t("Style generation steps")} className="mt-3 grid grid-cols-3 gap-[3px]">
        {STEPS.map((item, index) => (
          <li key={item.phase} aria-current={index === step ? "step" : undefined}
            className={`flex min-h-9 items-center gap-1.5 px-2 py-1.5 font-meta text-[0.6rem] font-bold uppercase leading-tight tracking-[0.06em] ${
              index < step ? "bg-ink-black text-bristol"
                : index === step ? "bg-bristol text-ink-black" : "bg-pulp-paper/60 text-ink-soft"
            }`}>
            <Icon name={index < step ? "check" : index === step ? "loader" : "circle"} size={12}
              className={index === step ? "shrink-0 motion-safe:animate-spin" : "shrink-0"} />
            <span>
              {t(item.label)}
              {item.phase === "proofs" && index === step && total > 0 && (
                <span className="tabular-nums"> {done}/{total}</span>
              )}
            </span>
          </li>
        ))}
      </ol>

      <p role="status" aria-live="polite" className="mt-3 font-body text-[0.84rem] leading-relaxed">
        {t(PHASE_COPY[phase])}
        {phase === "queued" && job?.queue_position ? ` ${t("Position {n} in line.", { n: String(job.queue_position) })}` : ""}
      </p>
      {phase !== "queued" && (
        <p className="mt-1 font-body text-xs leading-5 text-ink-black/70">
          {t("A full batch usually takes a couple of minutes. You can leave this room; the proofs keep painting.")}
        </p>
      )}

      {phase === "production" && shortlist.length > 0 && (
        <ul aria-label={t("Chosen directions")} className="mt-3 grid gap-[3px] sm:grid-cols-2 lg:grid-cols-3">
          {shortlist.map((entry) => (
            <li key={`${entry.role}:${entry.label}`} className="min-w-0 bg-bristol px-3 py-2">
              <div className="truncate font-display text-sm font-bold leading-tight">{entry.label}</div>
              <div className="mt-0.5 truncate font-meta text-[0.62rem] font-bold uppercase tracking-[0.06em] text-ink-muted">
                {entry.medium}
              </div>
              {entry.story_fit && (
                <p className="mt-1 line-clamp-2 font-body text-xs leading-5 text-ink-black/75">{entry.story_fit}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
