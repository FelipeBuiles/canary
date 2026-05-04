import { cn } from "../../lib/cn";
import type { ComposeIssue } from "../../lib/issueEngine";

interface IssueModeProps {
  issues: ComposeIssue[];
  onGoToIssue: (issue: ComposeIssue) => void;
}

const TYPE_LABELS: Record<string, string> = {
  unaccepted_panel: "UNACCEPTED",
  missing_image: "MISSING IMAGE",
  empty_bubble_text: "EMPTY BUBBLE",
  bubble_outside_safe_area: "OUTSIDE SAFE AREA",
  text_too_long: "TEXT TOO LONG",
  low_contrast: "LOW CONTRAST",
};

export function IssueMode({ issues, onGoToIssue }: IssueModeProps) {
  const hasIssues = issues.length > 0;
  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warnCount = issues.filter((i) => i.severity === "warning").length;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex shrink-0 items-baseline gap-3 border-b-[2px] border-ink-black px-6 py-3">
        {hasIssues ? (
          <>
            <span className="font-display text-sm font-bold tracking-[0.18em] text-ink-black">
              {issues.length} ISSUE{issues.length !== 1 ? "S" : ""} FOUND
            </span>
            {errorCount > 0 && (
              <span className="font-meta text-[0.5rem] tracking-[0.14em] text-hero-red">
                {errorCount} ERROR{errorCount !== 1 ? "S" : ""}
              </span>
            )}
            {warnCount > 0 && (
              <span className="font-meta text-[0.5rem] tracking-[0.14em] text-narrator-gold">
                {warnCount} WARNING{warnCount !== 1 ? "S" : ""}
              </span>
            )}
          </>
        ) : (
          <span className="font-display text-sm font-bold tracking-[0.18em] text-archive-sage">
            ALL CLEAR
          </span>
        )}
      </div>

      {/* Issue list or empty state */}
      {hasIssues ? (
        <ul className="flex-1 overflow-y-auto">
          {issues.map((issue) => (
            <li
              key={issue.id}
              className="flex items-center gap-3 border-b border-ink-black/10 px-6 py-3 hover:bg-ink-black/5"
            >
              {/* Severity dot */}
              <span
                className={cn(
                  "h-2 w-2 shrink-0 rounded-full",
                  issue.severity === "error" ? "bg-hero-red" : "bg-narrator-gold",
                )}
              />

              {/* Type + message */}
              <div className="min-w-0 flex-1">
                <p className="font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/50">
                  {TYPE_LABELS[issue.type] ?? issue.type.toUpperCase()}
                </p>
                <p className="mt-0.5 font-meta text-[0.56rem] tracking-[0.08em] text-ink-black">
                  {issue.message}
                </p>
              </div>

              {/* Page badge + go button */}
              <div className="flex shrink-0 items-center gap-2">
                <span className="font-meta text-[0.48rem] tracking-[0.14em] text-ink-black/40">
                  P.{issue.pageNumber}
                </span>
                <button
                  type="button"
                  onClick={() => onGoToIssue(issue)}
                  className="border border-ink-black/30 px-2 py-0.5 font-meta text-[0.46rem] tracking-[0.14em] text-ink-black/60 transition-colors hover:border-ink-black hover:text-ink-black"
                >
                  GO →
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-10 w-10 text-archive-sage"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M20 6L9 17l-5-5" />
          </svg>
          <p className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/40">
            NO ISSUES DETECTED. READY TO EXPORT.
          </p>
        </div>
      )}
    </div>
  );
}
