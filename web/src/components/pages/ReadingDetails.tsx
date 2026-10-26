import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ChevronDown, ChevronLeft, ChevronRight, MapPin, Package } from "lucide-react";
import { useI18n } from "../../i18n";
import { PlanSketch } from "./PlanSketch";
import { cn } from "../../lib/cn";
import { pageDisplayImage } from "../../lib/pageState";
import {
  ANGLE_LABELS, ROLE_LABELS, SHOT_LABELS, beatPages, entityLabel, layoutSummary, panelsInOrder, withEntityNames,
  type EntityRef,
} from "../../lib/readingDocs";
import type { BookAdaptation, BookPlan, ComicPage, CompletePageSummary, EditorialIssue, PageContent } from "../../types/api";

type Names = Map<string, EntityRef>;

const narrativeLabels: Record<string, string> = { establisher: "Establishing beat", initial: "Opening beat", prolongation: "Building tension", peak: "Peak", release: "Release", transition: "Transition" };
const densityLabels: Record<ComicPage["density_intent"], string> = { sparse: "Sparse", standard: "Standard", dense: "Dense" };
const turnLabels: Record<ComicPage["page_turn_role"], string> = { none: "", setup: "Setup", reveal: "Reveal", cliffhanger: "Cliffhanger", release: "Release", transition: "Transition" };
const spreadLabels: Record<ComicPage["spread_role"], string> = { single: "Single page", left: "Left page", right: "Right page", spread: "Full spread" };

const eyebrow = "font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted";
const pad = (value: number) => String(value).padStart(2, "0");

function pageImage(project: string, item: CompletePageSummary | undefined, size: "reader" | "thumbnail") {
  const revision = item?.active_render?.render.revision;
  if (!item || !revision) return null;
  return pageDisplayImage(project, {
    pageNumber: item.page.page_number, revision,
    hybrid: item.lettering_mode === "hybrid", letteringRevision: item.lettering_revision,
  }, size);
}

/** Canonical copy, set the way it reads on the page: captions boxed, balloons rounded, effects loud. */
export function LetteringLine({ kind, text, speaker }: { kind?: string; text: string; speaker?: string | null }) {
  if (kind === "sfx") {
    return <p className="font-display text-lg font-black uppercase leading-tight tracking-[-0.01em] text-hero-red">{text}</p>;
  }
  if (kind === "caption") {
    return <p className="border border-ink-black/70 bg-chip-gold px-3 py-2 font-body text-sm leading-6 whitespace-pre-line">{text}</p>;
  }
  return (
    <div>
      {speaker && <p className="mb-1 font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-ink-soft">{speaker}</p>}
      <p className={cn("rounded-[1.1rem] border bg-bristol px-3.5 py-2 font-body text-sm leading-6 whitespace-pre-line",
        kind === "thought" ? "border-dashed border-ink-black/50 italic" : "border-ink-black/70")}>{text}</p>
    </div>
  );
}

export function EditorialNotes({ issues }: { issues: EditorialIssue[] }) {
  const { t } = useI18n();
  return (
    <ul className="max-h-[60vh] space-y-3 overflow-y-auto">
      {issues.map((issue) => (
        <li key={issue.id} className="border-b border-ink-black/10 pb-3 last:border-0 last:pb-0">
          <p className="font-body text-sm leading-6">{issue.message}</p>
          {issue.evidence.map((line, index) => <p key={index} className="mt-1 font-body text-xs leading-5 text-ink-muted">{line}</p>)}
        </li>
      ))}
      <li className="font-body text-xs text-ink-muted">{t("These suggestions don't block anything.")}</li>
    </ul>
  );
}

/* ------------------------------------------------------------------ */
/* Adaptation: the story's beats under the page each one lands on.     */
/* ------------------------------------------------------------------ */

export function AdaptationDetails({ project, adaptation, pages, focusBeat, onOpenPage }: {
  project: string;
  adaptation: BookAdaptation;
  pages: CompletePageSummary[] | undefined;
  focusBeat?: string | null;
  onOpenPage: (page: number) => void;
}) {
  const { t } = useI18n();
  const beats = useMemo(() => [...(adaptation.beats ?? [])].sort((a, b) => a.order - b.order), [adaptation.beats]);
  const placed = useMemo(() => beatPages(pages), [pages]);
  const byNumber = useMemo(() => new Map(pages?.map((item) => [item.page.page_number, item])), [pages]);
  const groups = useMemo(() => {
    const out: Array<{ page: number | null; beats: typeof beats }> = [];
    for (const beat of beats) {
      const page = placed.get(beat.id) ?? null;
      const last = out.at(-1);
      if (last && last.page === page) last.beats.push(beat);
      else out.push({ page, beats: [beat] });
    }
    return out;
  }, [beats, placed]);
  const spine = adaptation.treatment?.causal_spine ?? [];
  const treatment = ([
    ["Character arcs", adaptation.treatment?.character_arcs],
    ["Reveals", adaptation.treatment?.reveals],
    ["Consequences", adaptation.treatment?.consequences],
    ["Aftermath", adaptation.treatment?.aftermath],
    ["Relative emphasis", adaptation.treatment?.relative_emphasis],
  ] as const).filter(([, lines]) => lines && lines.length > 0);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!focusBeat) return;
    const target = scroller.current?.querySelector<HTMLElement>(`[data-beat="${CSS.escape(focusBeat)}"]`);
    target?.scrollIntoView?.({ block: "center" });
    target?.focus({ preventScroll: true });
  }, [focusBeat]);

  const jumpTo = (page: number) => scroller.current?.querySelector<HTMLElement>(`[data-beat-page="${page}"]`)?.scrollIntoView?.({ block: "start", behavior: "smooth" });

  return (
    <div className="flex min-h-0 flex-1 flex-col studio-desktop:flex-row">
      <aside aria-label={t("Throughline")} className="relative shrink-0 border-b border-ink-black/10 bg-bristol px-5 py-6 studio-desktop:w-[21rem] studio-desktop:overflow-y-auto studio-desktop:border-b-0 studio-desktop:border-r">
        <h2 className="font-display text-lg font-black uppercase tracking-[-0.02em]">{t("Throughline")}</h2>
        {spine.length > 0 ? (
          <ol className="relative mt-4 space-y-4 before:absolute before:bottom-2 before:left-[0.6875rem] before:top-2 before:w-px before:bg-ink-black/20">
            {spine.map((line, index) => (
              <li key={index} className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3">
                <span aria-hidden="true" className="relative z-10 flex h-6 w-6 items-center justify-center border border-ink-black bg-narrator-gold font-meta text-[0.6875rem] font-bold tabular-nums">{index + 1}</span>
                <p className="font-body text-sm leading-6">{line}</p>
              </li>
            ))}
          </ol>
        ) : <p className="mt-3 font-body text-sm text-ink-muted">{t("No narrative treatment is available yet.")}</p>}

        {treatment.length > 0 && (
          <div className="mt-6 border-t border-ink-black/12">
            {treatment.map(([label, lines]) => (
              <details key={label} className="group border-b border-ink-black/12">
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 font-meta text-[0.8125rem] font-semibold [&::-webkit-details-marker]:hidden">
                  {t(label)}<span className="ml-auto font-normal text-ink-muted">{lines!.length}</span>
                  <ChevronDown size={15} aria-hidden="true" className="shrink-0 text-ink-muted group-open:rotate-180" />
                </summary>
                <ul className="space-y-2.5 pb-4">{lines!.map((line, index) => <li key={index} className="font-body text-sm leading-6">{line}</li>)}</ul>
              </details>
            ))}
          </div>
        )}

        {groups.some((group) => group.page !== null) && (
          <nav aria-label={t("Jump to page")} className="mt-6">
            <p className={eyebrow}>{t("Pages")}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {groups.filter((group) => group.page !== null).map((group) => (
                <button key={group.page} type="button" onClick={() => jumpTo(group.page!)}
                  aria-label={t("Jump to page {number}", { number: String(group.page) })}
                  className="flex h-8 min-w-8 items-center justify-center border border-ink-black/20 px-1.5 font-meta text-xs font-semibold tabular-nums hover:border-ink-black hover:bg-narrator-gold">
                  {group.page}
                </button>
              ))}
            </div>
          </nav>
        )}
      </aside>

      <div ref={scroller} className="benday-paper relative min-w-0 flex-1 px-3 py-5 sm:px-6 sm:py-7 studio-desktop:overflow-y-auto">
        <article className="mx-auto max-w-[48rem] border border-ink-black/14 bg-bristol shadow-[0_18px_40px_-24px_rgba(27,28,21,0.35)]">
          {beats.length === 0 && <p className="px-6 py-10 font-body text-sm text-ink-muted">{t("No adapted beats are available yet.")}</p>}
          {groups.map((group, index) => {
            const item = group.page !== null ? byNumber.get(group.page) : undefined;
            const thumb = pageImage(project, item, "thumbnail");
            return (
              <section key={`${group.page}-${index}`} data-beat-page={group.page ?? undefined} className="scroll-mt-4 border-b border-ink-black/12 last:border-0">
                {/* Before Plan has placed any beat, the beats read as one list. */}
                {placed.size > 0 && <header className="flex items-center gap-4 bg-surface-container/60 px-5 py-3 sm:px-8">
                  {group.page !== null ? (
                    <button type="button" onClick={() => onOpenPage(group.page!)} aria-label={t("Open page {number} in the plan", { number: String(group.page) })}
                      className="group/page flex min-w-0 flex-1 items-center gap-4 text-left">
                      <span className="flex h-14 w-10 shrink-0 items-center justify-center overflow-hidden border border-ink-black/30 bg-pulp-paper benday-paper">
                        {thumb ? <img src={thumb} alt="" loading="lazy" className="h-full w-full object-cover" />
                          : item && <PlanSketch page={item.page} size="thumb" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block font-display text-base font-black uppercase tracking-[-0.01em]">{t("Page {number}", { number: String(group.page) })}</span>
                        {item?.page.rhythm_intent && <span className="block truncate font-body text-xs text-ink-muted">{item.page.rhythm_intent}</span>}
                      </span>
                      <span className="hidden shrink-0 items-center gap-1 font-meta text-xs font-medium text-ink-soft group-hover/page:text-ink-black sm:inline-flex">{t("Open in plan")}<ArrowRight size={13} aria-hidden="true" /></span>
                    </button>
                  ) : <span className="font-display text-base font-black uppercase">{t("Not placed on a page")}</span>}
                </header>}
                <ol>
                  {group.beats.map((beat) => {
                    const lettering = (beat.lettering ?? []).filter((line) => line.text) as Array<{ id: string; kind?: string; text: string; speaker?: string | null }>;
                    const transitions = (beat.transitions ?? []).flatMap((line) => line.description ? [line.description] : []);
                    const changes = (beat.appearance_changes ?? []).flatMap((line) => line.description ? [line.description] : []);
                    const role = beat.narrative_function ? narrativeLabels[beat.narrative_function] : undefined;
                    return (
                      <li key={beat.id} data-beat={beat.id} tabIndex={-1}
                        className={cn("grid grid-cols-[2rem_minmax(0,1fr)] gap-3 px-5 py-5 outline-none sm:grid-cols-[2.5rem_minmax(0,1fr)] sm:gap-4 sm:px-8",
                          focusBeat === beat.id && "bg-chip-gold/60 shadow-[inset_3px_0_0_var(--color-narrator-gold)]")}>
                        <span className="pt-0.5 font-meta text-xs font-bold tabular-nums text-ink-muted">{pad(beat.order)}</span>
                        <div className="min-w-0 space-y-3">
                          <p className="font-body text-[0.9375rem] leading-7 whitespace-pre-line">{beat.summary}</p>
                          {role && <p className="font-meta text-[0.6875rem] font-medium uppercase tracking-[0.08em] text-ink-muted">{t(role)}</p>}
                          {lettering.length > 0 && (
                            <div aria-label={t("Lettering")} role="group" className="space-y-2.5">
                              {lettering.map((line) => <LetteringLine key={line.id} kind={line.kind} text={line.text} speaker={line.speaker} />)}
                            </div>
                          )}
                          {transitions.map((line, at) => <p key={`t${at}`} className="flex gap-2 font-body text-xs leading-5 text-ink-muted"><ArrowRight size={13} aria-hidden="true" className="mt-0.5 shrink-0" /><span><span className="sr-only">{t("Transition")}: </span>{line}</span></p>)}
                          {changes.map((line, at) => <p key={`c${at}`} className="flex gap-2 font-body text-xs leading-5 text-ink-muted"><span aria-hidden="true" className="mt-1.5 h-1.5 w-1.5 shrink-0 bg-narrator-gold" /><span><span className="sr-only">{t("Appearance change")}: </span>{line}</span></p>)}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </section>
            );
          })}
        </article>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Page plan: a storyboard, one page at a time.                        */
/* ------------------------------------------------------------------ */

export function PagePlanDetails({ project, plan, pages, names, detailsLoading, detailsError, page, onPage, onOpenBeat }: {
  project: string;
  plan: BookPlan;
  pages: CompletePageSummary[] | undefined;
  names: Names;
  detailsLoading: boolean;
  detailsError: unknown;
  page: number | null;
  onPage: (page: number) => void;
  onOpenBeat: (beat: string) => void;
}) {
  const { t } = useI18n();
  // The plan's own order is canonical; never re-sort it.
  const planned = plan.pages ?? [];
  const byNumber = useMemo(() => new Map(pages?.map((item) => [item.page.page_number, item])), [pages]);
  const current = page && planned.some((item) => item.page_number === page) ? page : planned[0]?.page_number ?? null;
  const index = planned.findIndex((item) => item.page_number === current);
  const item = current !== null ? byNumber.get(current) : undefined;
  const list = useRef<HTMLElement>(null);
  const [rhythmOpen, setRhythmOpen] = useState(false);

  const step = (delta: number) => {
    const next = planned[index + delta];
    if (next) onPage(next.page_number);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (target instanceof Element && target.closest("input, textarea, select, [contenteditable=true], [role=dialog]")) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
      if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-plan-page="${current}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [current]);

  if (planned.length === 0) return <p className="px-6 py-10 font-body text-sm text-ink-muted">{t("The page plan is not ready yet.")}</p>;
  const image = pageImage(project, item, "reader");
  const missing = detailsLoading ? t("Loading page details…") : detailsError ? t("Page details are not available right now.") : t("Details for this planned page are not available yet.");

  return (
    <div className="flex min-h-0 flex-1 flex-col studio-desktop:flex-row">
      <nav ref={list} aria-label={t("Planned pages")} className="relative hidden w-60 shrink-0 overflow-y-auto border-r border-ink-black/10 bg-bristol studio-desktop:block">
        {plan.rhythm_summary && (
          <div className="border-b border-ink-black/10 px-4 py-4">
            <p className={eyebrow}>{t("Book rhythm")}</p>
            <p className={cn("mt-1.5 font-body text-[0.8125rem] leading-5 text-ink-soft", !rhythmOpen && "line-clamp-4")}>{plan.rhythm_summary}</p>
            <button type="button" onClick={() => setRhythmOpen((open) => !open)} className="mt-1 font-meta text-xs font-medium underline decoration-ink-black/30 underline-offset-2 hover:decoration-ink-black">
              {rhythmOpen ? t("Less") : t("More")}
            </button>
          </div>
        )}
        <ol className="py-2">
          {planned.map(({ page_number }) => {
            const entry = byNumber.get(page_number);
            const thumb = pageImage(project, entry, "thumbnail");
            const turn = entry?.page.page_turn_role ? turnLabels[entry.page.page_turn_role] : "";
            const active = page_number === current;
            return (
              <li key={page_number}>
                <button type="button" data-plan-page={page_number} aria-current={active ? "page" : undefined} onClick={() => onPage(page_number)}
                  className={cn("grid w-full grid-cols-[2.25rem_minmax(0,1fr)] gap-3 border-l-[3px] px-3 py-2.5 text-left transition-colors",
                    active ? "border-hero-red bg-ink-black text-pulp-paper" : "border-transparent hover:bg-surface-container")}>
                  <span className={cn("flex h-12 w-9 items-center justify-center overflow-hidden border benday-paper", active ? "border-pulp-paper/40" : "border-ink-black/25")}>
                    {thumb ? <img src={thumb} alt="" loading="lazy" className="h-full w-full object-cover" />
                      : entry && <PlanSketch page={entry.page} size="thumb" />}
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-baseline gap-2 font-meta text-xs font-bold">
                      {t("Page {number}", { number: String(page_number) })}
                      {turn && <span className={cn("font-medium", active ? "text-narrator-gold" : "text-hero-red")}>{t(turn)}</span>}
                    </span>
                    <span className={cn("mt-0.5 block font-body text-xs leading-[1.35] line-clamp-2", active ? "text-pulp-paper/75" : "text-ink-muted")}>{entry?.page.rhythm_intent ?? ""}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      <div className="benday-ink relative flex min-h-[26rem] flex-1 items-center justify-center bg-ink-black px-14 py-6 studio-desktop:min-h-0">
        {image ? (
          <img key={image} src={image} alt={t("Page {number}", { number: String(current) })}
            className="max-h-full max-w-full object-contain shadow-[0_24px_60px_-20px_rgba(0,0,0,0.75)] studio-desktop:max-h-[calc(100%-1rem)]" />
        ) : item && item.page.content.length > 0 ? (
          <div className="flex h-full min-h-[24rem] w-full flex-col items-center gap-3 pb-5">
            <p className="inline-flex shrink-0 items-center gap-2 font-meta text-xs text-pulp-paper/70">
              <span aria-hidden="true" className="size-2 border border-pulp-paper/60" />
              {t("Not drawn yet · planned panels in reading order")}
            </p>
            <div className="flex min-h-0 w-full flex-1 items-center justify-center"><PlanSketch page={item.page} names={names} size="stage" /></div>
          </div>
        ) : (
          <div className="flex aspect-[2/3] h-[min(70%,32rem)] flex-col items-center justify-center gap-3 border border-dashed border-pulp-paper/30 text-center">
            <p className="font-display text-lg font-black uppercase text-pulp-paper">{t("Not drawn yet")}</p>
          </div>
        )}
        <button type="button" onClick={() => step(-1)} disabled={index <= 0} aria-label={t("Previous page")}
          className="absolute left-3 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center border border-pulp-paper/25 text-pulp-paper hover:bg-pulp-paper/10 disabled:opacity-30"><ChevronLeft size={20} aria-hidden="true" /></button>
        <button type="button" onClick={() => step(1)} disabled={index >= planned.length - 1} aria-label={t("Next page")}
          className="absolute right-3 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center border border-pulp-paper/25 text-pulp-paper hover:bg-pulp-paper/10 disabled:opacity-30"><ChevronRight size={20} aria-hidden="true" /></button>
        <p className="absolute bottom-3 left-1/2 -translate-x-1/2 font-meta text-xs tabular-nums text-pulp-paper/60">{index + 1} / {planned.length}</p>
      </div>

      <aside aria-label={t("Page {number}", { number: String(current) })} className="relative shrink-0 border-l border-ink-black/10 bg-bristol studio-desktop:w-[27rem] studio-desktop:overflow-y-auto">
        <div className="space-y-4 px-6 pb-5 pt-6">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-display text-[1.625rem] font-black uppercase leading-none tracking-[-0.03em]">{t("Page {number}", { number: String(current) })}</h2>
            {item && <>
              {item.page.page_turn_role !== "none" && <span className="border border-hero-red/40 bg-chip-red px-1.5 py-0.5 font-meta text-[0.6875rem] font-semibold text-status-blocked-text">{t(turnLabels[item.page.page_turn_role])}</span>}
              <span className="border border-ink-black/15 px-1.5 py-0.5 font-meta text-[0.6875rem] text-ink-soft">{t("{density} density", { density: t(densityLabels[item.page.density_intent]) })}</span>
              <span className="border border-ink-black/15 px-1.5 py-0.5 font-meta text-[0.6875rem] text-ink-soft">{t(spreadLabels[item.page.spread_role])}</span>
            </>}
          </div>
          {item ? <>
            {item.page.rhythm_intent && <p className="font-body text-base font-semibold leading-6">{item.page.rhythm_intent}</p>}
            {item.page.layout_intent && <p className="font-body text-sm leading-6 text-ink-soft whitespace-pre-line">{layoutSummary(item.page.layout_intent)}</p>}
          </> : <p role={detailsLoading ? "status" : undefined} className="font-body text-sm text-ink-muted">{missing}</p>}
        </div>
        {item && (
          <section aria-label={t("Panels")} className="border-t border-ink-black/10 px-6 pb-8 pt-5">
            <p className={eyebrow}>{t("{count, plural, one {# panel} other {# panels}}", { count: item.page.content.length })}</p>
            <ol className="mt-3 space-y-3">
              {panelsInOrder(item.page.content, item.page.reading_order).map((panel, at) => (
                <PanelCard key={panel.id} panel={panel} number={at + 1} names={names} onOpenBeat={onOpenBeat} />
              ))}
            </ol>
          </section>
        )}
      </aside>

      <div className="flex items-center justify-center gap-2 border-t border-ink-black/10 bg-bristol px-4 py-3 studio-desktop:hidden">
        <label className="font-meta text-xs text-ink-muted" htmlFor="plan-page-select">{t("Page")}</label>
        <select id="plan-page-select" value={current ?? ""} onChange={(event) => onPage(Number(event.target.value))} className="h-9 border border-ink-black/25 bg-bristol px-2 font-meta text-sm">
          {planned.map(({ page_number }) => <option key={page_number} value={page_number}>{page_number}</option>)}
        </select>
      </div>
    </div>
  );
}

function PanelCard({ panel, number, names, onOpenBeat }: { panel: PageContent; number: number; names: Names; onOpenBeat: (beat: string) => void }) {
  const { t } = useI18n();
  const role = ROLE_LABELS[panel.panel_role];
  const camera = panel.camera ? [t(SHOT_LABELS[panel.camera.shot]), t(ANGLE_LABELS[panel.camera.angle])].join(" · ") : "";
  const people = panel.entity_ids.filter((id) => names.get(id)?.kind !== "place" && names.get(id)?.kind !== "prop");
  const places = panel.entity_ids.filter((id) => names.get(id)?.kind === "place");
  const props = panel.entity_ids.filter((id) => names.get(id)?.kind === "prop");
  const lettering = panel.lettering.filter((line) => line.text);
  return (
    <li className="border border-ink-black/12 bg-pulp-paper/40">
      <div className="flex items-center gap-2.5 border-b border-ink-black/8 px-3.5 py-2">
        <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center border border-ink-black bg-narrator-gold font-meta text-[0.6875rem] font-bold tabular-nums">{number}</span>
        <h3 className="min-w-0 flex-1 truncate font-meta text-xs font-semibold">
          <span className="sr-only">{t("Panel {number}", { number: String(number) })}: </span>
          {[role ? t(role) : "", camera].filter(Boolean).join(" · ") || t("Panel {number}", { number: String(number) })}
        </h3>
        {panel.beat_ids.length > 0 && (
          <button type="button" onClick={() => onOpenBeat(panel.beat_ids[0])} className="shrink-0 font-meta text-[0.6875rem] text-ink-muted underline decoration-ink-black/25 underline-offset-2 hover:text-ink-black">
            {t("Beat {number}", { number: String(Number(panel.beat_ids[0].replace(/\D/g, "")) || 1) })}
          </button>
        )}
      </div>
      <div className="space-y-3 px-3.5 py-3">
        <p className="font-body text-sm leading-6">{withEntityNames(names, panel.visual_intent)}</p>
        {(people.length > 0 || places.length > 0 || props.length > 0) && (
          <ul aria-label={t("In this panel")} className="flex flex-wrap gap-1.5">
            {places.map((id) => <li key={id} className="inline-flex items-center gap-1 border border-ink-black/15 bg-bristol px-1.5 py-0.5 font-meta text-[0.6875rem] text-ink-soft"><MapPin size={11} aria-hidden="true" />{entityLabel(names, id)}</li>)}
            {people.map((id) => <li key={id} className="border border-ink-black/15 bg-bristol px-1.5 py-0.5 font-meta text-[0.6875rem] font-medium">{entityLabel(names, id)}</li>)}
            {props.map((id) => <li key={id} className="inline-flex items-center gap-1 border border-ink-black/15 bg-bristol px-1.5 py-0.5 font-meta text-[0.6875rem] text-ink-soft"><Package size={11} aria-hidden="true" />{entityLabel(names, id)}</li>)}
          </ul>
        )}
        {lettering.length > 0 && <div role="group" aria-label={t("Lettering")} className="space-y-2">{lettering.map((line) => <LetteringLine key={line.id} kind={line.kind} text={line.text} speaker={line.speaker} />)}</div>}
        {panel.acting.length > 0 && (
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-1 font-meta text-xs font-medium text-ink-soft hover:text-ink-black [&::-webkit-details-marker]:hidden">
              {t("Acting")}<ChevronDown size={13} aria-hidden="true" className="group-open:rotate-180" />
            </summary>
            <ul className="mt-2 space-y-2">
              {panel.acting.map((act) => (
                <li key={act.entity_id} className="font-body text-xs leading-5 text-ink-soft">
                  <span className="font-semibold text-ink-black">{entityLabel(names, act.entity_id)}</span>
                  {[act.expression, act.gesture, act.gaze && t("looking at {target}", { target: withEntityNames(names, act.gaze) })].filter(Boolean).map((part) => ` · ${part}`)}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </li>
  );
}
