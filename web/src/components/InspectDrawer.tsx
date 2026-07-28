import { useAdaptation, useBookPlan, useCompletePages } from "../api/queries";
import { useI18n } from "../i18n";
import type { DrawerKind } from "../lib/stations";
import { Button } from "./ui/Button";
import { Surface } from "./ui/Surface";
import type { BookAdaptation, CompletePageSummary } from "../types/api";

interface InspectDrawerProps {
  project: string;
  kind: DrawerKind | null;
  onClose: () => void;
}

function countLabel(value: number, singular: string, plural: string) {
  return `${value} ${value === 1 ? singular : plural}`;
}

function AdaptationDetails({ adaptation }: { adaptation: BookAdaptation }) {
  const { t } = useI18n();
  const beats = adaptation.beats ?? [];
  const ledger = adaptation.ledger ?? [];
  const treatment = adaptation.treatment;
  const letteringCount = beats.reduce((total, beat) => total + (beat.lettering?.length ?? 0), 0);
  const transitionCount = beats.reduce((total, beat) => total + (beat.transitions?.length ?? 0), 0);
  const appearanceChangeCount = beats.reduce((total, beat) => total + (beat.appearance_changes?.length ?? 0), 0);
  const compressedCount = ledger.filter((entry) => entry.disposition === "compressed_into").length;
  const omittedCount = ledger.filter((entry) => entry.disposition === "intentionally_omitted").length;
  const treatmentSignals = [
    ["REVEALS", treatment?.reveals],
    ["CONSEQUENCES", treatment?.consequences],
    ["AFTERMATH", treatment?.aftermath],
    ["CHARACTER ARCS", treatment?.character_arcs],
    ["RELATIVE EMPHASIS", treatment?.relative_emphasis],
  ] as const;

  return (
    <>
      <Surface tone="container" border="soft" shadow="none" padding="md">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-5">
          <div>
            <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("ORDERED BEATS")}</dt>
            <dd className="mt-1 font-display text-xl font-black">{beats.length}</dd>
            <p className="mt-1 font-body text-xs text-ink-muted">{t("kept in story order")}</p>
          </div>
          <div>
            <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("SOURCE ACCOUNTING")}</dt>
            <dd className="mt-1 font-display text-xl font-black">{ledger.length}</dd>
            <p className="mt-1 font-body text-xs text-ink-muted">{t("source units accounted")}</p>
          </div>
          <div>
            <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("LETTERING ITEMS")}</dt>
            <dd className="mt-1 font-display text-xl font-black">{letteringCount}</dd>
            <p className="mt-1 font-body text-xs text-ink-muted">{t("dialogue, captions, and SFX")}</p>
          </div>
          <div>
            <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("STORY CONTINUITY")}</dt>
            <dd className="mt-1 font-display text-xl font-black">{transitionCount + appearanceChangeCount}</dd>
            <p className="mt-1 font-body text-xs text-ink-muted">
              {transitionCount} {t("transitions")} · {appearanceChangeCount} {t("appearance changes")}
            </p>
          </div>
        </dl>
        <dl className="mt-5 border-t border-ink-black/12 pt-3">
          <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("SOURCE DISPOSITION")}</dt>
          <dd className="mt-1 font-body text-sm font-semibold">
            {ledger.length - compressedCount - omittedCount} {t("retained or depicted")} · {compressedCount} {t("compressed")} · {omittedCount} {t("omitted")}
          </dd>
        </dl>
      </Surface>

      <Surface padding="md" border="soft" shadow="none">
        <h3 className="font-display text-lg font-black uppercase">{t("NARRATIVE TREATMENT")}</h3>
        <h4 className="mt-4 font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-hero-red">{t("CAUSAL SPINE")}</h4>
        <ul className="mt-3 space-y-2 font-body text-sm leading-6">
          {(treatment?.causal_spine ?? []).map((line, index) => (
            <li key={`spine-${index}`} className="bg-surface-container px-3 py-2">{line}</li>
          ))}
        </ul>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          {treatmentSignals.map(([label, values]) => values && values.length > 0 && (
            <div key={label}>
              <h4 className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-hero-red">{t(label)}</h4>
              <ul className="mt-2 space-y-1 font-body text-xs leading-5 text-ink-muted">
                {values.map((value) => <li key={value}>· {value}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </Surface>

      <section aria-label={t("BEAT REGISTER")}>
        <div className="mb-3 flex items-baseline justify-between gap-3 border-b-[2px] border-ink-black pb-2">
          <h3 className="font-display text-lg font-black uppercase">{t("BEAT REGISTER")}</h3>
          <span className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">
            {countLabel(beats.length, t("beat"), t("beats"))}
          </span>
        </div>
        <ol className="space-y-1">
          {beats.map((beat) => (
            <li key={beat.id} className="grid grid-cols-[2.25rem_minmax(0,1fr)] items-start gap-3 bg-surface-container px-3 py-3">
              <span className="font-display text-lg font-black leading-none">{beat.order}</span>
              <div className="min-w-0">
                <p className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] text-hero-red">
                  {t(beat.narrative_function ?? "beat")} · {beat.source_unit_ids?.length ?? 0} {t("source units")}
                  {beat.lettering?.length ? ` · ${beat.lettering.length} ${t("lettering")}` : ""}
                </p>
                <p className="mt-1 font-body text-sm font-semibold leading-5">{beat.summary}</p>
                {beat.story_functions && beat.story_functions.length > 0 && (
                  <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
                    {beat.story_functions.map((value) => t(value)).join(" · ")}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function PagePlanDetails({
  pages,
  targetPageMin,
  targetPageMax,
}: {
  pages: CompletePageSummary[];
  targetPageMin: number;
  targetPageMax: number;
}) {
  const { t } = useI18n();
  const pageCount = pages.length;
  const beatCount = new Set(
    pages.flatMap((item) => item.page.content.flatMap((content) => content.beat_ids)),
  ).size;
  const letteringCount = pages.reduce(
    (total, item) => total + item.page.content.reduce((count, content) => count + content.lettering.length, 0),
    0,
  );
  const spreadPageCount = pages.filter((item) => item.page.spread_role !== "single").length;
  const densityCounts = pages.reduce<Record<string, number>>((counts, item) => {
    counts[item.page.density_intent] = (counts[item.page.density_intent] ?? 0) + 1;
    return counts;
  }, {});
  const densitySummary = ["sparse", "standard", "dense"]
    .filter((density) => densityCounts[density])
    .map((density) => `${densityCounts[density]} ${t(density)}`)
    .join(" · ");

  return (
    <>
      <Surface tone="container" border="soft" shadow="none" padding="md">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-5">
          <div>
            <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("PLANNED PAGES")}</dt>
            <dd className="mt-1 font-display text-xl font-black">{pageCount}</dd>
            <p className="mt-1 font-body text-xs text-ink-muted">{t("Target range")} {targetPageMin}–{targetPageMax}</p>
          </div>
          <div>
            <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("STORY BEATS")}</dt>
            <dd className="mt-1 font-display text-xl font-black">{beatCount}</dd>
            <p className="mt-1 font-body text-xs text-ink-muted">{t("allocated across pages")}</p>
          </div>
          <div>
            <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("LETTERING")}</dt>
            <dd className="mt-1 font-display text-xl font-black">{letteringCount}</dd>
            <p className="mt-1 font-body text-xs text-ink-muted">{t("dialogue, captions, and SFX")}</p>
          </div>
          <div>
            <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("SPREAD PAGES")}</dt>
            <dd className="mt-1 font-display text-xl font-black">{spreadPageCount}</dd>
            <p className="mt-1 font-body text-xs text-ink-muted">{t("linked to a facing page")}</p>
          </div>
        </dl>
        <div className="mt-5 border-t border-ink-black/12 pt-3">
          <dt className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("DENSITY MIX")}</dt>
          <dd className="mt-1 font-body text-sm font-semibold">{densitySummary || t("Page density is not available yet.")}</dd>
        </div>
      </Surface>

      <section aria-label={t("PAGE REGISTER")}>
        <div className="mb-3 flex items-baseline justify-between gap-3 border-b-[2px] border-ink-black pb-2">
          <h3 className="font-display text-lg font-black uppercase">{t("PAGE REGISTER")}</h3>
          <span className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.12em] text-ink-muted">
            {countLabel(pageCount, t("page"), t("pages"))}
          </span>
        </div>
        <ol className="space-y-1">
          {pages.map((item) => (
            <li key={item.page.page_number} className="grid grid-cols-[2.25rem_minmax(0,1fr)_auto] items-start gap-3 bg-surface-container px-3 py-3">
              <span className="font-display text-lg font-black leading-none">{item.page.page_number}</span>
              <div className="min-w-0">
                <p className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] text-hero-red">
                  {t(item.page.page_turn_role)} · {t(item.page.emphasis)} · {t(item.page.spread_role)}
                </p>
                <p className="mt-1 font-body text-sm font-semibold leading-5">{item.page.layout_intent}</p>
                <p className="mt-1 font-body text-xs leading-5 text-ink-muted">{item.page.rhythm_intent}</p>
              </div>
              <span className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.1em] text-ink-muted">
                {t(item.page.density_intent)}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

export function InspectDrawer({ project, kind, onClose }: InspectDrawerProps) {
  const { t } = useI18n();
  const adaptation = useAdaptation(kind === "adaptation" ? project : undefined);
  const plan = useBookPlan(kind === "page-plan" ? project : undefined);
  const completePages = useCompletePages(kind === "page-plan" ? project : undefined);

  if (!kind) return null;
  const title = kind === "adaptation" ? t("BOOK ADAPTATION") : t("PAGE PLAN");
  const loading = kind === "adaptation" ? adaptation.isLoading : plan.isLoading;
  const error = kind === "adaptation" ? adaptation.error : plan.error;

  return (
    <aside
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-[120] flex justify-end bg-ink-black/60"
      onClick={onClose}
    >
      <div
        className="h-full w-full max-w-2xl overflow-y-auto border-l-[3px] border-ink-black bg-pulp-paper shadow-ink"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="relative sticky top-0 z-10 flex min-h-14 items-center justify-between gap-4 border-b-[3px] border-ink-black bg-bristol px-5 py-3 md:h-shell-top md:py-4">
          <div className="min-w-0">
            <p className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.14em] text-hero-red">{t("AUTOMATIC WORK")}</p>
            <h2 className="truncate font-display text-[1.55rem] font-black uppercase leading-[0.9] tracking-[-0.03em]">{title}</h2>
          </div>
          <Button variant="outline" size="xs" onClick={onClose}>{t("CLOSE")}</Button>
          <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-[4px] bg-hero-red" />
        </header>

        <div className="space-y-5 p-5">
          {loading && <p className="font-meta text-sm font-bold">{t("LOADING…")}</p>}
          {error && (
            <Surface tone="gold" border="hard" shadow="none" padding="md">
              <p className="font-body text-sm font-bold">{t("This automatic work is not available yet.")}</p>
            </Surface>
          )}

          {kind === "adaptation" && adaptation.data && (
            <>
              <AdaptationDetails adaptation={adaptation.data} />
            </>
          )}

          {kind === "page-plan" && plan.data && (
            <>
              <Surface padding="md" border="soft" shadow="none">
                <h3 className="font-display text-lg font-black uppercase">{t("Book rhythm")}</h3>
                <p className="mt-2 font-body text-sm leading-6">
                  {plan.data.rhythm_summary || t("The page and spread rhythm is ready.")}
                </p>
              </Surface>
              {completePages.data?.pages ? (
                <PagePlanDetails
                  pages={completePages.data.pages}
                  targetPageMin={plan.data.target_page_min}
                  targetPageMax={plan.data.target_page_max}
                />
              ) : (
                <Surface tone="container" border="soft" shadow="none" padding="md">
                  <h3 className="font-display text-lg font-black uppercase">{t("Planned pages")}</h3>
                  <p className="mt-2 font-body text-sm">{t("Loading page details…")}</p>
                </Surface>
              )}
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
