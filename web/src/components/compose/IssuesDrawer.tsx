import { cn } from "../../lib/cn";
import type { ComposeIssue } from "../../lib/issueEngine";

interface IssuesDrawerProps {
  open: boolean;
  issues: ComposeIssue[];
  onClose: () => void;
  onGoToIssue: (issue: ComposeIssue) => void;
}

const TYPE_LABELS: Record<string, string> = {
  flagged_panel: "FLAGGED FOR RE-WORK",
  missing_image: "MISSING IMAGE",
  empty_bubble_text: "EMPTY TEXT",
  bubble_outside_safe_area: "OUTSIDE SAFE AREA",
  text_too_long: "TEXT TOO LONG",
  low_contrast: "LOW CONTRAST",
};

function IssueRow({
  issue,
  emphasis,
  onGoToIssue,
}: {
  issue: ComposeIssue;
  emphasis: boolean;
  onGoToIssue: (issue: ComposeIssue) => void;
}) {
  return (
    <li
      className={cn(
        "flex items-center gap-3 px-4 py-3",
        emphasis
          ? "border-[2px] border-hero-red bg-hero-red/5"
          : "border-b border-ink-black/10",
      )}
    >
      <div className="min-w-0 flex-1">
        <p className={cn(
          "font-meta text-[0.48rem] tracking-[0.16em]",
          emphasis ? "text-hero-red" : "text-ink-black/50",
        )}>
          {TYPE_LABELS[issue.type] ?? issue.type.toUpperCase()} · PAGE {issue.pageNumber}
        </p>
        <p className="mt-0.5 font-meta text-[0.56rem] tracking-[0.08em] text-ink-black">
          {issue.message}
        </p>
      </div>
      <button
        type="button"
        onClick={() => onGoToIssue(issue)}
        className={cn(
          "shrink-0 border px-2.5 py-1 font-meta text-[0.5rem] tracking-[0.14em] transition-colors",
          emphasis
            ? "border-hero-red bg-hero-red text-bristol hover:bg-hero-red/85"
            : "border-ink-black/30 text-ink-black/60 hover:border-ink-black hover:text-ink-black",
        )}
      >
        FIX →
      </button>
    </li>
  );
}

/**
 * The one issues surface: a triaged right-side drawer — "need you" (errors)
 * vs "suggestions" (warnings) — reachable from the Book header on any tab.
 */
export function IssuesDrawer({ open, issues, onClose, onGoToIssue }: IssuesDrawerProps) {
  if (!open) return null;

  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Issues">
      <div className="absolute inset-0 bg-ink-black/35" onClick={onClose} />
      <aside className="absolute right-0 top-0 flex h-full w-[420px] max-w-[92vw] flex-col border-l-[2px] border-ink-black bg-bristol">
        <div className="flex items-center justify-between border-b-[2px] border-ink-black px-4 py-3">
          <div>
            <div className="font-meta text-[0.5rem] tracking-[0.2em] text-ink-black/45">PRODUCTION CHECK</div>
            <div className="font-display text-[1.2rem] font-bold uppercase leading-tight tracking-[-0.03em]">
              Issues
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close issues"
            className="p-2 text-ink-black/50 transition-colors hover:text-hero-red"
          >
            ✕
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {issues.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-3">
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
                ALL CLEAR — READY TO EXPORT
              </p>
            </div>
          ) : (
            <>
              {errors.length > 0 && (
                <section className="mb-5">
                  <div className="mb-2 font-meta text-[0.56rem] tracking-[0.2em] text-hero-red">
                    NEED YOU · {errors.length}
                  </div>
                  <ul className="space-y-2">
                    {errors.map((issue) => (
                      <IssueRow key={issue.id} issue={issue} emphasis onGoToIssue={onGoToIssue} />
                    ))}
                  </ul>
                </section>
              )}
              {warnings.length > 0 && (
                <section>
                  <div className="mb-2 font-meta text-[0.56rem] tracking-[0.2em] text-ink-black/45">
                    SUGGESTIONS · {warnings.length}
                  </div>
                  <ul>
                    {warnings.map((issue) => (
                      <IssueRow key={issue.id} issue={issue} emphasis={false} onGoToIssue={onGoToIssue} />
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
