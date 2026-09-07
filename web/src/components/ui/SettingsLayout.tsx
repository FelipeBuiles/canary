import { cn } from "../../lib/cn";
import { SectionLabel } from "../SectionLabel";

export interface SettingsTab {
  id: string;
  label: string;
}

interface SettingsLayoutProps {
  kicker: string;
  title: string;
  subtitle?: string;
  /** Hide the in-page hero when the shell masthead already carries the title. */
  hero?: boolean;
  tabs: SettingsTab[];
  activeTab: string;
  onTabChange: (id: string) => void;
  children: React.ReactNode;
}

export function SettingsRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid gap-4 border-b-[2px] border-ink-black/10 px-5 py-5 last:border-b-0 md:grid-cols-[210px_1fr] md:items-start md:gap-7 md:px-6">
      <div>
        <h3 className="font-meta text-xs font-bold uppercase tracking-[0.1em] text-ink-black">
          {label}
        </h3>
        {hint && (
          <p className="mt-2 font-body text-[0.76rem] font-medium leading-5 text-ink-muted">{hint}</p>
        )}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

export function SettingsLayout({
  kicker,
  title,
  subtitle,
  hero = true,
  tabs,
  activeTab,
  onTabChange,
  children,
}: SettingsLayoutProps) {
  return (
    <div className="space-y-8 pb-10">
      {hero && (
        <section className="relative overflow-hidden border-[3px] border-ink-black bg-ink-black px-6 py-8 text-bristol shadow-paper md:px-9 md:py-10">
          <div aria-hidden="true" className="absolute inset-y-0 right-0 w-24 benday-paper opacity-20 sm:w-40" />
          <SectionLabel tone="red">{kicker}</SectionLabel>
          <h1 className="relative mt-4 max-w-[14ch] font-display text-[2.7rem] font-black uppercase leading-[0.9] tracking-[-0.035em] text-bristol sm:text-[3.25rem]">
            {title}
          </h1>
          {subtitle && (
            <p className="relative mt-5 max-w-[44rem] font-body text-[0.95rem] font-semibold leading-7 text-bristol/72">
              {subtitle}
            </p>
          )}
        </section>
      )}

      <div className="flex flex-col gap-6 md:flex-row md:gap-8">
        {/* Desktop sidebar tabs */}
        <nav className="hidden md:block">
          <div className="w-[210px] border-[2px] border-ink-black bg-bristol shadow-paper-sm">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => onTabChange(tab.id)}
                className={cn(
                  "flex min-h-12 w-full items-center gap-3 border-b border-ink-black/10 px-4 py-3 text-left font-body text-[0.82rem] font-bold transition-colors last:border-b-0",
                  activeTab === tab.id
                    ? "bg-ink-black text-bristol"
                    : "text-ink-black/65 hover:bg-surface-container hover:text-ink-black",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn("h-2 w-2 shrink-0", activeTab === tab.id ? "bg-hero-red" : "bg-ink-black/18")}
                />
                {tab.label}
              </button>
            ))}
          </div>
        </nav>

        {/* Mobile horizontal tabs */}
        <nav className="md:hidden">
          <div className="flex gap-1 overflow-x-auto border-b border-ink-black/12 pb-0">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => onTabChange(tab.id)}
                className={cn(
                  "min-h-11 shrink-0 border-b-[3px] px-4 py-2.5 font-meta text-xs tracking-[0.1em] transition-colors",
                  activeTab === tab.id
                    ? "border-b-hero-red text-ink-black font-bold"
                    : "border-transparent text-ink-black/55 hover:text-ink-black/80",
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </nav>

        {/* Content panel */}
        <div className="flex-1 max-w-[680px]">{children}</div>
      </div>
    </div>
  );
}
