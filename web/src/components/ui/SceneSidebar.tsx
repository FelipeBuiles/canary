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
      <div className="px-4 py-3 font-meta text-[0.56rem] tracking-[0.22em] text-ink-black/45">
        SCENE
      </div>
      <div>
        {items.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              "w-full border-t border-panel-line px-4 py-4 text-left transition-colors last:border-b",
              s.id === activeId
                ? "bg-hero-red text-bristol"
                : "bg-bristol text-ink-black hover:bg-pulp-paper",
            )}
          >
            <div className="font-meta text-[0.66rem] tracking-[0.16em]">
              {s.label}
            </div>
            <div className="mt-1 font-body text-[0.74rem] opacity-70">
              {s.count}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
