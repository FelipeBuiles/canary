import { useState } from "react";
import { useI18n } from "../../i18n";
import type { PageIssue } from "../../types/api";
import { StatusPill } from "../ui/StatusPill";
import { Surface } from "../ui/Surface";
import {
  alignChars,
  alignLettering,
  cropLeadingContext,
  cropMiddleContext,
  cropTrailingContext,
  cropCheckStatus,
  isOcrIssue,
  issueConfirmed,
  ocrIssueTitle,
  readTextEvidence,
  type SegmentDifference,
} from "./lettering";

function DifferenceRow({ difference, secondaryRead = false }: { difference: SegmentDifference; secondaryRead?: boolean }) {
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
        <span className="font-bold">{t("Expected:")} </span>
        {renderSide("expected")}
      </p>
      <p>
        <span className="font-bold">{t(secondaryRead ? "First read:" : "Found:")} </span>
        {renderSide("recognized")}
      </p>
    </li>
  );
}

/**
 * One OCR finding: compact multi-difference summary plus full evidence
 * disclosure. The exact comparison policy is unchanged; every segment pair
 * is shown instead of only the first.
 */
export function LetteringIssueCard({ issue }: { issue: PageIssue }) {
  const { t } = useI18n();
  const expected = readTextEvidence(issue, "expected_text=");
  const recognized = readTextEvidence(issue, "recognized_text=");
  const closeUp = readTextEvidence(issue, "crop_recognized_text=");
  const cropStatus = cropCheckStatus(issue);
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
        <p className="mt-1 font-body text-xs leading-5 text-ink-black/75">
          {t(cropStatus === "disagrees"
            ? "The text checks disagree. Compare the saved artwork with the script before making changes."
            : cropStatus === "inconclusive"
              ? "The close-up text check was inconclusive. Compare the saved artwork with the script before making changes."
              : "Possible wording difference. The checker can misread text; compare it with the saved artwork before making changes.")}
        </p>
      </div>
      {(expected || recognized) && (
        <details>
        <summary className="cursor-pointer py-2 font-meta text-xs font-bold">{t("Full text comparison")}</summary>
        <dl className="grid gap-2 font-body text-xs leading-5">
          {expected && (
            <div>
              <dt className="font-meta font-bold text-ink-muted">{t("EXPECTED SCRIPT")}</dt>
              <dd>{expected.join(" · ") || t("No lettering")}</dd>
            </div>
          )}
          {recognized && (
            <div>
              <dt className="font-meta font-bold text-ink-muted">{t("CHECKER READ")}</dt>
              <dd>{recognized.join(" · ") || t("No readable lettering found")}</dd>
            </div>
          )}
          {closeUp && (
            <div>
              <dt className="font-meta font-bold text-ink-muted">{t("CLOSE-UP READ")}</dt>
              <dd>{closeUp.join(" · ") || t("No readable lettering found")}</dd>
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
                <DifferenceRow key={`${row.type}:${index}`} difference={row} secondaryRead={cropStatus !== null} />
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
      {closeUp && closeUp.length > 0 && (
        <div className="font-body text-xs leading-5">
          <p className="font-bold">{t("CLOSE-UP READ")}</p>
          <ul className="mt-1 space-y-1">{closeUp.map((text, index) => <li key={index}>{text}</li>)}</ul>
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
