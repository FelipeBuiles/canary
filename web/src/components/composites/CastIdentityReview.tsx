import { ChevronDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { seriesPath } from "../../api/projectScope";

type Review = {
  status: "missing" | "stale" | "current";
  issues: {
    character_ids: string[];
    concern: string;
    evidence: string;
    suggestion: string;
  }[];
};

export function CastIdentityReview({ projectId, characters, onShowCharacter, onResume, busy }: {
  projectId: string;
  characters: { id: string; name: string }[];
  onShowCharacter: () => void;
  onResume: () => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const { data, isError } = useQuery({
    queryKey: ["cast-review", projectId],
    queryFn: () => apiFetch<Review>(`${seriesPath(projectId)}/cast/review`),
    refetchInterval: 10000,
  });
  const names = new Map(characters.map((character) => [character.id, character.name]));
  const issues = !isError && data?.status === "current" ? data.issues : [];
  const affectedNames = [...new Set(issues.flatMap((issue) => issue.character_ids))]
    .map((id) => names.get(id) ?? id).join(", ");
  const message = isError ? t("Could not load the cast review. Refresh to try again.")
    : !data ? t("Loading cast review…")
    : data.status === "stale" ? t("The cast has changed since its review. Resume Cast to compare the current references.")
    : data.status === "missing" ? t("Run Cast to design distinct characters and compare their generated references.")
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
              {t("Compare these notes with the artwork. Use Review & adjust on a character to make a change.")}
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
          {!isError && data && data.status !== "current" && (
            <Button variant="outline" size="sm" disabled={busy} onClick={onResume}>
              {t("RESUME CAST")}
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
