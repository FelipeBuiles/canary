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

export function SettingsRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <section className="grid gap-4 px-5 py-6 not-last:border-b not-last:border-ink-black/10 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)] lg:gap-8 lg:px-7 lg:py-8">
    <div>
      <h3 className="font-body text-base font-bold leading-6 text-ink-black">{label}</h3>
      {hint && <p className="mt-2 max-w-[42ch] font-body text-sm leading-6 text-ink-muted">{hint}</p>}
    </div>
    <div className="min-w-0">{children}</div>
  </section>;
}

export function SettingsLayout({ title, subtitle, hero = true, tabs, activeTab, onTabChange, children }: SettingsLayoutProps) {
  const { t } = useI18n();
  return <div className="mx-auto w-full max-w-6xl space-y-8 pb-12 md:space-y-10">
    {hero && <header className="py-3 md:py-5">
      <h1 className="font-display text-4xl font-black uppercase leading-tight tracking-[-0.03em] md:text-5xl">{t(title)}</h1>
      {subtitle && <p className="mt-4 max-w-[65ch] font-body text-base leading-7 text-ink-muted">{t(subtitle)}</p>}
    </header>}
    <div className="grid items-start gap-6 md:grid-cols-[200px_minmax(0,1fr)] md:gap-9">
      <nav aria-label={t("Settings sections")} className="flex gap-1 overflow-x-auto pb-2 md:flex-col md:overflow-visible md:pb-0">
        {tabs.map((tab) => <button key={tab.id} type="button" aria-current={activeTab === tab.id ? "page" : undefined} onClick={() => onTabChange(tab.id)}
          className={cn("flex min-h-12 shrink-0 items-center justify-between gap-4 px-4 py-3 text-left font-body text-sm font-semibold transition-colors md:w-full", activeTab === tab.id ? "bg-ink-black text-bristol shadow-paper-sm" : tab.id === "delete" ? "text-hero-red hover:bg-chip-red/40" : "text-ink-muted hover:bg-surface-container hover:text-ink-black")}>
          {t(tab.label)}<ChevronRight size={16} aria-hidden="true" className={cn("hidden shrink-0 md:block", activeTab !== tab.id && "opacity-0")} />
        </button>)}
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
  </div>;
}
