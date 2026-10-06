import { useI18n } from "../../i18n";
import { spendByPhase } from "../../lib/creditsHistory";
import { CreditAmount } from "../ui/CreditAmount";

const PHASE_COLORS: Record<string, string> = {
  story: "bg-ink-soft",
  look: "bg-on-secondary-container",
  adapt: "bg-archive-sage",
  draw: "bg-hero-red",
  finish: "bg-narrator-gold",
  other: "bg-panel-line",
};

/** Where a book's credits went, by the phases an author works through. */
export function CreditSpendSummary({ spendByStage }: { spendByStage: Record<string, number> | undefined }) {
  const { t } = useI18n();
  const phases = spendByPhase(spendByStage);
  const total = phases.reduce((sum, phase) => sum + phase.credits, 0);
  if (total === 0) return null;

  return (
    <div className="mb-6 border-[2px] border-ink-black/10 bg-bristol px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="font-body text-sm font-semibold text-ink-muted">{t("Spent on this book")}</p>
        <CreditAmount value={total} className="font-meta text-xl font-bold text-ink-black" />
      </div>
      <div aria-hidden="true" className="mt-3 flex h-3 gap-[2px] overflow-hidden">
        {phases.map((phase) => (
          <div key={phase.key} className={PHASE_COLORS[phase.key]} style={{ flexGrow: phase.credits, flexBasis: 4, minWidth: 4 }} />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 font-body text-sm">
        {phases.map((phase) => (
          <li key={phase.key} className="flex items-center gap-2">
            <span aria-hidden="true" className={`size-2.5 shrink-0 ${PHASE_COLORS[phase.key]}`} />
            <span className="font-semibold text-ink-black/82">{t(phase.label)}</span>
            <CreditAmount value={phase.credits} className="font-meta text-xs font-bold text-ink-muted" />
          </li>
        ))}
      </ul>
    </div>
  );
}
