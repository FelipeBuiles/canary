import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { usePageFlags } from "../../api/seriesQueries";
import { splitProjectKey } from "../../api/projectScope";
import type { PageFlagReason } from "../../api/parts";
import type { ProjectStatus } from "../../types/api";

const REASONS: Record<PageFlagReason, string> = {
  description: "description changed",
  continuity: "continuity note changed",
  "reference image": "Cast image changed",
  removed: "removed from the Story Bible",
};

/** Advisory notices for the open part; nothing here re-runs on its own. */
export function PartNotices({ project, status, onOpenPage }: {
  project: string; status: ProjectStatus | undefined; onOpenPage: (page: number) => void;
}) {
  const { t } = useI18n();
  const { data } = usePageFlags(project);
  const part = status?.parts?.find((item) => item.id === splitProjectKey(project).part);
  const flagged = data?.pages ?? [];
  if (!flagged.length && !part?.earlier_part_changed) return null;
  return (
    <section className="space-y-3 border-[2px] border-ink-black bg-surface-container p-5" aria-label={t("Notices for this part")}>
      {part?.earlier_part_changed && (
        <p className="font-body text-sm">{t("An earlier part was re-adapted after this one, so its continuity may have changed. Nothing re-runs on its own.")}</p>
      )}
      {flagged.length > 0 && (
        <>
          <p className="font-body text-sm">
            {t("{count, plural, one {# page was} other {# pages were}} drawn before a later Story Bible or Cast change. They keep their artwork until you redraw them.", { count: flagged.length })}
          </p>
          <ul className="flex flex-wrap gap-2">
            {flagged.map((page) => {
              const detail = page.changes.map((change) =>
                `${change.label}: ${change.reasons.map((reason) => t(REASONS[reason])).join(", ")}`).join("; ");
              return (
                <li key={page.page_number}>
                  <Button size="xs" variant="outline" title={detail} onClick={() => onOpenPage(page.page_number)}>
                    {t("Page {number}", { number: page.page_number })}
                  </Button>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
