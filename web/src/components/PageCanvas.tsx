import type { ComicPage } from "../types/api";

interface PageCanvasProps {
  page: ComicPage;
  projectName: string;
}

export function PageCanvas({ page, projectName }: PageCanvasProps) {
  const colCount = page.layout === "1" ? 1 : page.layout === "2" ? 2 : 2;

  return (
    <div className="border-[2px] border-ink-black bg-ink-black p-3">
      <div className="font-meta text-[0.5rem] tracking-[0.18em] text-bristol/62 mb-3">
        PAGE {String(page.page_number).padStart(2, "0")}
      </div>
      <div
        className="grid gap-[3px] bg-ink-black"
        style={{
          gridTemplateColumns: `repeat(${colCount}, 1fr)`,
        }}
      >
        {page.panels.map((panel) => {
          const imageUrl = `/api/projects/${encodeURIComponent(projectName)}/files/${panel.image_path}`;
          return (
            <div
              key={panel.id}
              className="relative border border-bristol/30 bg-[#24261d] overflow-hidden"
              style={{
                gridColumn: panel.grid_column ?? undefined,
                gridRow: panel.grid_row ?? undefined,
              }}
            >
              <img
                src={imageUrl}
                alt={`Panel ${panel.panel_number}`}
                className="h-full w-full object-cover"
              />

              {/* Bubbles overlay */}
              {panel.bubbles.map((bubble) => (
                <div
                  key={bubble.id}
                  className={`absolute max-w-[70%] rounded-sm border-2 border-ink-black px-2 py-1 text-[0.55rem] leading-4 ${
                    bubble.type === "narration"
                      ? "bg-bristol text-ink-black"
                      : bubble.type === "thought"
                        ? "bg-bristol text-ink-black border-dashed"
                        : "bg-bristol text-ink-black"
                  }`}
                  style={
                    bubble.x != null && bubble.y != null
                      ? { left: `${bubble.x}px`, top: `${bubble.y}px` }
                      : undefined
                  }
                >
                  {bubble.text}
                </div>
              ))}

              {/* SFX overlay */}
              {panel.sfx && (
                <div
                  className="absolute font-display font-bold text-hero-red"
                  style={{
                    fontSize: panel.sfx.font_size ? `${panel.sfx.font_size}px` : "1.2rem",
                    transform: `rotate(${panel.sfx.rotation ?? -4}deg)`,
                    ...(panel.sfx.x != null && panel.sfx.y != null
                      ? { left: `${panel.sfx.x}px`, top: `${panel.sfx.y}px` }
                      : { bottom: "18%", left: "50%", transform: `translateX(-50%) rotate(${panel.sfx.rotation ?? -4}deg)` }),
                  }}
                >
                  {panel.sfx.text.toUpperCase()}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
