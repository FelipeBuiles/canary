import type { AdaptProgressPhase, AdaptProgressSection, AdaptProgressSnapshot } from "../../types/api";
import { useI18n } from "../../i18n";
import { Icon } from "../ui/Icon";
import { ProgressStat, ProgressStats } from "./ProgressStats";

/**
 * Adapt's running view: the comic script taking shape as a beat sheet.
 *
 * Everything drawn here comes from the stage's validated snapshot — a
 * section's beats once its structure validates, its lettering once that
 * validates, and flags from the same checks that gate the script.
 */

const STEPS: { phases: AdaptProgressPhase[]; label: string }[] = [
  { phases: ["treatment"], label: "Shape the story" },
  { phases: ["drafting", "repairing"], label: "Write beats and lettering" },
  { phases: ["checking"], label: "Check against the source" },
  { phases: ["reviewing", "complete"], label: "Story review" },
];

const PHASE_LABEL: Record<AdaptProgressPhase, string> = {
  treatment: "Reading the whole story for its spine, turns, and reveals.",
  drafting: "Staging each part's beats, then writing its lettering.",
  checking: "Checking every beat against the source and your brief.",
  reviewing: "An editor's read for story gaps and contradictions.",
  repairing: "Rewriting the parts the checks flagged.",
  complete: "The comic script is ready.",
};

type TileState = "lettered" | "lettering" | "staged" | "flagged";

function tileState(section: AdaptProgressSection, index: number): TileState {
  if (section.flagged.includes(index)) return "flagged";
  if (section.state === "lettering") return "lettering";
  if (section.state === "staged") return "staged";
  return "lettered";
}

const TILE_FRAME: Record<TileState, string> = {
  lettered: "border-ink-black bg-bristol",
  lettering: "border-ink-black bg-narrator-gold motion-safe:animate-pulse",
  staged: "border-dashed border-ink-soft/60 bg-pulp-paper",
  flagged: "border-dashed border-hero-red bg-chip-red",
};

function BeatTile({ number, functions, state, className = "" }: {
  number: number; functions: string[]; state: TileState; className?: string;
}) {
  const { t } = useI18n();
  const reveal = functions.includes("reveal");
  const turn = functions.includes("character_turn");
  const reaction = functions.includes("reaction") || functions.includes("aftermath");
  const description = [
    t("Beat {n}", { n: String(number) }),
    reveal ? t("Reveal") : null,
    turn ? t("Character turn") : null,
    reaction ? t("Reaction") : null,
    state === "flagged" ? t("Needs a fix") : state === "staged" ? t("Lettering not written yet") : null,
  ].filter(Boolean).join(" · ");

  return (
    <li title={description} aria-label={description}
      className={`relative h-[22px] w-[15px] shrink-0 border-[2px] ${TILE_FRAME[state]} ${className}`}>
      {reaction && <span aria-hidden className="absolute left-1/2 top-1/2 size-[5px] -translate-x-1/2 -translate-y-1/2 bg-ink-black" />}
      {turn && (
        <span aria-hidden
          className="absolute -right-[2px] -top-[2px] size-0 border-l-[7px] border-t-[7px] border-l-transparent border-t-hero-red" />
      )}
      {reveal && <span aria-hidden className="absolute inset-x-0 -bottom-[2px] h-[4px] bg-hero-red" />}
    </li>
  );
}

function sectionTiles(section: AdaptProgressSection, part: number, firstBeat: number, t: (key: string, values?: Record<string, string | number>) => string) {
  // Tiles stay one flat list; a wider gap marks where each part begins.
  const edge = part > 1 ? "ml-2" : "";
  const label = [t("Part {n}", { n: String(part) }), section.title].filter(Boolean).join(": ");
  if (section.beats === null) {
    const structuring = section.state === "structuring";
    const status = t(structuring ? "Staging beats now" : "Waiting");
    return [
      <li key={`part-${part}`} title={`${label} · ${status}`} aria-label={`${label} · ${status}`}
        className={`h-[22px] w-12 shrink-0 border-[2px] ${edge} ${structuring
          ? "border-ink-black bg-narrator-gold motion-safe:animate-pulse"
          : "border-dashed border-ink-soft/60 bg-pulp-paper"}`} />,
    ];
  }
  return section.beats.map((functions, index) => (
    <BeatTile key={`part-${part}-${index}`} number={firstBeat + index} functions={functions}
      state={tileState(section, index)} className={index === 0 ? edge : ""} />
  ));
}

function parts(indices: number[]): string {
  return indices.map((index) => String(index + 1)).join(", ");
}

export function AdaptProgressBoard({ snapshot }: { snapshot: AdaptProgressSnapshot }) {
  const { t } = useI18n();
  const step = STEPS.findIndex((item) => item.phases.includes(snapshot.phase));
  const done = snapshot.phase === "complete";
  const total = snapshot.sections.length;
  const latest = snapshot.rounds.at(-1);
  const hasBeats = snapshot.sections.some((section) => section.beats !== null);
  const indicesIn = (...states: AdaptProgressSection["state"][]) =>
    snapshot.sections.flatMap((section, index) => (states.includes(section.state) ? [index] : []));
  const writing = indicesIn("structuring", "lettering");
  const fixing = indicesIn("repairing");
  const waiting = indicesIn("queued", "staged", "needs_repair");
  const firstBeats = snapshot.sections.map((_, index) =>
    1 + snapshot.sections.slice(0, index).reduce((sum, section) => sum + (section.beats?.length ?? 0), 0));

  return (
    <section aria-label={t("Adaptation progress")} className="@container mt-6">
      <ol aria-label={t("Adaptation steps")} className="grid grid-cols-4 gap-[3px]">
        {STEPS.map((item, index) => (
          <li key={item.label} aria-current={index === step ? "step" : undefined}
            className={`flex min-h-9 min-w-0 items-center justify-center gap-1.5 px-2 py-1.5 font-meta text-[0.6rem] font-bold uppercase leading-tight tracking-[0.06em] @min-[28rem]:min-h-12 @min-[28rem]:flex-col @min-[28rem]:items-start @min-[28rem]:justify-between ${
              index < step || done
                ? "bg-ink-black text-bristol"
                : index === step ? "bg-narrator-gold text-ink-black" : "bg-surface-container text-ink-soft"
            }`}>
            <Icon name={index < step || done ? "check" : index === step ? "loader" : "circle"}
              size={12} className={index === step && !done ? "shrink-0 motion-safe:animate-spin" : "shrink-0"} />
            {/* Narrow boards show numbered steps; the phase line below names the current one. */}
            <span aria-hidden className="tabular-nums @min-[28rem]:hidden">{index + 1}</span>
            <span className="sr-only @min-[28rem]:not-sr-only [overflow-wrap:anywhere]">{t(item.label)}</span>
          </li>
        ))}
      </ol>
      <p role="status" className="mt-3 font-body text-sm font-semibold leading-6 text-ink-black">
        {t(PHASE_LABEL[snapshot.phase])}
      </p>
      {snapshot.treatment && (
        <p className="mt-1 font-body text-xs font-semibold leading-5 text-ink-muted">
          {t("Story shape: {spine} story links · {reveals} reveals · {turns} character turns.", { spine: String(snapshot.treatment.spine), reveals: String(snapshot.treatment.reveals), turns: String(snapshot.treatment.turns) })}
        </p>
      )}

      <ProgressStats>
        <ProgressStat value={hasBeats ? String(snapshot.beats) : "—"} label={t("Story beats")} />
        <ProgressStat value={hasBeats ? String(snapshot.lettering) : "—"} label={t("Lettering lines")} />
        <ProgressStat
          value={String(snapshot.sections_done)}
          total={String(total)}
          label={t("Parts written")}
          detail={t("{n} source passages", { n: String(snapshot.source_units) })}
        />
        <ProgressStat
          value={latest ? String(latest.blocking) : "—"}
          label={t("Issues to fix")}
          detail={latest
            ? t(latest.blocking ? "Check {n} of {max}" : "Check {n} passed", { n: String(latest.round), max: String(snapshot.max_rounds) })
            : undefined}
        />
      </ProgressStats>

      <ol aria-label={t("Beat sheet")} className="mt-4 flex flex-wrap gap-[5px]">
        {snapshot.sections.flatMap((section, index) => sectionTiles(section, index + 1, firstBeats[index], t))}
      </ol>
      {hasBeats && (
        <div aria-hidden className="mt-3 flex flex-wrap gap-x-4 gap-y-1 font-meta text-[0.62rem] font-bold text-ink-muted">
          <span className="flex items-center gap-1.5"><span className="size-2.5 border-[2px] border-ink-black bg-bristol" />{t("Lettered")}</span>
          <span className="flex items-center gap-1.5"><span className="size-2.5 border-[2px] border-dashed border-ink-soft/60" />{t("Staged")}</span>
          <span className="flex items-center gap-1.5"><span className="size-2.5 border-[2px] border-dashed border-hero-red bg-chip-red" />{t("Needs a fix")}</span>
          <span className="flex items-center gap-1.5"><span className="h-[4px] w-2.5 bg-hero-red" />{t("Reveal")}</span>
          <span className="flex items-center gap-1.5"><span className="size-0 border-l-[8px] border-t-[8px] border-l-transparent border-t-hero-red" />{t("Character turn")}</span>
          <span className="flex items-center gap-1.5"><span className="size-[5px] bg-ink-black" />{t("Reaction")}</span>
        </div>
      )}

      {(writing.length > 0 || fixing.length > 0 || (waiting.length > 0 && !done)) && (
        <p className="mt-3 font-body text-xs font-semibold leading-5 text-ink-muted">
          {[
            writing.length > 0 ? t("Writing part {parts}.", { parts: parts(writing) }) : null,
            fixing.length > 0 ? t("Fixing part {parts}.", { parts: parts(fixing) }) : null,
            waiting.length > 0 && snapshot.phase !== "checking" && snapshot.phase !== "reviewing"
              ? t("{count, plural, one {# part waiting.} other {# parts waiting.}}", { count: waiting.length })
              : null,
            snapshot.serial_transport && waiting.length > 0 && (writing.length > 0 || fixing.length > 0)
              ? t("This model writes one part at a time, so waiting parts start as each one finishes.")
              : null,
          ].filter(Boolean).join(" ")}
        </p>
      )}

      {snapshot.rounds.length > 0 && (
        <ol aria-label={t("Checks")} className="mt-3 space-y-1 border-t-[2px] border-ink-black/10 pt-3">
          {snapshot.rounds.map((round) => (
            <li key={round.round} className="flex items-center gap-2 font-body text-xs font-semibold leading-5 text-ink-muted">
              <Icon name={round.blocking ? "alert" : "check"} size={12}
                className={round.blocking ? "text-hero-red" : "text-ink-black"} />
              <span>
                {(round.blocking
                  ? t("{count, plural, one {Check {n}: # issue to fix.} other {Check {n}: # issues to fix.}}", { count: round.blocking, n: round.round })
                  : t("Check {n}: passed.", { n: round.round })
                )}
                {round.notes > 0 && ` ${t("{count, plural, one {# note for your review.} other {# notes for your review.}}", { count: round.notes })}`}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
