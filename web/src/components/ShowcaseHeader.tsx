import type { ReactNode } from "react";
import { SectionLabel } from "./SectionLabel";
import { Card } from "./ui/Card";
import { cn } from "../lib/cn";
import { useI18n } from "../i18n";

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
  const { t } = useI18n();
  return (
    <Card className={cn("p-5 md:p-6", className)}>
      <div className="flex items-start justify-between gap-4">
        <SectionLabel tone={labelTone}>{t(label)}</SectionLabel>
        {actions}
      </div>
      <h1 className="mt-4 font-display font-bold text-ink-black display-headline">
        {t(title)}
      </h1>
      {lead && <div className="mt-4 lead-pulp">{typeof lead === "string" ? t(lead) : lead}</div>}
    </Card>
  );
}
