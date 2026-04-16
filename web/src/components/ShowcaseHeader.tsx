import type { ReactNode } from "react";
import { SectionLabel } from "./SectionLabel";
import { Card } from "./ui/Card";
import { cn } from "../lib/cn";

/**
 * Standard room-page header: chip label + big display title + optional lead copy.
 * Matches the "THE LIVING INK" masthead pattern in the spec.
 */
export function ShowcaseHeader({
  label,
  labelTone = "red",
  title,
  lead,
  actions,
  className,
}: {
  label: string;
  labelTone?: "red" | "gold" | "sage" | "ink" | "bristol";
  title: string;
  lead?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("p-5 md:p-6", className)}>
      <div className="flex items-start justify-between gap-4">
        <SectionLabel tone={labelTone}>{label}</SectionLabel>
        {actions}
      </div>
      <h1 className="mt-4 font-display font-bold text-ink-black display-headline">
        {title}
      </h1>
      {lead && <div className="mt-4 lead-pulp max-w-[52ch]">{lead}</div>}
    </Card>
  );
}
