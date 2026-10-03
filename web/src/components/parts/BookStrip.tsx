import { useId, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Check, ChevronDown, CircleAlert, LoaderCircle } from "lucide-react";
import { useI18n } from "../../i18n";
import { partProjectKey, splitProjectKey } from "../../api/projectScope";
import type { PartSummary } from "../../types/api";
import { cn } from "../../lib/cn";
import { partState, type PartState } from "../../lib/partProgress";
import { StageStartAction } from "../composites/StagePlaceholder";
import { Surface } from "../ui/Surface";
import { PartsDialog } from "./PartsDialog";

const ANALYZED: ReadonlySet<PartState> = new Set(["review", "approved", "finished"]);

const STATE_LABELS: Record<PartState, string> = {
  not_started: "Not started",
  analyzing: "Analyzing…",
  needs_brief: "Brief not prepared",
  review: "Brief to review",
  approved: "Brief approved",
  finished: "Finished",
  attention: "Needs attention",
};

interface BookStripProps {
  project: string;
  parts: PartSummary[];
  /** "ink" sits inside the Story hero; "paper" stands alone above stage progress. */
  tone?: "ink" | "paper";
}

/**
 * The saved book at a glance: one segment per part, sized by its text.
 *
 * The first message is what matters most on first ingestion: the whole book
 * is saved, but only the part the author starts is analyzed. Details stay one
 * click away. The next part is offered only once the current part's Brief is
 * approved, so a paid start never competes with the review in front of it.
 */
export function BookStrip({ project, parts, tone = "ink" }: BookStripProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [managing, setManaging] = useState(false);
  const { id, part: currentId } = splitProjectKey(project);
  if (parts.length < 2) return null;

  const states = parts.map(partState);
  const analyzed = states.filter((state) => ANALYZED.has(state)).length;
  const analyzing = parts.find((_part, index) => states[index] === "analyzing");
  const attention = parts.find((_part, index) => states[index] === "attention");
  const currentIndex = parts.findIndex((part) => part.id === currentId);
  const current = parts[currentIndex];
  const nextIndex = states.findIndex((state) => state === "not_started");
  const next = parts[nextIndex];
  // Extract reads the previous part's Story Bible additions, so parts start in
  // reading order, one at a time, after the open part's Brief is approved.
  const offerNext = Boolean(next && current && !analyzing && !attention
    && (states[currentIndex] === "approved" || states[currentIndex] === "finished")
    && nextIndex === currentIndex + 1);
  const ink = tone === "ink";

  const summary = analyzed === 0 && !analyzing
    ? t("Your book is saved as {count} parts. Story analysis starts with Part 1; you start each later part yourself.", { count: parts.length })
    : analyzed === parts.length
      ? t("All {count} parts analyzed.", { count: parts.length })
      : t("{analyzed} of {count} parts analyzed. The rest are saved and wait until you start them.", { analyzed, count: parts.length });

  return (
    <div className={cn("min-w-0", ink ? "text-pulp-paper" : "text-ink-black")}>
      <div className="flex items-end gap-[3px]" aria-hidden="true">
        {parts.map((part, index) => {
          const state = states[index];
          const isCurrent = part.id === currentId;
          return (
            <span
              key={part.id}
              title={`${part.ordinal}. ${part.title} · ${t(STATE_LABELS[state])}`}
              style={{ flexGrow: Math.max(part.characters, 1) }}
              className={cn(
                "block min-w-1.5 basis-0 transition-[height]",
                isCurrent ? "h-4" : "h-2.5",
                ANALYZED.has(state) ? (ink ? "bg-narrator-gold" : "bg-ink-black")
                  : state === "attention" ? "bg-hero-red"
                    : state === "analyzing" || state === "needs_brief"
                      ? cn(ink ? "bg-narrator-gold/45" : "bg-ink-black/35", state === "analyzing" && "motion-safe:animate-pulse")
                      : ink ? "border border-pulp-paper/45" : "border border-ink-black/30",
              )}
            />
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <p role="status" className={cn("max-w-[64ch] font-body text-sm leading-6", ink ? "text-pulp-paper/85" : "text-ink-muted")}>
          {summary}
          {analyzing && analyzing.id !== currentId && <> {t("Part {number} is being analyzed.", { number: analyzing.ordinal })}</>}
          {attention && attention.id !== currentId && <> {t("Part {number} needs attention.", { number: attention.ordinal })}</>}
        </p>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((value) => !value)}
          className={cn(
            "inline-flex min-h-11 shrink-0 items-center gap-2 font-meta text-xs font-bold uppercase tracking-[0.1em] underline decoration-2 underline-offset-[6px]",
            ink ? "decoration-narrator-gold hover:text-narrator-gold" : "decoration-hero-red hover:text-hero-red",
            "focus-visible:outline-2 focus-visible:outline-offset-2",
          )}
        >
          {open ? t("Hide parts") : t("All {count} parts", { count: parts.length })}
          <ChevronDown size={16} aria-hidden="true" className={cn("transition-transform motion-reduce:transition-none", open && "rotate-180")} />
        </button>
      </div>

      {offerNext && next && (
        <div className={cn("mt-4 p-4", ink ? "bg-pulp-paper/10" : "bg-surface-container")}>
          <StageStartAction
            key={partProjectKey(id, next.id)}
            project={partProjectKey(id, next.id)}
            stage="extract"
            layout="footer"
            buttonVariant={ink ? "onInk" : "primary"}
            label={t("Start Part {number}", { number: next.ordinal })}
            description={t("Analyze Part {number} ({title}) and prepare its story brief. It continues from the parts before it; you review its brief before anything is drawn.", { number: next.ordinal, title: next.title })}
            onStarted={() => navigate(`/project/${encodeURIComponent(partProjectKey(id, next.id))}/story`)}
          />
        </div>
      )}

      <div id={listId} hidden={!open}>
        <ol aria-label={t("Parts in reading order")} className="mt-4 space-y-1">
          {parts.map((part, index) => {
            const state = states[index];
            const isCurrent = part.id === currentId;
            const StateIcon = state === "attention" ? CircleAlert : state === "analyzing" ? LoaderCircle : ANALYZED.has(state) ? Check : null;
            return (
              <li key={part.id}>
                <Link
                  to={`/project/${encodeURIComponent(partProjectKey(id, part.id))}/story`}
                  aria-current={isCurrent ? "page" : undefined}
                  className={cn(
                    "group grid min-h-14 grid-cols-[2rem_minmax(0,1fr)_auto] items-start gap-x-3 px-3 py-3 transition-colors",
                    "focus-visible:outline-2 focus-visible:outline-offset-2",
                    ink ? "hover:bg-pulp-paper/10" : "hover:bg-surface-container",
                    isCurrent && (ink ? "bg-pulp-paper/10" : "bg-chip-gold/40"),
                  )}
                >
                  <span className={cn("pt-0.5 font-meta text-sm font-semibold tabular-nums", ink ? "text-narrator-gold" : "text-ink-muted")}>
                    {part.ordinal.toString().padStart(2, "0")}
                  </span>
                  <span className="min-w-0">
                    <span className="block font-body text-sm font-semibold leading-5">
                      {part.title}
                      {isCurrent && <span className={cn("ml-2 font-meta text-[0.65rem] font-bold uppercase tracking-[0.1em]", ink ? "text-narrator-gold" : "text-hero-red")}>{t("Viewing")}</span>}
                    </span>
                    <span className={cn("mt-1 block font-body text-xs leading-5", ink ? "text-pulp-paper/70" : "text-ink-muted")}>
                      {part.synopsis ?? t("{count}k characters", { count: Math.max(1, Math.round(part.characters / 1000)) })}
                    </span>
                  </span>
                  <span className={cn(
                    "flex items-center gap-1.5 whitespace-nowrap pt-0.5 font-body text-xs leading-5",
                    state === "attention" ? (ink ? "text-[#ff8a80]" : "text-hero-red") : ink ? "text-pulp-paper/80" : "text-ink-muted",
                  )}>
                    {StateIcon && <StateIcon size={14} aria-hidden="true" className={state === "analyzing" ? "motion-safe:animate-spin" : undefined} />}
                    {t(STATE_LABELS[state])}
                    <ArrowRight size={14} aria-hidden="true" className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
                  </span>
                </Link>
              </li>
            );
          })}
        </ol>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 px-3">
          <p className={cn("font-body text-xs leading-5", ink ? "text-pulp-paper/70" : "text-ink-muted")}>
            {t("Characters, places and the visual style are shared by every part.")}
          </p>
          <button type="button" onClick={() => setManaging(true)}
            className="min-h-11 font-meta text-xs font-bold uppercase tracking-[0.1em] underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2">
            {t("Manage parts")}
          </button>
        </div>
      </div>
      <PartsDialog open={managing} project={project} parts={parts} onClose={() => setManaging(false)} />
    </div>
  );
}

/** The strip on its own sheet, above a part's analysis progress. */
export function BookStripPanel({ project, parts }: { project: string; parts: PartSummary[] }) {
  const { t } = useI18n();
  const current = parts.find((part) => part.id === splitProjectKey(project).part);
  if (parts.length < 2 || !current) return null;
  return (
    <Surface padding="md" shadow="paper-sm" aria-labelledby="book-strip-title">
      <p className="font-meta text-xs font-bold uppercase tracking-[0.1em] text-ink-muted">
        {t("Part {number} of {count}", { number: current.ordinal, count: parts.length })}
      </p>
      <h2 id="book-strip-title" className="mt-1 break-words font-display text-xl font-black uppercase leading-tight tracking-[-0.02em] sm:text-2xl">
        {current.title}
      </h2>
      <div className="mt-4">
        <BookStrip project={project} parts={parts} tone="paper" />
      </div>
    </Surface>
  );
}
