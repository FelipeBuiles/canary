import { useI18n } from "../../i18n";
import { msg } from "../../locales/messages";
import type { InvariantFailure } from "../../types/api";
import { SectionHeader } from "../composites/SectionHeader";

const groups = {
  story: msg("Story coverage"),
  lettering: msg("Dialogue and captions"),
  continuity: msg("Character and scene continuity"),
  pages: msg("Page flow and staging"),
  draft: msg("Saved draft checks"),
};
type Group = keyof typeof groups;

// Several checks can describe the same reader-facing problem. Show that
// explanation once, while keeping every finding in the support details.
const checks: { group: Group; codes: string[]; explanation: string }[] = [
  { group: "story", codes: ["missing_source_disposition", "missing_ledger_exception"],
    explanation: msg("Some passages have not been accounted for in the comic script.") },
  { group: "story", codes: ["source_disposition_not_realized"],
    explanation: msg("Some passages meant to appear as dialogue or narration are missing from the script.") },
  { group: "story", codes: ["missing_essential_event", "missing_character_turn"],
    explanation: msg("An important event or character change from your brief is missing from the script.") },
  { group: "story", codes: ["faithful_source_scene_erased"],
    explanation: msg("A scene has lost too much of its story in this faithful adaptation.") },
  { group: "story", codes: ["faithful_rushed_reaction_or_aftermath", "narrative_review_rushed_sequence"],
    explanation: msg("A key moment moves on too quickly for readers to follow the reaction or aftermath.") },
  { group: "story", codes: ["narrative_review_missing_context"],
    explanation: msg("A sequence is missing context that readers need to follow the story.") },
  { group: "story", codes: ["narrative_review_repeated_event", "narrative_review_padding"],
    explanation: msg("A sequence repeats or adds moments that make the story harder to follow.") },
  { group: "story", codes: ["narrative_review_unsupported_event"],
    explanation: msg("The script includes an event that is not supported by your story.") },
  { group: "lettering", codes: ["invalid_lettering_speaker", "lettering_speaker_visibility"],
    explanation: msg("Some dialogue does not clearly match the person speaking or whether they are visible.") },
  { group: "lettering", codes: ["incomplete_display_text", "trailing_clipped_display_text"],
    explanation: msg("Some dialogue or captions may be unfinished or have incomplete quotation marks.") },
  { group: "lettering", codes: ["protected_language_missing"],
    explanation: msg("Wording you asked to keep exactly is missing from the comic script. Resume adaptation to letter the book’s exact wording, or change the phrase under Protected language in the Story room.") },
  { group: "lettering", codes: ["lettering_allocation", "lettering_changed", "unknown_lettering", "duplicate_lettering", "lettering_beat_mismatch"],
    explanation: msg("The page plan needs to keep every line of dialogue and narration once, in order, with the right story moment.") },
  { group: "continuity", codes: ["unknown_entity", "reference_authority", "unapproved_appearance_state"],
    explanation: msg("Some characters, places, props, or changed appearances do not match your Story Bible and approved cast.") },
  { group: "continuity", codes: ["appearance_state_chronology", "cross_page_appearance_state", "appearance_state_allocation"],
    explanation: msg("A changed appearance is shown at the wrong point in the story or is missing its visual reference.") },
  { group: "continuity", codes: ["compound_appearance_change", "appearance_state_conflict"],
    explanation: msg("An appearance change needs separate visual moments so readers can follow the transformation.") },
  { group: "continuity", codes: ["incomplete_transition"],
    explanation: msg("A change in time, place, or a character’s situation is not clear enough.") },
  { group: "pages", codes: ["upstream_adaptation_granularity"],
    explanation: msg("The story needs more visual moments to fill the planned pages.") },
  { group: "pages", codes: ["beat_allocation", "page_order", "page_spread_order", "reading_order"],
    explanation: msg("Some story moments or pages are missing, repeated, or out of reading order.") },
  { group: "pages", codes: ["missing_panel_camera", "staging_authority", "canonical_page_contract"],
    explanation: msg("Some scenes need clearer directions for what the artwork should show and how it should be framed.") },
  { group: "pages", codes: ["missing_character_acting", "acting_for_non_character", "repeated_character_acting", "reference_angle_only"],
    explanation: msg("Some character poses, expressions, or viewing angles need clearer or more varied directions.") },
  { group: "draft", codes: ["source_authority_mismatch", "brief_authority_mismatch", "adaptation_authority_mismatch"],
    explanation: msg("The generated draft was based on an earlier version of your story, brief, or script.") },
  { group: "draft", codes: ["unknown_source_disposition", "unknown_source_provenance", "unknown_requirement"],
    explanation: msg("Some parts of the generated draft could not be matched to your current story or brief.") },
  { group: "draft", codes: ["narrative_review_invalid"],
    explanation: msg("The story check could not be completed, so the draft is not ready to continue.") },
];
const unknownCheck = {
  group: "draft" as const,
  explanation: msg("Part of the generated draft could not be checked. Try again before continuing to drawing."),
};

function pageNumbers(failures: InvariantFailure[]) {
  const numbers = failures.flatMap((failure) => (failure.artifact_ids ?? []).flatMap((id) => {
    const match = /^page_(\d+)(?:_|$)/.exec(id);
    const number = match ? Number(match[1]) : 0;
    return Number.isSafeInteger(number) && number > 0 ? [number] : [];
  }));
  return [...new Set(numbers)].sort((a, b) => a - b);
}

export function StageFailureSummary({ failures, recoveryStage }: {
  failures: InvariantFailure[];
  recoveryStage: "adapt" | "plan";
}) {
  const { t } = useI18n();
  const uniqueFailures = [...new Map(failures.map((failure) => [failure.id, failure])).values()];
  if (uniqueFailures.length === 0) return null;
  const grouped = new Map<Group, Map<string, InvariantFailure[]>>();
  for (const failure of uniqueFailures) {
    const check = checks.find((candidate) => candidate.codes.includes(failure.code)) ?? unknownCheck;
    const group = grouped.get(check.group) ?? new Map<string, InvariantFailure[]>();
    const matching = group.get(check.explanation) ?? [];
    matching.push(failure);
    group.set(check.explanation, matching);
    grouped.set(check.group, group);
  }

  return (
    <section aria-label={t("What needs another check")} className="mx-auto w-full max-w-[760px] px-2 pb-8 sm:px-6">
      <SectionHeader
        title={t("What needs another check")}
        description={t("The generated script or page plan needs corrections before drawing can start. Similar issues are grouped below.")}
      />
      <p className="mb-6 font-body text-sm leading-6 text-ink-muted">
        {recoveryStage === "adapt"
          ? t("Resume or restart adaptation to check the script again before page planning continues.")
          : t("Retry page planning to check these pages again.")}
      </p>
      <div className="space-y-6">
        {(Object.keys(groups) as Group[]).map((key) => {
          const explanations = grouped.get(key);
          if (!explanations) return null;
          const findings = [...explanations.values()].flat();
          return (
            <section key={key} aria-label={t(groups[key])} className="border-t border-ink-black/15 pt-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-body text-base font-semibold leading-7">{t(groups[key])}</h3>
                <span className="font-meta text-xs text-ink-muted">
                  {t("{count, plural, one {# check} other {# checks}}", { count: findings.length })}
                </span>
              </div>
              <ul className="mt-3 space-y-3 font-body text-sm leading-6 text-ink-black">
                {[...explanations].map(([explanation, matching]) => {
                  const pages = pageNumbers(matching);
                  return <li key={explanation}>
                    <p>{t(explanation)}</p>
                    {pages.length > 0 && <p className="mt-1 text-xs text-ink-muted">
                      {t("{count, plural, one {Page} other {Pages}}: {pages}", { count: pages.length, pages: pages.join(", ") })}
                    </p>}
                  </li>;
                })}
              </ul>
              <details className="mt-2">
                <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm text-ink-muted">{t("Technical details")}</summary>
                <ul className="space-y-4 bg-surface-container p-4 font-body text-sm leading-6 [overflow-wrap:anywhere]">
                  {findings.map((failure) => <li key={failure.id}>
                    <p>{failure.message}</p>
                    {failure.evidence.map((evidence, index) => <p key={index} className="mt-1 text-ink-muted">{evidence}</p>)}
                  </li>)}
                </ul>
              </details>
            </section>
          );
        })}
      </div>
    </section>
  );
}
