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
    <div className="h-full bg-bristol">
      <div className="border-b-[2px] border-ink-black px-4 py-2 font-meta text-[0.5rem] tracking-[0.22em] text-ink-black/45">
        SCENE
      </div>
      <div>
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
              <span className="flex-1 px-4 py-3">
                <span className="block font-display text-[0.78rem] font-bold uppercase leading-tight tracking-[-0.02em]">
                  {s.label}
                </span>
                <span className={cn(
                  "mt-0.5 block font-meta text-[0.52rem] tracking-[0.12em]",
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
