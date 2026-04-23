import { cn } from "../../lib/cn";

interface SceneItem {
  id: string;
  label: string;
  count: string;
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
                "flex w-full items-stretch border-b border-panel-line text-left last:border-b-0",
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
              <span className="flex-1 px-5 py-5">
                <span className="block font-display text-[1.02rem] font-bold uppercase leading-tight tracking-[0.08em]">
                  {s.label}
                </span>
                <span className={cn(
                  "mt-1.5 block font-body text-[0.9rem] font-semibold",
                  isActive ? "text-bristol/70" : "text-ink-black/45",
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
