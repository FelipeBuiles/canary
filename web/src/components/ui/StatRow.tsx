import type { ReactNode } from "react";
import { useI18n } from "../../i18n";

interface StatRowProps {
  label: string;
  children: ReactNode;
}

export function StatRow({ label, children }: StatRowProps) {
  const { t } = useI18n();
  return (
    <div className="flex items-center justify-between border-b border-panel-line pb-3 last:border-b-0">
      <span className="font-meta text-[0.56rem] tracking-[0.18em] text-ink-black/45">
        {t(label)}
      </span>
      <span className="font-display text-[1.15rem] font-bold leading-none tracking-[-0.04em] tabular-nums">
        {children}
      </span>
    </div>
  );
}
