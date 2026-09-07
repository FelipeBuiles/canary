import type { PageIssue } from "../../types/api";
import type { VisualFindingIssue, VisualReviewFinding } from "../../api/pages";

export function visualFindingKey(finding: VisualReviewFinding): string {
  return `visual:${finding.category}:${finding.panel_number}:${finding.observation}`;
}

/**
 * Link a finding to its persisted page issue: the envelope's finding_issues
 * entry first (skipped when marked unavailable), then an explicit id, then
 * evidence match as a fallback.
 */
export function visualFindingIssueId(
  finding: VisualReviewFinding,
  findingIndex: number,
  findingIssues: VisualFindingIssue[],
  issues: PageIssue[],
): string | undefined {
  const entry = findingIssues.find((candidate) => candidate.finding_index === findingIndex);
  if (entry && entry.available !== false) {
    const known = issues.find((issue) => issue.id === entry.issue_id);
    if (known) return known.id;
    return entry.issue_id;
  }
  if (finding.issue_id) {
    const known = issues.find((issue) => issue.id === finding.issue_id);
    if (known) return known.id;
    return finding.issue_id;
  }
  const match = issues.find((issue) =>
    issue.issue_type === `visual_${finding.category}`
    && issue.requested_correction === finding.correction
    && issue.evidence.includes(`Panel ${finding.panel_number}: ${finding.observation}`),
  );
  return match?.id;
}
