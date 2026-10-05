import { ArrowUpRight, Check, ChevronDown } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { seriesPath } from "../../api/projectScope";
import { castReviewKey, useCastReview, type CastReview, type ReviewIssue } from "../../api/castReview";

export function CastIdentityReview({ projectId, characters, onShowCharacter, onUseSuggestion, onResume, busy, redrawing = new Set() }: {
  projectId: string;
  characters: { id: string; name: string }[];
  onShowCharacter: () => void;
  /** Opens the character's Review & adjust with the suggestion prefilled; never spends. */
  onUseSuggestion: (characterId: string, suggestion: string) => void;
  onResume: () => void;
  busy: boolean;
  /** Characters whose main sheet is being redrawn; their notes wait for the re-check. */
  redrawing?: Set<string>;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { data, isError } = useCastReview(projectId, busy);
  const dismiss = useMutation({
    mutationFn: (issue: ReviewIssue) => apiFetch<CastReview>(`${seriesPath(projectId)}/cast/review/dismiss`, {
      method: "POST",
      body: JSON.stringify({ character_ids: issue.character_ids, concern: issue.concern }),
    }),
    onSuccess: (review) => queryClient.setQueryData(castReviewKey(projectId), review),
  });
  const names = new Map(characters.map((character) => [character.id, character.name]));
  const reviewing = !isError && !!data?.reviewing;
  const currentIssues = !isError && !reviewing && data?.status === "current" ? data.issues : [];
  const issues = currentIssues.filter((issue) => !issue.character_ids.some((id) => redrawing.has(id)));
  const redrawingNames = [...redrawing].map((id) => names.get(id) ?? id).join(", ");
  const affectedNames = [...new Set(issues.flatMap((issue) => issue.character_ids))]
    .map((id) => names.get(id) ?? id).join(", ");
  const message = isError ? t("Could not load the cast review. Refresh to try again.")
    : !data ? t("Loading cast review…")
    : redrawing.size > 0 && issues.length === 0 ? t("Redrawing {names}. The check runs again on the new sheet when it finishes.", { names: redrawingNames })
    : reviewing ? t("Comparing {count, plural, one {# character sheet} other {# character sheets}} for lookalikes and mismatches with their descriptions. One AI pass, usually about a minute.", { count: data.characters ?? characters.length })
    : data.status === "stale" ? t("The cast has changed since its review. Resume Cast to compare the current references.")
    : data.status === "missing" ? t("Run Cast to design distinct characters and compare their generated references.")
    : data.dismissed > 0 ? t("{count, plural, one {You marked # note as fine.} other {You marked # notes as fine.}} Nothing else was flagged; notes return if those sheets are redrawn.", { count: data.dismissed })
    : t("No identity problems were flagged. Check the references yourself before approving; this is not a guarantee of visual accuracy.");

  return (
    <section aria-label={t("Character identity review")} className="mb-7 bg-surface-container text-ink-black">
      {issues.length > 0 ? (
        <details className="group">
          <summary className="relative flex min-h-14 cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-2 p-4 pr-11 [&::-webkit-details-marker]:hidden">
            <span className="font-meta text-xs font-bold uppercase tracking-wider">{t("Character check")}</span>
            <span className="font-body text-sm font-semibold">
              {t("{count, plural, one {# note to review} other {# notes to review}}", { count: issues.length })}
            </span>
            <span className="min-w-0 flex-1 basis-full break-words font-body text-sm text-ink-muted sm:basis-auto">{affectedNames}</span>
            <ChevronDown size={18} aria-hidden="true" className="absolute right-4 top-5 group-open:rotate-180" />
          </summary>
          <div className="px-4 pb-5 sm:px-5">
            <p className="font-body text-sm leading-6 text-ink-muted">
              {t("Compare these notes with the artwork. Use a suggestion to open that character with the change filled in, or mark a note fine if the artwork already looks right. Notes are advice; you can continue with them open.")}
            </p>
            <ul className="mt-5 space-y-6">
              {issues.map((issue, index) => (
                <li key={`${issue.character_ids.join("-")}-${index}`}>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {issue.character_ids.map((id) => (
                      <a key={id} href={`#cast-character-${id}`} onClick={onShowCharacter}
                        className="inline-flex min-h-11 items-center font-display text-base font-bold underline underline-offset-4 hover:text-hero-red">
                        {names.get(id) ?? id}
                      </a>
                    ))}
                  </div>
                  <dl className="grid gap-4 md:grid-cols-2 md:gap-8">
                    <div>
                      <dt className="mb-1 font-meta text-xs font-semibold text-ink-muted">{t("What was noticed")}</dt>
                      <dd className="break-words font-body text-sm leading-6">{issue.evidence}</dd>
                    </div>
                    <div>
                      <dt className="mb-1 font-meta text-xs font-semibold text-ink-muted">{t("Suggested adjustment")}</dt>
                      <dd className="break-words font-body text-sm leading-6">{issue.suggestion}</dd>
                      <dd className="mt-2 flex flex-wrap gap-2">
                        {issue.suggestion.trim() && issue.character_ids.map((id) => {
                          const name = names.get(id) ?? id;
                          return (
                            <Button key={id} variant="outline" size="sm" onClick={() => onUseSuggestion(id, issue.suggestion)}
                              aria-label={`${t("Use this suggestion")} · ${name}`}>
                              <ArrowUpRight size={16} aria-hidden="true" />
                              {issue.character_ids.length > 1 ? t("Use for {name}", { name }) : t("Use this suggestion")}
                            </Button>
                          );
                        })}
                        <Button variant="secondary" size="sm" disabled={dismiss.isPending} onClick={() => dismiss.mutate(issue)}>
                          <Check size={16} aria-hidden="true" />
                          {t("This looks right")}
                        </Button>
                      </dd>
                      {dismiss.isError && dismiss.variables === issue && (
                        <dd role="alert" className="mt-2 font-body text-sm text-hero-red">
                          {dismiss.error instanceof Error ? dismiss.error.message : t("Could not save. Try again.")}
                        </dd>
                      )}
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          </div>
        </details>
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-3 p-4">
          <div>
            <h3 className="font-meta text-xs font-bold uppercase tracking-wider">{t("Character check")}</h3>
            <p className="mt-2 font-body text-sm leading-6 text-ink-muted">{message}</p>
          </div>
          {!isError && data && !reviewing && redrawing.size === 0 && data.status !== "current" && (
            <Button variant="outline" size="sm" disabled={busy} onClick={onResume}>
              {t("RESUME CAST")}
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
