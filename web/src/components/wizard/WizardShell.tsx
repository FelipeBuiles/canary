import type { ReactNode } from "react";
import type { StageName } from "../../types/api";
import { STAGE_ORDER, STAGE_DISPLAY_NAMES } from "../../types/api";

type StepState = "pending" | "running" | "review" | "done";

interface WizardShellProps {
  steps: Partial<Record<StageName, StepState>>;
  children: ReactNode;
}

function stepIndicator(state: StepState) {
  if (state === "done") return "bg-archive-sage text-bristol border-ink-black";
  if (state === "running") return "bg-narrator-gold text-ink-black border-ink-black animate-pulse";
  if (state === "review") return "bg-hero-red text-bristol border-ink-black";
  return "bg-pulp-paper text-ink-black/40 border-ink-black/30";
}

export function WizardShell({ steps, children }: WizardShellProps) {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-1">
        {STAGE_ORDER.map((stage, i) => {
          const state = steps[stage] ?? "pending";
          return (
            <div key={stage} className="flex items-center">
              {i > 0 && (
                <div className={`h-[2px] w-4 ${state === "pending" ? "bg-ink-black/20" : "bg-ink-black"}`} />
              )}
              <div
                className={`border-[2px] px-2 py-1 font-meta text-[0.4rem] tracking-[0.14em] ${stepIndicator(state)}`}
                title={STAGE_DISPLAY_NAMES[stage]}
              >
                {STAGE_DISPLAY_NAMES[stage]}
              </div>
            </div>
          );
        })}
      </div>
      <div>{children}</div>
    </div>
  );
}
