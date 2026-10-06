import type { ReactNode } from "react";

/** Size the statistics to their available space, including inside the station rail. */
export function ProgressStats({ children }: { children: ReactNode }) {
  return (
    <div className="@container mt-4">
      <dl className="grid grid-cols-1 gap-[3px] bg-ink-black p-[3px] @min-[18rem]:grid-cols-2 @min-[32rem]:grid-cols-4">
        {children}
      </dl>
    </div>
  );
}

export function ProgressStat({ value, total, label, detail }: {
  value: string;
  total?: string;
  label: string;
  detail?: string;
}) {
  return (
    <div className="@container flex min-w-0 flex-col bg-bristol px-3 py-2.5 [overflow-wrap:anywhere]">
      <dt className="order-2 mt-1 font-meta text-[0.62rem] font-bold uppercase tracking-[0.08em] text-ink-muted">{label}</dt>
      <dd className="order-1 font-display text-[clamp(1.25rem,12cqi,1.7rem)] font-black leading-[1.1] tracking-[-0.03em] tabular-nums text-ink-black">
        {value}{total !== undefined && <><wbr />/{total}</>}
      </dd>
      {detail && <dd className="order-3 mt-0.5 font-meta text-[0.62rem] text-ink-soft">{detail}</dd>}
    </div>
  );
}
