import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../../i18n";
import {
  applyNote,
  checkNotePages,
  getNoteApplyEstimate,
  getNoteChecksEstimate,
  previewNote,
  undoNote,
  type NoteChange,
  type NoteClaim,
} from "../../api/notes";
import { invalidateProject } from "../../api/projectScope";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { ConfirmDrawer } from "../composites";
import { ErrorNotice } from "../composites/ErrorNotice";
import { Button } from "../ui/Button";
import { cn } from "../../lib/cn";

/**
 * A change the page's art can't hold by itself: a line of the script, a
 * story moment, or a look that lasts beyond this page. Canary lists every
 * page it touches (code finds them, not the model), checks drawn pages
 * before anything is redrawn, and changes the Story Bible, script and plan
 * together, or not at all. Applied changes undo as one step.
 */
export function CarryThrough({ project, pageNumber, note, claim }: {
  project: string;
  pageNumber: number;
  note: string;
  claim: NoteClaim;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [change, setChange] = useState<NoteChange | null>(null);
  const [confirm, setConfirm] = useState<"checks" | "apply" | null>(null);
  const [chosen, setChosen] = useState<number[] | null>(null);
  const settle = (next: NoteChange) => {
    setChange(next);
    setConfirm(null);
    void invalidateProject(queryClient, project);
  };
  const preview = useMutation({ mutationFn: () => previewNote(project, pageNumber, note, claim), onSuccess: setChange });
  const checksEstimate = useQuery({
    queryKey: ["project", project, "note-checks-estimate", change?.id],
    queryFn: () => getNoteChecksEstimate(project, change!.id),
    enabled: confirm === "checks" && change != null,
    retry: false,
  });
  const applyEstimate = useQuery({
    queryKey: ["project", project, "note-apply-estimate", change?.id, change?.checks.length],
    queryFn: () => getNoteApplyEstimate(project, change!.id),
    enabled: confirm === "apply" && change != null,
    retry: false,
  });
  const checks = useMutation({
    mutationFn: () => checkNotePages(project, change!.id),
    onSuccess: (next) => { setChosen(null); settle(next); },
    onError: (error) => maybeShowInsufficientCredits(error, { actionLabel: t("CHECK PAGES"), onRetry: () => checks.mutate() }),
  });
  const apply = useMutation({
    mutationFn: (pages: number[]) => applyNote(project, change!.id, pages),
    onSuccess: settle,
    onError: (error, pages) => maybeShowInsufficientCredits(error, { actionLabel: t("APPLY"), onRetry: () => apply.mutate(pages) }),
  });
  const undo = useMutation({ mutationFn: () => undoNote(project, change!.id), onSuccess: settle });

  const headline = claim.kind === "look"
    ? t("THIS GOES BEYOND PAGE {page}", { page: pageNumber })
    : claim.kind === "line" ? t("THIS CHANGES THE SCRIPT") : t("THIS CHANGES THE STORY");
  const intro = claim.kind === "look"
    ? claim.fact
    : claim.kind === "line"
      ? t("A redraw can’t change the script. Canary can change this line in the script, then the pages that carry it.")
      : t("A redraw can’t add story. Canary can rewrite this moment in the script and re-plan only the pages that carry it.");

  if (change == null) {
    return (
      <div className="space-y-2 border-l-2 border-hero-red pl-3" role="status">
        <p className="font-meta text-xs font-bold text-hero-red">{headline}</p>
        <p className="font-body text-xs leading-5">{intro}</p>
        <Button size="xs" disabled={preview.isPending} onClick={() => preview.mutate()}>
          {preview.isPending ? t("Finding pages…") : t("SHOW THE PAGES IT TOUCHES")}
        </Button>
        {preview.error && <ErrorNotice error={preview.error} operation="generate" />}
      </div>
    );
  }

  const pages = change.scope.pages.map((page) => page.page_number);
  const selected = chosen ?? change.default_pages;
  const broken = change.checks.filter((check) => check.breaks_fact).map((check) => check.page_number);
  const checked = change.checks.length > 0;
  const needsCheck = change.check_pages.length > 0 && !checked;
  const pageList = (numbers: number[]) => numbers.join(", ");

  if (change.status === "applied") {
    return (
      <div className="space-y-2 border-l-2 border-ink-black pl-3" role="status">
        <p className="font-meta text-xs font-bold">{t("CARRIED THROUGH")}</p>
        <p className="font-body text-xs leading-5">
          {t("{count, plural, one {Changed page {pages}.} other {Changed pages {pages}.}}", { count: change.pages.length, pages: pageList(change.pages) })}
          {change.redraw_pages.length > 0 && " " + t("Redraw {pages} to show it; their current art stays in history.", { pages: pageList(change.redraw_pages) })}
        </p>
        {change.added_state && (
          <p className="font-body text-xs leading-5">{t("Draw the new look in Look before redrawing those pages.")}</p>
        )}
        <Button size="xs" variant="outline" disabled={undo.isPending} onClick={() => undo.mutate()}>
          {undo.isPending ? t("Undoing…") : t("UNDO")}
        </Button>
        {undo.error && <ErrorNotice error={undo.error} operation="generate" />}
      </div>
    );
  }
  if (change.status === "undone") {
    return (
      <div className="border-l-2 border-ink-black/25 pl-3" role="status">
        <p className="font-body text-xs leading-5 text-ink-muted">{t("Undone. The script and pages are as they were.")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2 border-l-2 border-hero-red pl-3" role="status">
      <p className="font-meta text-xs font-bold text-hero-red">{headline}</p>
      <p className="font-body text-xs leading-5">
        {claim.kind === "look"
          ? t("{count, plural, one {Shows on page {pages}.} other {Shows on {count} pages: {pages}.}}", { count: pages.length, pages: pageList(pages) })
          : t("{count, plural, one {Touches page {pages}.} other {Touches pages {pages}.}}", { count: pages.length, pages: pageList(pages) })}
      </p>
      {checked && (
        <p className="font-body text-xs leading-5">
          {broken.length > 0
            ? t("The art breaks it on {pages}.", { pages: pageList(broken) })
            : t("Every other drawn page already shows it.")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {needsCheck && (
          <Button size="xs" variant="outline" disabled={checks.isPending} onClick={() => setConfirm("checks")}>
            {checks.isPending ? t("Checking pages…") : t("CHECK {count} DRAWN PAGES", { count: change.check_pages.length })}
          </Button>
        )}
        <Button size="xs" disabled={apply.isPending} onClick={() => setConfirm("apply")}>
          {apply.isPending ? t("Applying…") : t("APPLY")}
        </Button>
      </div>
      {(checks.error || apply.error) && <ErrorNotice error={(checks.error || apply.error)!} operation="generate" />}
      <ConfirmDrawer
        open={confirm === "checks"}
        title={t("CHECK PAGES")}
        body={t("Looks at each other drawn page for art that breaks this. Nothing is changed or redrawn.")}
        cost={checksEstimate.data}
        extraBody={checksEstimate.error ? <ErrorNotice error={checksEstimate.error} operation="estimate" /> : undefined}
        confirmLabel={t("CHECK PAGES")}
        busy={checks.isPending}
        disabled={!checksEstimate.data}
        onClose={() => setConfirm(null)}
        onConfirm={() => checks.mutate()}
      />
      <ConfirmDrawer
        open={confirm === "apply"}
        title={headline}
        body={claim.kind === "look"
          ? t("Adds the look to the Story Bible when it’s new, and shows it on the pages you choose. Pages left out keep their art and plan.")
          : t("Changes the script, then the pages that carry it, and checks the story like a stage run. All of it applies, or none of it.")}
        cost={applyEstimate.data}
        extraBody={(
          <div className="space-y-2">
            {claim.kind === "look" && (
              <fieldset className="flex flex-wrap gap-1.5">
                <legend className="mb-1 font-meta text-xs font-bold">{t("PAGES TO CHANGE")}</legend>
                {change.scope.pages.map((page) => {
                  const on = selected.includes(page.page_number);
                  return (
                    <label key={page.page_number} className={cn(
                      "cursor-pointer border-2 border-ink-black px-2 py-0.5 font-meta text-xs font-bold",
                      on ? "bg-ink-black text-bristol" : "bg-bristol text-ink-black",
                      broken.includes(page.page_number) && !on && "border-hero-red",
                    )}>
                      <input type="checkbox" className="sr-only" checked={on}
                        onChange={() => setChosen(on ? selected.filter((n) => n !== page.page_number) : [...selected, page.page_number].sort((a, b) => a - b))} />
                      {page.page_number}
                    </label>
                  );
                })}
              </fieldset>
            )}
            <p className="font-body text-xs leading-5 text-ink-muted">
              {t("Changed pages that are already drawn go out of date. Redraw them from Pages; their current art stays in history.")}
            </p>
            {applyEstimate.error && <ErrorNotice error={applyEstimate.error} operation="estimate" />}
          </div>
        )}
        confirmLabel={t("APPLY")}
        busy={apply.isPending}
        disabled={!applyEstimate.data || selected.length === 0}
        onClose={() => setConfirm(null)}
        onConfirm={() => apply.mutate(claim.kind === "look" ? selected : pages)}
      />
    </div>
  );
}
