import { cn } from "../../lib/cn";
import { Surface } from "./Surface";

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
    <Surface padding="sm" shadow="paper-sm">
      <div className="mb-3 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45">
        SCENES
      </div>
      <div className="space-y-1">
        {items.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              "w-full border-[2px] border-ink-black px-3 py-2 text-left font-body text-[0.78rem]",
              s.id === activeId
                ? "bg-hero-red text-bristol"
                : "bg-pulp-paper text-ink-black hover:bg-ghost-shadow",
            )}
          >
            <div className="font-display text-[0.72rem] font-bold tracking-[-0.03em]">
              {s.label}
            </div>
            <div className="mt-0.5 font-meta text-[0.46rem] tracking-[0.14em] opacity-70">
              {s.count}
            </div>
          </button>
        ))}
      </div>
    </Surface>
  );
}
