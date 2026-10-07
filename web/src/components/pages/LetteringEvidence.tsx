import { useState } from "react";
import { useI18n } from "../../i18n";
import { msg } from "../../locales/messages";
import type { PageIssue } from "../../types/api";
import { StatusPill } from "../ui/StatusPill";
import { Button } from "../ui/Button";
import { Surface } from "../ui/Surface";
import {
  alignChars,
  alignLettering,
  assessTextCheck,
  cropLeadingContext,
  cropMiddleContext,
  cropTrailingContext,
  isOcrIssue,
  issueConfirmed,
  normalizeLettering,
  ocrIssueTitle,
  readTextEvidence,
  type AssessedReading,
  type SegmentDifference,
  type TextCheckAssessment,
} from "./lettering";

const SUMMARIES: Record<TextCheckAssessment | "none", string> = {
  none: msg("Possible wording difference. The checker can misread text; compare it with the saved artwork before making changes."),
  likely_error: msg("This was read the same way twice, so the artwork probably differs from the script. Compare it with the artwork before making changes."),
  likely_misread: msg("A closer look matches the script, so the artwork is probably fine. If it looks right, choose Not a problem."),
  unclear: msg("This lettering was hard to read. Compare the artwork with the script before making changes."),
  unchecked: msg("This lettering hasn’t been double-checked yet. Compare the artwork with the script, or double-check it now at no cost."),
};

/** One plain-language line on what the second look found for this difference. */
function ReadingNote({ reading }: { reading: AssessedReading }) {
  const { t } = useI18n();
  return (
    <p className="font-meta text-ink-muted">
      {reading.assessment === "likely_error"
        ? t("Read the same way twice.")
        : reading.assessment === "likely_misread"
          ? t("A closer look reads “{text}”, matching the script.", { text: reading.closeUp })
          : t(reading.closeUp ? "Hard to read, even up close." : "Not double-checked.")}
    </p>
  );
}

function DifferenceRow({ difference, reading }: { difference: SegmentDifference; reading?: AssessedReading }) {
  const { t } = useI18n();
  if (difference.type === "same") {
    return (
      <li className="flex gap-2">
        <span aria-hidden="true" className="font-bold text-ink-muted">=</span>
        <span>{difference.expected}</span>
      </li>
    );
  }
  if (difference.type === "moved") {
    return (
      <li className="flex gap-2">
        <span aria-hidden="true" className="font-bold text-narrator-gold">⇄</span>
        <span>
          {t("Moved:")} {difference.expected}
        </span>
      </li>
    );
  }
  if (difference.type === "missing") {
    return (
      <li className="flex gap-2">
        <span aria-hidden="true" className="font-bold text-hero-red">−</span>
        <span>
          {t("Missing:")} <mark className="bg-hero-red/15 text-hero-red">{difference.expected}</mark>
        </span>
      </li>
    );
  }
  if (difference.type === "extra") {
    return (
      <li className="flex gap-2">
        <span aria-hidden="true" className="font-bold text-hero-red">+</span>
        <span>
          {t("Extra:")} <mark className="bg-hero-red/15 text-hero-red">{difference.recognized}</mark>
          {reading && <ReadingNote reading={reading} />}
        </span>
      </li>
    );
  }
  const hunks = alignChars(difference.expected ?? "", difference.recognized ?? "");
  const firstChanged = hunks.findIndex((hunk) => hunk.type === "changed");
  function renderSide(side: "expected" | "recognized") {
    return hunks.map((hunk, index) => {
      if (hunk.type === "changed") {
        const text = hunk[side] || "∅";
        return <mark key={index} className="bg-hero-red/15 text-hero-red">{text}</mark>;
      }
      const last = hunks.length - 1;
      const text = firstChanged < 0 || (index === 0 && index === last)
        ? hunk[side]
        : index === 0
          ? cropLeadingContext(hunk[side]).text
          : index === last
            ? cropTrailingContext(hunk[side]).text
            : cropMiddleContext(hunk[side]);
      return <span key={index}>{text}</span>;
    });
  }
  return (
    <li className="space-y-1">
      <p>
        <span className="font-bold">{t("Script:")} </span>
        {renderSide("expected")}
      </p>
      <p>
        <span className="font-bold">{t("On the page:")} </span>
        {renderSide("recognized")}
      </p>
      {reading && <ReadingNote reading={reading} />}
    </li>
  );
}

/**
 * One OCR finding: a plain-language conclusion, the script-versus-artwork
 * differences, and the raw reads behind a disclosure. The exact comparison
 * policy is unchanged; every segment pair is shown instead of only the first.
 * When a second look ran, each difference says what it found; the reads
 * themselves are never presented as a pipeline to the author.
 */
export function LetteringIssueCard({ issue, secondLook }: {
  issue: PageIssue;
  /** Free retry of unfinished close-up reads; omitted where no action belongs. */
  secondLook?: { onRetry: () => void; busy: boolean; error?: string };
}) {
  const { t } = useI18n();
  const expected = readTextEvidence(issue, "expected_text=");
  const recognized = readTextEvidence(issue, "recognized_text=");
  const closeUp = readTextEvidence(issue, "crop_recognized_text=");
  const { overall, readings } = assessTextCheck(issue);
  const readingFor = (text?: string) => text === undefined ? undefined
    : readings.find((reading) => normalizeLettering(reading.first) === normalizeLettering(text));
  const differences = expected && recognized ? alignLettering(expected, recognized) : null;
  const changedCount = differences?.filter((row) => row.type !== "same").length ?? 0;
  return (
    <div className="space-y-3">
      <div>
        <StatusPill
          tone={
            issueConfirmed(issue)
              ? "sage"
              : issue.status === "revised"
                ? "gold"
                : "gold"
          }
        >
          {t(
            issue.status === "revised"
              ? "REVISED — AWAITING CONFIRMATION"
              : issueConfirmed(issue)
                ? "CONFIRMED"
                : issue.status.toUpperCase(),
          )}
        </StatusPill>
        <p className="mt-3 font-body text-sm font-bold">{t(ocrIssueTitle(issue))}</p>
        <p className="mt-1 font-body text-xs leading-5 text-ink-black/75">{t(SUMMARIES[overall ?? "none"])}</p>
        {overall === "unchecked" && secondLook && (
          <div className="mt-2">
            <Button size="xs" variant="outline" disabled={secondLook.busy} onClick={secondLook.onRetry}>
              {t(secondLook.busy ? "DOUBLE-CHECKING…" : "DOUBLE-CHECK")}
            </Button>
            {secondLook.error && <p role="alert" className="mt-1 text-xs text-hero-red">{secondLook.error}</p>}
          </div>
        )}
      </div>
      {(expected || recognized) && (
        <details>
        <summary className="cursor-pointer py-2 font-meta text-xs font-bold">{t("Full text comparison")}</summary>
        <dl className="grid gap-2 font-body text-xs leading-5">
          {expected && (
            <div>
              <dt className="font-meta font-bold text-ink-muted">{t("SCRIPT")}</dt>
              <dd>{expected.join(" · ") || t("No lettering")}</dd>
            </div>
          )}
          {recognized && (
            <div>
              <dt className="font-meta font-bold text-ink-muted">{t("ON THE PAGE")}</dt>
              <dd>{recognized.join(" · ") || t("No readable lettering found")}</dd>
            </div>
          )}
          {closeUp && closeUp.length > 0 && (
            <div>
              <dt className="font-meta font-bold text-ink-muted">{t("CLOSER LOOK")}</dt>
              <dd>{closeUp.join(" · ")}</dd>
            </div>
          )}
        </dl>
        </details>
      )}
      {differences && changedCount > 0 && (
        <div className="bg-chip-gold/40 px-3 py-2 font-body text-xs leading-5">
          <p className="font-meta font-bold text-ink-muted">
            {t("POSSIBLE DIFFERENCES")} · {changedCount}
          </p>
          <ul className="mt-2 space-y-2">
            {differences
              .filter((row) => row.type !== "same")
              .map((row, index) => (
                <DifferenceRow key={`${row.type}:${index}`} difference={row} reading={readingFor(row.recognized)} />
              ))}
          </ul>
          {differences.some((row) => row.type === "same") && (
            <details className="mt-2">
              <summary className="cursor-pointer font-meta font-bold text-ink-muted">
                {t("Show matching lettering")}
              </summary>
              <ul className="mt-1 space-y-1">
                {differences
                  .filter((row) => row.type === "same")
                  .map((row, index) => (
                    <DifferenceRow key={`same:${index}`} difference={row} />
                  ))}
              </ul>
            </details>
          )}
        </div>
      )}
      <p className="font-body text-xs leading-5 text-ink-muted">
        {t("Revision")} {issue.render_revision}
        {issue.resolution_revision ? ` → ${t("Revision")} ${issue.resolution_revision}` : ""}
        {" · "}
        {t("Optional text review")}
      </p>
      {issue.dismissal_reason && (
        <p className="mt-2 font-body text-xs leading-5 text-ink-black/70">{issue.dismissal_reason}</p>
      )}
    </div>
  );
}

/** Non-OCR finding card with resolved/confirmed status made explicit. */
export function PlainIssueCard({ issue }: { issue: PageIssue }) {
  const { t } = useI18n();
  return (
    <div className="space-y-2">
      <StatusPill tone={issueConfirmed(issue) ? "sage" : "gold"}>
        {t(
          issue.status === "revised"
            ? "REVISED — AWAITING CONFIRMATION"
            : issueConfirmed(issue)
              ? "CONFIRMED"
              : issue.status.toUpperCase(),
        )}
      </StatusPill>
      <p className="mt-2 font-body text-sm font-bold">{issue.requested_correction}</p>
      {issue.evidence.length > 0 && (
        <ul className="space-y-1 font-body text-xs leading-5 text-ink-black/75">
          {issue.evidence.map((item, index) => (
            <li key={`${issue.id}:evidence:${index}`}>{item}</li>
          ))}
        </ul>
      )}
      <p className="font-body text-xs leading-5 text-ink-muted">
        {t("Revision")} {issue.render_revision}
        {issue.resolution_revision ? ` → ${t("Revision")} ${issue.resolution_revision}` : ""}
      </p>
    </div>
  );
}

/** Collapsed history for confirmed/dismissed issues; open findings stay expanded. */
export function ResolvedIssueHistory({ issues }: { issues: PageIssue[] }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  if (issues.length === 0) return null;
  return (
    <div className="border-t border-ink-black/15 pt-3">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="font-meta text-xs font-bold text-ink-muted underline underline-offset-2"
      >
        {open
          ? t("Hide resolved history")
          : t("Show resolved history")}
        {` (${issues.length})`}
      </button>
      {open && (
        <ol className="mt-3 space-y-3">
          {issues.map((issue) => (
            <li key={issue.id}>
              <Surface tone="bristol" border="soft" shadow="none" padding="md">
                {isOcrIssue(issue)
                  ? <LetteringIssueCard issue={issue} />
                  : <PlainIssueCard issue={issue} />}
              </Surface>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
