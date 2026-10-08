import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ErrorNotice } from "../composites/ErrorNotice";
import { useI18n } from "../../i18n";
import { selectPageRender } from "../../api/pages";
import { invalidateProject } from "../../api/projectScope";
import { Button } from "../ui/Button";

export interface RevisionOption {
  revision: number;
  /** Drawn from an earlier page plan; viewable but never selectable. */
  stale: boolean;
}

/**
 * Steps through every saved render of a page from the page view. Viewing is
 * free and local; "Use this version" makes the viewed render the one used for
 * reading, export and the next correction.
 */
export function RevisionSwitcher({ project, pageNumber, revisions, selected, viewing, onView, disabled }: {
  project: string;
  pageNumber: number;
  /** Ascending render revisions. */
  revisions: RevisionOption[];
  selected: number;
  viewing: number;
  onView: (revision: number) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const select = useMutation({
    mutationFn: (chosen: number) => selectPageRender(project, pageNumber, chosen, selected),
    // The selected render re-keys the page view, which resets viewing to it.
    onSuccess: () => invalidateProject(qc, project),
  });
  const index = revisions.findIndex((option) => option.revision === viewing);
  const current = revisions[index];
  if (revisions.length < 2 || !current) return null;

  function step(offset: number) {
    const next = revisions[index + offset];
    if (next) {
      select.reset();
      onView(next.revision);
    }
  }

  const latest = revisions[revisions.length - 1].revision;
  return (
    <div role="group" aria-label={t("Page versions")} className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <div className="flex items-center border border-ink-black/25">
        <button type="button" className="flex min-h-9 min-w-9 items-center justify-center disabled:opacity-30"
          aria-label={t("Previous version")} disabled={index <= 0} onClick={() => step(-1)}>
          <ChevronLeft size={16} aria-hidden="true" />
        </button>
        <label className="sr-only" htmlFor={`revision-switcher-${pageNumber}`}>{t("Version")}</label>
        <div className="relative">
          <select id={`revision-switcher-${pageNumber}`} value={viewing}
            className="min-h-9 appearance-none border-x border-ink-black/25 bg-transparent pl-3 pr-9 font-meta text-xs font-bold"
            onChange={(event) => { select.reset(); onView(Number(event.target.value)); }}>
            {revisions.map((option) => (
              <option key={option.revision} value={option.revision}>
                {t("Revision")} {option.revision}
                {option.revision === selected ? ` · ${t("Selected")}` : option.revision === latest ? ` · ${t("Latest")}` : ""}
                {option.stale ? ` · ${t("earlier plan")}` : ""}
              </option>
            ))}
          </select>
          <ChevronDown size={14} aria-hidden="true" className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2" />
        </div>
        <button type="button" className="flex min-h-9 min-w-9 items-center justify-center disabled:opacity-30"
          aria-label={t("Next version")} disabled={index >= revisions.length - 1} onClick={() => step(1)}>
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </div>
      <span className="font-meta text-xs text-ink-muted">{index + 1} / {revisions.length}</span>
      {viewing !== selected && (
        <>
          <Button size="sm" disabled={disabled || current.stale || select.isPending}
            onClick={() => select.mutate(viewing)}>
            {select.isPending ? t("Selecting…") : t("Use this version")}
          </Button>
          <button type="button" className="font-meta text-xs underline underline-offset-4"
            onClick={() => { select.reset(); onView(selected); }}>
            {t("Back to selected")}
          </button>
          <p className="basis-full text-xs leading-5 text-ink-muted">
            {current.stale
              ? t("This version belongs to an earlier page plan.")
              : t("Previewing only. Changes and exports use the selected version until you choose this one. Choosing costs no credits.")}
          </p>
        </>
      )}
      {select.error && <ErrorNotice error={select.error} operation="save" />}
    </div>
  );
}
