import { useI18n } from "../../i18n";
import { splitProjectKey } from "../../api/projectScope";
import type { ProjectStatus } from "../../types/api";

/**
 * Advisory notices for the open part; nothing here re-runs on its own.
 * Out-of-date pages are reported once, by ``OutOfDatePages``.
 */
export function PartNotices({ project, status }: { project: string; status: ProjectStatus | undefined }) {
  const { t } = useI18n();
  const part = status?.parts?.find((item) => item.id === splitProjectKey(project).part);
  if (!part?.earlier_part_changed) return null;
  return (
    <section className="space-y-3 border-[2px] border-ink-black bg-surface-container p-5" aria-label={t("Notices for this part")}>
      <p className="font-body text-sm">{t("An earlier part was re-adapted after this one, so its continuity may have changed. Nothing re-runs on its own.")}</p>
    </section>
  );
}
