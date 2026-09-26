import { useId } from "react";
import { ChevronDown } from "lucide-react";
import { useI18n } from "../../i18n";
import type { BookAdaptation, BookPlan, ComicPage, CompletePageSummary, EditorialIssue } from "../../types/api";
import { SectionHeader } from "../composites/SectionHeader";


const metaClass = "font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] text-ink-muted";
const copyClass = "whitespace-pre-line font-body text-sm leading-7";
const disclosureClass = "flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-3 font-meta text-xs font-bold text-hero-red [&::-webkit-details-marker]:hidden";

const narrativeLabels: Record<string, string> = { establisher: "Establishing beat", initial: "Opening beat", prolongation: "Building tension", peak: "Peak", release: "Release", transition: "Transition" };

function PassageList({ lines }: { lines: string[] }) {
  return <ul className="space-y-3">{lines.map((line, index) => <li key={index} className={copyClass}>{line}</li>)}</ul>;
}

function EditorialNotes({ issues }: { issues: EditorialIssue[] }) {
  const { t } = useI18n();
  if (issues.length === 0) return null;
  return <details className="group border-t border-ink-black/15">
    <summary className={disclosureClass}>{t("Optional editorial notes")} · {issues.length}<ChevronDown size={16} aria-hidden="true" /></summary>
    <p className={`${copyClass} mb-4 text-ink-muted`}>{t("These suggestions do not block completion or start another generation.")}</p>
    {issues.map((issue) => <details key={issue.id} className="border-b border-ink-black/15">
      <summary className={disclosureClass}>{issue.evidence[0] ?? issue.message}<ChevronDown size={16} aria-hidden="true" /></summary>
      <div className="pb-4"><PassageList lines={issue.evidence.slice(1)} /></div>
    </details>)}
  </details>;
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
    <div className="space-y-8">
      <section id={`${prefix}-treatment`} tabIndex={-1} className="scroll-mt-40 md:scroll-mt-28 focus-visible:outline-2 focus-visible:outline-hero-red">
        <details className="group/treatment bg-surface-container px-4 sm:px-5">
          <summary className={`${disclosureClass} text-ink-black`}>
            <span>{t("Narrative treatment")}<span className="mt-1 block font-body text-sm font-normal text-ink-muted">{t("The story’s throughline, from one turning point to the next.")}</span></span>
            <ChevronDown size={18} aria-hidden="true" className="shrink-0 group-open/treatment:rotate-180" />
          </summary>
          <div className="pb-5 pt-3">
        {spine.length > 0 ? (
          <ol className="space-y-5">
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
          </div>
        </details>
      </section>
      <section id={`${prefix}-beats`} tabIndex={-1} className="scroll-mt-40 md:scroll-mt-28 focus-visible:outline-2 focus-visible:outline-hero-red">
        <SectionHeader title="Adapted beats" description={`${beats.length} ${t("ordered story beats")} · ${t("Open a beat for the full text and lettering.")}`} />
        {beats.length === 0 && <p className={`${copyClass} text-ink-muted`}>{t("No adapted beats are available yet.")}</p>}
        <ol className="divide-y divide-ink-black/15">
          {beats.map((beat) => {
            const lettering = (beat.lettering ?? []).filter((item) => item.text);
            const transitions = (beat.transitions ?? []).flatMap((item) => item.description ? [item.description] : []);
            const changes = (beat.appearance_changes ?? []).flatMap((item) => item.description ? [item.description] : []);
            return (
              <li key={beat.id}>
                <details className="group/beat">
                  <summary className="grid min-h-11 cursor-pointer list-none grid-cols-[2.5rem_minmax(0,1fr)_1rem] items-start gap-3 py-5 hover:bg-surface-container/60 sm:gap-5 [&::-webkit-details-marker]:hidden">
                    <span className="pt-0.5 font-meta text-sm font-bold tabular-nums text-ink-muted">{String(beat.order).padStart(2, "0")}</span>
                    <span className="min-w-0">
                      <span className="whitespace-pre-line font-body text-sm leading-6 line-clamp-2 group-open/beat:line-clamp-none">{beat.summary}</span>
                      {beat.narrative_function && narrativeLabels[beat.narrative_function] && <span className="mt-2 block font-meta text-xs text-ink-muted">{t(narrativeLabels[beat.narrative_function])}</span>}
                    </span>
                    <ChevronDown size={16} aria-hidden="true" className="mt-1 shrink-0 group-open/beat:rotate-180" />
                  </summary>
                  <div className="pb-5 pl-13 sm:pl-15">
                  {(lettering.length > 0 || transitions.length > 0 || changes.length > 0) && (
                    <section aria-label={t("Lettering & story details")}>
                      <div className="space-y-5 pb-2">
                        {lettering.length > 0 && <div><h3 className={`${metaClass} mb-3`}>{t("Lettering")}</h3><ul className="space-y-3">{lettering.map((item) => <li key={item.id} className="bg-surface-container px-4 py-3 font-body text-sm leading-6 whitespace-pre-line">{item.text}</li>)}</ul></div>}
                        {transitions.length > 0 && <div><h3 className={`${metaClass} mb-2`}>{t("Transitions")}</h3><PassageList lines={transitions} /></div>}
                        {changes.length > 0 && <div><h3 className={`${metaClass} mb-2`}>{t("Appearance changes")}</h3><PassageList lines={changes} /></div>}
                      </div>
                    </section>
                  )}
                  </div>
                </details>
              </li>
            );
          })}
        </ol>
      </section>
      <EditorialNotes issues={adaptation.editorial_issues} />
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
    <div className="space-y-8">
      <details className="group/rhythm bg-surface-container px-4 sm:px-5">
        <summary className={`${disclosureClass} text-ink-black`}>
          <span>{t("Book rhythm")}<span className="mt-1 block font-body text-sm font-normal text-ink-muted">{t("Target pages")}: {plan.target_page_min === plan.target_page_max ? plan.target_page_min : `${plan.target_page_min}–${plan.target_page_max}`}</span></span>
          <ChevronDown size={18} aria-hidden="true" className="shrink-0 group-open/rhythm:rotate-180" />
        </summary>
        <p className={`${copyClass} pb-5 pt-2`}>{plan.rhythm_summary || t("No book rhythm summary is available yet.")}</p>
      </details>
      <section>
        <SectionHeader title="Planned pages" description={`${plannedPages.length} ${t("planned pages")} · ${t("Scan the pacing. Open a page for layout and staging.")}`} />
        {plannedPages.length > 0 && (
          <nav aria-label={t("Jump to a planned page")} className="mb-7">
            <p className={`${metaClass} mb-3`}>{t("Jump to page")}</p>
            <div className="flex flex-wrap gap-2">
              {plannedPages.map((item) => <a key={item.page_number} href={`#${prefix}-planned-page-${item.page_number}`} aria-label={t("Jump to page {number}", { number: String(item.page_number) })} className="flex min-h-11 min-w-11 items-center justify-center border border-ink-black/20 bg-bristol px-3 font-meta text-sm font-bold hover:border-ink-black hover:bg-narrator-gold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">{item.page_number}</a>)}
            </div>
          </nav>
        )}
        {plannedPages.length === 0 && <p className={`${copyClass} text-ink-muted`}>{t("The page plan is not ready yet.")}</p>}
        <ol className="space-y-4">
          {plannedPages.map((planned) => {
            const page = detailsByNumber.get(planned.page_number);
            return <li key={planned.page_number} id={`${prefix}-planned-page-${planned.page_number}`} tabIndex={-1} className="scroll-mt-40 md:scroll-mt-28 focus-visible:outline-2 focus-visible:outline-hero-red">
              <article className="bg-bristol p-4 sm:p-5">
                <div className="grid gap-3 sm:grid-cols-[5rem_minmax(0,1fr)] sm:gap-6">
                  <h3 className="flex items-baseline gap-2 font-meta text-xs font-bold text-ink-muted sm:block">{t("Page")} <span className="font-display text-2xl font-black tabular-nums text-ink-black sm:mt-1 sm:block">{String(planned.page_number).padStart(2, "0")}</span></h3>
                  <div className="min-w-0">
                    {page ? <>
                      <p className="whitespace-pre-line font-body text-base font-semibold leading-7">{page.rhythm_intent || t("Open the layout notes to explore this page.")}</p>
                      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
                        {page.page_turn_role && page.page_turn_role !== "none" && <div className="flex items-baseline gap-2"><dt className="sr-only">{t("Page turn")}</dt><dd className="font-meta text-xs font-semibold text-hero-red">{t(turnLabels[page.page_turn_role])}</dd></div>}
                        {page.density_intent && <div className="flex items-baseline gap-2"><dt className="font-body text-xs text-ink-muted">{t("Density")}</dt><dd className="font-meta text-xs">{t(densityLabels[page.density_intent])}</dd></div>}
                        {page.spread_role && <div><dt className="sr-only">{t("Placement")}</dt><dd className="font-meta text-xs text-ink-muted">{t(spreadLabels[page.spread_role])}</dd></div>}
                      </dl>
                      <details className="group/layout mt-3">
                        <summary className={disclosureClass}>{t("Layout & staging")}<ChevronDown size={16} aria-hidden="true" className="shrink-0 group-open/layout:rotate-180" /></summary>
                        <p className={`${copyClass} pb-2`}>{page.layout_intent || t("No layout notes are available.")}</p>
                      </details>
                    </> : <p className={`${copyClass} text-ink-muted`} role={detailsLoading ? "status" : undefined}>{detailsLoading ? t("Loading page details…") : detailsError ? t("Page details are not available right now.") : t("Details for this planned page are not available yet.")}</p>}
                  </div>
                </div>
              </article>
            </li>;
          })}
        </ol>
      </section>
      <EditorialNotes issues={plan.editorial_issues} />
    </div>
  );
}
