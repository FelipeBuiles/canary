import { useId } from "react";
import { ChevronDown } from "lucide-react";
import { useI18n } from "../../i18n";
import type { BookAdaptation, BookPlan, ComicPage, CompletePageSummary } from "../../types/api";
import { SectionHeader } from "../composites/SectionHeader";
import { Surface } from "../ui/Surface";

const metaClass = "font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] text-ink-muted";
const copyClass = "max-w-[72ch] whitespace-pre-line font-body text-sm leading-7";
const disclosureClass = "flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-3 font-meta text-xs font-bold text-hero-red [&::-webkit-details-marker]:hidden";

const narrativeLabels: Record<string, string> = { establisher: "Establishing beat", initial: "Opening beat", prolongation: "Building tension", peak: "Peak", release: "Release", transition: "Transition" };

function PassageList({ lines }: { lines: string[] }) {
  return <ul className="space-y-3">{lines.map((line, index) => <li key={index} className={copyClass}>{line}</li>)}</ul>;
}

export function AdaptationDetails({ adaptation }: { adaptation: BookAdaptation }) {
  const { t } = useI18n();
  const prefix = useId();
  const beats = [...(adaptation.beats ?? [])].sort((left, right) => left.order - right.order);
  const spine = adaptation.treatment?.causal_spine ?? [];
  const treatmentSections = [
    ["Character arcs", adaptation.treatment?.character_arcs],
    ["Reveals", adaptation.treatment?.reveals],
    ["Consequences", adaptation.treatment?.consequences],
    ["Aftermath", adaptation.treatment?.aftermath],
    ["Relative emphasis", adaptation.treatment?.relative_emphasis],
  ] as const;

  return (
    <div className="space-y-12">
      <nav aria-label={t("Adaptation sections")} className="flex flex-wrap gap-x-6 gap-y-2 border-b border-ink-black/15 pb-4">
        <a href={`#${prefix}-treatment`} className="flex min-h-11 items-center font-meta text-sm font-bold text-hero-red underline decoration-hero-red/30 underline-offset-4 hover:decoration-hero-red focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">{t("Narrative treatment")}</a>
        <a href={`#${prefix}-beats`} className="flex min-h-11 items-center font-meta text-sm font-bold text-hero-red underline decoration-hero-red/30 underline-offset-4 hover:decoration-hero-red focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">{t("Adapted beats")}</a>
      </nav>
      <section id={`${prefix}-treatment`} tabIndex={-1} className="scroll-mt-6 focus-visible:outline-2 focus-visible:outline-hero-red">
        <SectionHeader title="Narrative treatment" description="The story’s throughline, from one turning point to the next." />
        {spine.length > 0 ? (
          <ol className="grid gap-x-8 gap-y-5 md:grid-cols-2">
            {spine.map((line, index) => (
              <li key={index} className="flex items-start gap-4">
                <span aria-hidden="true" className="shrink-0 pt-1 font-meta text-xs font-bold tabular-nums text-ink-muted">{String(index + 1).padStart(2, "0")}</span>
                <p className={copyClass}>{line}</p>
              </li>
            ))}
          </ol>
        ) : <p className={`${copyClass} text-ink-muted`}>{t("No narrative treatment is available yet.")}</p>}
        {treatmentSections.some(([, lines]) => lines && lines.length > 0) && (
          <div className="mt-7 border-t border-ink-black/15">
            {treatmentSections.filter(([, lines]) => lines && lines.length > 0).map(([label, lines]) => (
              <details key={label} className="group border-b border-ink-black/15">
                <summary className={disclosureClass}>{t(label)}<ChevronDown size={16} aria-hidden="true" className="shrink-0 group-open:rotate-180" /></summary>
                <div className="pb-5"><PassageList lines={[...(lines ?? [])]} /></div>
              </details>
            ))}
          </div>
        )}
      </section>
      <section id={`${prefix}-beats`} tabIndex={-1} className="scroll-mt-6 focus-visible:outline-2 focus-visible:outline-hero-red">
        <SectionHeader title="Adapted beats" description={`${beats.length} ${t("ordered story beats")}`} />
        {beats.length === 0 && <p className={`${copyClass} text-ink-muted`}>{t("No adapted beats are available yet.")}</p>}
        <ol className="divide-y divide-ink-black/15">
          {beats.map((beat) => {
            const lettering = (beat.lettering ?? []).filter((item) => item.text);
            const transitions = (beat.transitions ?? []).flatMap((item) => item.description ? [item.description] : []);
            const changes = (beat.appearance_changes ?? []).flatMap((item) => item.description ? [item.description] : []);
            return (
              <li key={beat.id} className="grid grid-cols-[minmax(2.5rem,max-content)_minmax(0,1fr)] gap-3 py-7 first:pt-0 sm:grid-cols-[minmax(4rem,max-content)_minmax(0,1fr)] sm:gap-6">
                <div className="pt-1"><span className="whitespace-nowrap font-display text-3xl font-black tracking-[-0.03em] text-hero-red sm:text-4xl">{String(beat.order).padStart(2, "0")}</span></div>
                <div className="min-w-0">
                  <p className="max-w-[68ch] whitespace-pre-line font-body text-base font-semibold leading-7">{beat.summary}</p>
                  {beat.narrative_function && narrativeLabels[beat.narrative_function] && <p className="mt-3 max-w-[72ch] font-body text-sm leading-6 text-ink-muted">{t(narrativeLabels[beat.narrative_function])}</p>}
                  {(lettering.length > 0 || transitions.length > 0 || changes.length > 0) && (
                    <details className="group mt-3 border-t border-ink-black/10">
                      <summary className={disclosureClass}>{t("Lettering & story details")}<ChevronDown size={16} aria-hidden="true" className="shrink-0 group-open:rotate-180" /></summary>
                      <div className="space-y-5 pb-2">
                        {lettering.length > 0 && <div><h3 className={`${metaClass} mb-3`}>{t("Lettering")}</h3><ul className="space-y-3">{lettering.map((item) => <li key={item.id} className="max-w-[72ch] bg-surface-container px-4 py-3 font-body text-sm leading-6 whitespace-pre-line">{item.text}</li>)}</ul></div>}
                        {transitions.length > 0 && <div><h3 className={`${metaClass} mb-2`}>{t("Transitions")}</h3><PassageList lines={transitions} /></div>}
                        {changes.length > 0 && <div><h3 className={`${metaClass} mb-2`}>{t("Appearance changes")}</h3><PassageList lines={changes} /></div>}
                      </div>
                    </details>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}

const densityLabels: Record<ComicPage["density_intent"], string> = { sparse: "Sparse", standard: "Standard", dense: "Dense" };
const turnLabels: Record<ComicPage["page_turn_role"], string> = { none: "", setup: "Setup", reveal: "Reveal", cliffhanger: "Cliffhanger", release: "Release", transition: "Transition" };
const spreadLabels: Record<ComicPage["spread_role"], string> = { single: "Single page", left: "Left page", right: "Right page", spread: "Full spread" };

export function PagePlanDetails({ plan, pages, detailsLoading, detailsError }: {
  plan: BookPlan;
  pages: CompletePageSummary[] | undefined;
  detailsLoading: boolean;
  detailsError: unknown;
}) {
  const { t } = useI18n();
  const prefix = useId();
  const plannedPages = plan.pages ?? [];
  const detailsByNumber = new Map(pages?.map((item) => [item.page.page_number, item.page]));
  return (
    <div className="space-y-12">
      <section>
        <SectionHeader title="Book rhythm" />
        <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_auto] md:gap-10">
          <p className="max-w-[64ch] whitespace-pre-line font-body text-base leading-8">{plan.rhythm_summary || t("No book rhythm summary is available yet.")}</p>
          <Surface tone="container" border="soft" shadow="none" padding="md" className="self-start md:min-w-44">
            <p className={metaClass}>{t("Page budget")}</p>
            <p className="mt-2 font-display text-3xl font-black tracking-[-0.04em]">{plan.target_page_min === plan.target_page_max ? plan.target_page_min : `${plan.target_page_min}–${plan.target_page_max}`}</p>
            <p className="mt-1 font-body text-xs text-ink-muted">{t("Target pages")}</p>
          </Surface>
        </div>
      </section>
      <section>
        <SectionHeader title="Planned pages" description={`${plannedPages.length} ${t("planned pages")}`} />
        {plannedPages.length > 0 && (
          <nav aria-label={t("Jump to a planned page")} className="mb-7">
            <p className={`${metaClass} mb-3`}>{t("Jump to page")}</p>
            <div className="flex flex-wrap gap-2">
              {plannedPages.map((item) => <a key={item.page_number} href={`#${prefix}-planned-page-${item.page_number}`} aria-label={t("Jump to page {number}").replace("{number}", String(item.page_number))} className="flex min-h-11 min-w-11 items-center justify-center border border-ink-black/20 bg-bristol px-3 font-meta text-sm font-bold hover:border-ink-black hover:bg-narrator-gold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">{item.page_number}</a>)}
            </div>
          </nav>
        )}
        {plannedPages.length === 0 && <p className={`${copyClass} text-ink-muted`}>{t("The page plan is not ready yet.")}</p>}
        <ol className="space-y-4">
          {plannedPages.map((planned) => {
            const page = detailsByNumber.get(planned.page_number);
            return <li key={planned.page_number} id={`${prefix}-planned-page-${planned.page_number}`} tabIndex={-1} className="scroll-mt-6 focus-visible:outline-2 focus-visible:outline-hero-red">
              <Surface border="soft" shadow="none" padding="none" className="grid sm:grid-cols-[minmax(7rem,max-content)_minmax(0,1fr)]">
                <div className="flex items-center gap-3 border-b border-ink-black/10 bg-surface-container p-4 sm:block sm:border-b-0 sm:border-r sm:p-5">
                  <h3 className={metaClass}>{t("Page")} <span className="ml-2 whitespace-nowrap font-display text-3xl font-black tracking-[-0.04em] text-ink-black sm:ml-0 sm:mt-2 sm:block sm:text-4xl">{String(planned.page_number).padStart(2, "0")}</span></h3>
                </div>
                <div className="min-w-0 p-4 md:p-6">
                  {page ? <>
                    <h4 className={metaClass}>{t("Layout")}</h4>
                    <p className="mt-2 max-w-[72ch] whitespace-pre-line font-body text-base font-semibold leading-7">{page.layout_intent || t("No layout notes are available.")}</p>
                    {page.rhythm_intent && <div className="mt-4"><h4 className={metaClass}>{t("Rhythm")}</h4><p className="mt-2 max-w-[72ch] whitespace-pre-line font-body text-sm leading-7 text-ink-muted">{page.rhythm_intent}</p></div>}
                    <dl className="mt-5 flex flex-wrap gap-x-6 gap-y-3 border-t border-ink-black/10 pt-4">
                      {page.density_intent && <div><dt className={metaClass}>{t("Density")}</dt><dd className="mt-1 font-body text-sm">{t(densityLabels[page.density_intent])}</dd></div>}
                      {page.spread_role && <div><dt className={metaClass}>{t("Placement")}</dt><dd className="mt-1 font-body text-sm">{t(spreadLabels[page.spread_role])}</dd></div>}
                      {page.page_turn_role && page.page_turn_role !== "none" && <div><dt className={metaClass}>{t("Page turn")}</dt><dd className="mt-1 font-body text-sm">{t(turnLabels[page.page_turn_role])}</dd></div>}
                    </dl>
                  </> : <p className={`${copyClass} text-ink-muted`} role={detailsLoading ? "status" : undefined}>{detailsLoading ? t("Loading page details…") : detailsError ? t("Page details are not available right now.") : t("Details for this planned page are not available yet.")}</p>}
                </div>
              </Surface>
            </li>;
          })}
        </ol>
      </section>
    </div>
  );
}
