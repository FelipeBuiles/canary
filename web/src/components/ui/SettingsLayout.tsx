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
  tabs: SettingsTab[];
  activeTab: string;
  onTabChange: (id: string) => void;
  children: React.ReactNode;
}

export function SettingsLayout({
  kicker,
  title,
  subtitle,
  tabs,
  activeTab,
  onTabChange,
  children,
}: SettingsLayoutProps) {
  return (
    <div className="space-y-8">
      <section>
        <SectionLabel tone="red">{kicker}</SectionLabel>
        <h1 className="mt-4 max-w-[14ch] display-impact">{title}</h1>
        {subtitle && (
          <p className="mt-5 lead-pulp max-w-[44rem]">{subtitle}</p>
        )}
      </section>

      <div className="flex flex-col gap-6 md:flex-row md:gap-8">
        {/* Desktop sidebar tabs */}
        <nav className="hidden md:block">
          <div className="w-[200px] border-[2px] border-ink-black bg-bristol">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => onTabChange(tab.id)}
                className={cn(
                  "w-full border-l-[3px] px-4 py-3 text-left font-meta text-[0.68rem] tracking-[0.14em] transition-colors",
                  activeTab === tab.id
                    ? "border-l-hero-red bg-pulp-paper text-ink-black font-bold"
                    : "border-transparent text-ink-black/55 hover:bg-pulp-paper/50",
                )}
              >
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
                  "shrink-0 border-b-[3px] px-4 py-2.5 font-meta text-[0.68rem] tracking-[0.14em] transition-colors",
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
