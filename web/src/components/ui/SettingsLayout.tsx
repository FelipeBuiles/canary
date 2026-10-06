import { ChevronRight } from "lucide-react";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";

export interface SettingsTab { id: string; label: string; }
interface SettingsLayoutProps {
  kicker: string;
  title: string;
  subtitle?: string;
  hero?: boolean;
  tabs: SettingsTab[];
  activeTab: string;
  onTabChange: (id: string) => void;
  children: React.ReactNode;
}

export function SettingsRow({ label, hint, children, stacked = false }: { label: string; hint?: string; children: React.ReactNode; stacked?: boolean }) {
  // The row's own width decides whether label and control sit side by side.
  return <section className="@container not-last:border-b not-last:border-ink-black/10">
    <div className={cn("grid gap-4", stacked ? "py-4" : "px-5 py-6 @min-[40rem]:grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)] @min-[40rem]:gap-8 @min-[40rem]:px-7 @min-[40rem]:py-8")}>
      <div>
        <h3 className="font-body text-base font-bold leading-6 text-ink-black">{label}</h3>
        {hint && <p className="mt-2 font-body text-sm leading-6 text-ink-muted">{hint}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  </section>;
}

export function SettingsLayout({ title, subtitle, hero = true, tabs, activeTab, onTabChange, children }: SettingsLayoutProps) {
  const { t } = useI18n();
  return <div className="@container/settings mx-auto w-full max-w-6xl space-y-8 pb-12 md:space-y-10">
    {hero && <header className="py-3 md:py-5">
      <h1 className="font-display text-4xl font-black uppercase leading-tight tracking-[-0.03em] md:text-5xl">{t(title)}</h1>
      {subtitle && <p className="mt-4 font-body text-base leading-7 text-ink-muted">{t(subtitle)}</p>}
    </header>}
    <div className="grid items-start gap-6 @min-[46rem]/settings:grid-cols-[200px_minmax(0,1fr)] @min-[46rem]/settings:gap-9">
      <nav aria-label={t("Settings sections")} className="flex gap-1 overflow-x-auto pb-2 @min-[46rem]/settings:flex-col @min-[46rem]/settings:overflow-visible @min-[46rem]/settings:pb-0">
        {tabs.map((tab) => <button key={tab.id} type="button" aria-current={activeTab === tab.id ? "page" : undefined} onClick={() => onTabChange(tab.id)}
          className={cn("flex min-h-12 shrink-0 items-center justify-between gap-4 px-4 py-3 text-left font-body text-sm font-semibold transition-colors @min-[46rem]/settings:w-full", activeTab === tab.id ? "bg-ink-black text-bristol shadow-paper-sm" : tab.id === "delete" ? "text-hero-red hover:bg-chip-red/40" : "text-ink-muted hover:bg-surface-container hover:text-ink-black")}>
          {t(tab.label)}<ChevronRight size={16} aria-hidden="true" className={cn("hidden shrink-0 @min-[46rem]/settings:block", activeTab !== tab.id && "opacity-0")} />
        </button>)}
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
  </div>;
}
