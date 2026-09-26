import type { PlanBatchState, PlanProgressPage, PlanProgressPhase, PlanProgressSnapshot } from "../../types/api";
import { useI18n } from "../../i18n";
import { Icon } from "../ui/Icon";
import { panelRows } from "../../lib/planProgress";

/**
 * Plan's running view: the book taking shape as a contact sheet.
 *
 * Everything drawn here comes from the stage's validated snapshot — the
 * checked page map, then each batch once its pages compile. Nothing is
 * inferred from elapsed time, so a tile only fills when that page is real.
 */

const STEPS: { phases: PlanProgressPhase[]; label: string }[] = [
  { phases: ["mapping"], label: "Map the book" },
  { phases: ["reviewing_map"], label: "Check story flow" },
  { phases: ["laying_out", "repairing"], label: "Lay out panels" },
  { phases: ["checking"], label: "Check continuity" },
  { phases: ["reviewing", "complete"], label: "Final story review" },
];

const PHASE_LABEL: Record<PlanProgressPhase, string> = {
  mapping: "Deciding how many pages each story beat needs.",
  reviewing_map: "Reading the page map for pacing and story flow.",
  laying_out: "Composing panels and placing every line of lettering.",
  checking: "Checking continuity across the whole book.",
  repairing: "Fixing the pages the checks flagged.",
  reviewing: "A final read of the complete plan.",
  complete: "The page plan is ready.",
};

type TileState = "laid_out" | "writing" | "repair" | "waiting";

function batchStateFor(snapshot: PlanProgressSnapshot, page: number): PlanBatchState | null {
  const batch = snapshot.batches.find((item) => page >= item.first && page <= item.last);
  return batch?.state ?? null;
}

function tileState(snapshot: PlanProgressSnapshot, page: PlanProgressPage): TileState {
  const batch = batchStateFor(snapshot, page.page);
  if (batch === "needs_repair" || batch === "repairing") return "repair";
  if (page.panels !== null) return "laid_out";
  if (batch === "writing") return "writing";
  return "waiting";
}

function PageTile({ page, state }: { page: PlanProgressPage; state: TileState }) {
  const { t } = useI18n();
  const peak = page.emphasis === "peak";
  const turn = page.turn === "reveal" || page.turn === "cliffhanger";
  const frame = {
    laid_out: "border-ink-black bg-bristol",
    writing: "border-ink-black bg-narrator-gold motion-safe:animate-pulse",
    repair: "border-dashed border-hero-red bg-chip-red",
    waiting: "border-dashed border-ink-soft/60 bg-pulp-paper",
  }[state];
  const description = [
    t("Page {n}", { n: String(page.page) }),
    page.panels !== null
      ? t("{n} panels", { n: String(page.panels) })
      : t("{n} story beats", { n: String(page.beats) }),
    peak ? t("Peak moment") : null,
    turn ? t("Page-turn reveal") : null,
  ].filter(Boolean).join(" · ");

  return (
    <li title={description} aria-label={description}
      className={`relative aspect-[2/3] border-[2px] ${frame}`}>
      {page.panels !== null ? (
        <div aria-hidden className="flex h-full flex-col gap-[2px] p-[3px]">
          {panelRows(page.panels).map((cells, row) => (
            <div key={row} className="flex flex-1 gap-[2px]">
              {Array.from({ length: cells }, (_, cell) => (
                <div key={cell} className="flex-1 bg-surface-variant" />
              ))}
            </div>
          ))}
        </div>
      ) : (
        <div aria-hidden className="flex h-full flex-wrap content-center justify-center gap-[3px] p-[4px]">
          {Array.from({ length: Math.min(page.beats, 6) }, (_, index) => (
            <span key={index} className="size-[4px] bg-ink-soft/60" />
          ))}
        </div>
      )}
      {peak && (
        <span aria-hidden
          className="absolute -right-[2px] -top-[2px] size-0 border-l-[9px] border-t-[9px] border-l-transparent border-t-hero-red" />
      )}
      {turn && <span aria-hidden className="absolute inset-x-0 -bottom-[2px] h-[4px] bg-hero-red" />}
    </li>
  );
}

function Stat({ value, label, detail }: { value: string; label: string; detail?: string }) {
  return (
    <div className="min-w-0 bg-bristol px-3 py-2.5">
      <div className="font-display text-[1.7rem] font-black leading-none tracking-[-0.03em] tabular-nums text-ink-black">
        {value}
      </div>
      <div className="mt-1 font-meta text-[0.62rem] font-bold uppercase tracking-[0.08em] text-ink-muted">{label}</div>
      {detail && <div className="mt-0.5 font-meta text-[0.62rem] text-ink-soft">{detail}</div>}
    </div>
  );
}

export function PlanProgressBoard({ snapshot }: { snapshot: PlanProgressSnapshot }) {
  const { t } = useI18n();
  const step = STEPS.findIndex((item) => item.phases.includes(snapshot.phase));
  const pageCount = snapshot.pages.length;
  const writing = snapshot.batches.filter((batch) => batch.state === "writing" || batch.state === "repairing");
  const queued = snapshot.batches.filter((batch) => batch.state === "queued" || batch.state === "needs_repair");
  const range = (batch: { first: number; last: number }) =>
    batch.first === batch.last ? String(batch.first) : `${batch.first}–${batch.last}`;

  return (
    <section aria-label={t("Plan progress")} className="mt-6">
      <ol aria-label={t("Planning steps")} className="grid grid-cols-5 gap-[3px]">
        {STEPS.map((item, index) => (
          <li key={item.label} aria-current={index === step ? "step" : undefined}
            className={`flex min-h-9 items-center justify-center gap-1.5 px-2 py-1.5 font-meta text-[0.6rem] font-bold uppercase leading-tight tracking-[0.06em] sm:min-h-12 sm:flex-col sm:items-start sm:justify-between ${
              index < step || snapshot.phase === "complete"
                ? "bg-ink-black text-bristol"
                : index === step ? "bg-narrator-gold text-ink-black" : "bg-surface-container text-ink-soft"
            }`}>
            <Icon name={index < step || snapshot.phase === "complete" ? "check" : index === step ? "loader" : "circle"}
              size={12} className={index === step && snapshot.phase !== "complete" ? "motion-safe:animate-spin" : undefined} />
            {/* Phones show numbered steps; the phase line below names the current one. */}
            <span aria-hidden className="tabular-nums sm:hidden">{index + 1}</span>
            <span className="max-sm:sr-only">{t(item.label)}</span>
          </li>
        ))}
      </ol>
      <p role="status" className="mt-3 font-body text-sm font-semibold leading-6 text-ink-black">
        {t(PHASE_LABEL[snapshot.phase])}
      </p>

      <div className="mt-4 grid grid-cols-2 gap-[3px] bg-ink-black p-[3px] sm:grid-cols-4">
        <Stat
          value={pageCount ? String(pageCount) : "—"}
          label={t("Pages")}
          detail={t("Target {min}–{max}", { min: String(snapshot.target_pages.min), max: String(snapshot.target_pages.max) })}
        />
        <Stat
          value={String(snapshot.panels)}
          label={t("Panels")}
          detail={pageCount ? t("{done} of {total} pages laid out", { done: String(snapshot.pages_laid_out), total: String(pageCount) }) : undefined}
        />
        <Stat
          value={`${snapshot.lettering_placed}/${snapshot.lettering_total}`}
          label={t("Lines placed")}
        />
        <Stat value={String(snapshot.beats)} label={t("Story beats")} />
      </div>

      {pageCount > 0 && (
        <>
          <ol aria-label={t("Page plan contact sheet")}
            className="mt-4 grid grid-cols-[repeat(auto-fill,minmax(26px,1fr))] gap-[5px]">
            {snapshot.pages.map((page) => (
              <PageTile key={page.page} page={page} state={tileState(snapshot, page)} />
            ))}
          </ol>
          <div aria-hidden className="mt-3 flex flex-wrap gap-x-4 gap-y-1 font-meta text-[0.62rem] font-bold text-ink-muted">
            <span className="flex items-center gap-1.5"><span className="size-2.5 border-[2px] border-ink-black bg-bristol" />{t("Laid out")}</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 border-[2px] border-ink-black bg-narrator-gold" />{t("Writing now")}</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 border-[2px] border-dashed border-ink-soft/60" />{t("Waiting")}</span>
            <span className="flex items-center gap-1.5"><span className="size-0 border-l-[8px] border-t-[8px] border-l-transparent border-t-hero-red" />{t("Peak moment")}</span>
            <span className="flex items-center gap-1.5"><span className="h-[4px] w-2.5 bg-hero-red" />{t("Page-turn reveal")}</span>
          </div>
        </>
      )}

      {(writing.length > 0 || queued.length > 0) && (
        <p className="mt-3 font-body text-xs font-semibold leading-5 text-ink-muted">
          {writing.map((batch) => t("Writing pages {range}.", { range: range(batch) })).join(" ")}
          {queued.length > 0 && ` ${t("{count, plural, one {# batch waiting.} other {# batches waiting.}}", { count: queued.length })}`}
          {snapshot.serial_transport && queued.length > 0 && ` ${t("This model writes one batch at a time, so waiting batches start as each one finishes.")}`}
        </p>
      )}
    </section>
  );
}
