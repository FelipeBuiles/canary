import { cn } from "../../lib/cn";

interface SceneItem {
  id: string;
  label: string;
  count: string;
  /** Optional scene title from the story bible (e.g. "The Death"). */
  sceneTitle?: string | null;
  /** Green dot if the scene is fully complete. */
  isComplete?: boolean;
}

interface SceneSidebarProps {
  items: SceneItem[];
  activeId: string;
  onSelect: (id: string) => void;
}

export function SceneSidebar({
  items,
  activeId,
  onSelect,
}: SceneSidebarProps) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-bristol">
      <div className="shrink-0 border-b border-panel-line px-5 py-4 font-meta text-[0.68rem] tracking-[0.22em] text-ink-black/45">
        SCENE
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {items.map((s) => {
          const isActive = s.id === activeId;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => onSelect(s.id)}
              className={cn(
                "flex w-full min-w-0 items-stretch overflow-hidden border-b border-panel-line text-left last:border-b-0",
                isActive
                  ? "bg-hero-red text-bristol"
                  : "bg-bristol text-ink-black hover:bg-pulp-paper",
              )}
            >
              {/* Left accent bar */}
              <span
                className={cn(
                  "w-1 shrink-0",
                  isActive ? "bg-ink-black/30" : "bg-transparent",
                )}
              />
              <span className="min-w-0 flex-1 overflow-hidden px-5 py-4">
                <span className="flex items-center gap-1.5">
                  <span className="font-meta text-[0.62rem] font-bold uppercase tracking-[0.14em]">
                    {s.label}
                  </span>
                  {s.isComplete && (
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-archive-sage" aria-label="Complete" />
                  )}
                </span>
                {s.sceneTitle && (
                  <span className={cn(
                    "mt-0.5 block truncate font-body text-[0.72rem] font-medium",
                    isActive ? "text-bristol/85" : "text-ink-black/68",
                  )}>
                    {s.sceneTitle}
                  </span>
                )}
                <span className={cn(
                  "mt-1 block font-meta text-[0.62rem] tracking-[0.06em]",
                  isActive ? "text-bristol/55" : "text-ink-black/40",
                )}>
                  {s.count}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
