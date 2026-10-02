import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useI18n } from "../../i18n";
import { Select } from "../ui/Select";
import { PartsDialog } from "./PartsDialog";
import { partProjectKey, splitProjectKey, withProjectKey } from "../../api/projectScope";
import type { PartSummary } from "../../types/api";

const MANAGE = "__manage_parts";

interface Props {
  project: string;
  parts: PartSummary[];
  tone?: "light" | "dark";
  className?: string;
}

/** Choose the part to work on, or manage the series' parts. */
export function PartSwitcher({ project, parts, tone = "dark", className }: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [managing, setManaging] = useState(false);
  const { id, part } = splitProjectKey(project);
  if (!part) return null;
  const options = [
    ...parts.map((item) => ({ value: item.id, label: `${item.ordinal}. ${item.title}` })),
    { value: MANAGE, label: parts.length > 1 ? t("Manage parts…") : t("Add or split parts…") },
  ];
  return (
    <>
      <Select
        aria-label={t("Part")}
        tone={tone}
        size="sm"
        value={part}
        options={options}
        className={className}
        onValueChange={(value) => {
          if (value === MANAGE) setManaging(true);
          // Page selections belong to a part, so the new part opens fresh.
          else if (value !== part) navigate({ pathname: withProjectKey(location.pathname, partProjectKey(id, value)) });
        }}
      />
      <PartsDialog open={managing} project={project} parts={parts} onClose={() => setManaging(false)} />
    </>
  );
}
