import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";

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
    queryFn: () => apiFetch<Review>(`/projects/${encodeURIComponent(projectId)}/cast/review`),
    refetchInterval: 10000,
  });
  const names = new Map(characters.map((character) => [character.id, character.name]));
  return (
    <section aria-labelledby="cast-identity-review" className="border-2 border-ink-black bg-bristol p-5 text-ink-black">
      <h2 id="cast-identity-review" className="font-display text-xl">{t("Character identity review")}</h2>
      <p className="mt-2 max-w-prose text-sm leading-6">
        {isError ? t("Could not load the cast review. Refresh to try again.")
          : !data ? t("Loading cast review…")
          : data.status === "stale" ? t("The cast has changed since its review. Resume Cast to compare the current references.")
          : data.status === "missing" ? t("Run Cast to design distinct characters and compare their generated references.")
          : data.issues.length ? t("Possible identity problems need your review. Compare the characters below, then use Review & adjust to correct an affected reference.")
          : t("No identity problems were flagged. Check the references yourself before approving; this is not a guarantee of visual accuracy.")}
      </p>
      {data && data.status !== "current" && (
        <Button variant="outline" size="sm" className="mt-3" disabled={busy} onClick={onResume}>
          {t("RESUME CAST")}
        </Button>
      )}
      {data?.status === "current" && data.issues.length > 0 && (
        <ul className="mt-4 space-y-5">
          {data.issues.map((issue, index) => (
            <li key={`${issue.character_ids.join("-")}-${index}`} className="border-t-2 border-ink-black/20 pt-3">
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {issue.character_ids.map((id) => (
                  <a key={id} href={`#cast-character-${id}`} onClick={onShowCharacter}
                    className="inline-flex min-h-11 items-center font-bold underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2">
                    {names.get(id) ?? id}
                  </a>
                ))}
              </div>
              <p className="max-w-prose text-sm leading-6">{issue.evidence}</p>
              <p className="mt-1 max-w-prose text-sm leading-6">{issue.suggestion}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
