import type { PagePanel } from "../../types/api";
import { PanelImage } from "./PanelImage";
import { BubbleElement } from "./BubbleElement";
import { SfxElement } from "./SfxElement";
import { resolveGridPlacement } from "./layouts";

interface PanelCellProps {
  panel: PagePanel;
  panelIndex: number;
  layoutId: string;
  layoutMode: "grid" | "freeform";
  selectedPanelId: string | null;
  selectedElementId: string | null;
  selectedType: "bubble" | "sfx" | null;
  imageBaseUrl: string;
}

/**
 * One panel cell in the grid — composes image + bubbles + SFX.
 * Mirrors Python html_renderer._panel_html().
 * Pointer events are handled by the parent PageEditor via event delegation.
 */
export function PanelCell({
  panel,
  panelIndex,
  layoutId,
  layoutMode,
  selectedPanelId,
  selectedElementId,
  selectedType,
  imageBaseUrl,
}: PanelCellProps) {
  const gridStyle =
    layoutMode === "grid"
      ? resolveGridPlacement(layoutId, panelIndex, panel.grid_column, panel.grid_row)
      : {};
  const freeformStyle: React.CSSProperties =
    layoutMode === "freeform"
      ? {
          ...(panel.x != null ? { left: `${Math.round(panel.x)}px` } : {}),
          ...(panel.y != null ? { top: `${Math.round(panel.y)}px` } : {}),
          ...(panel.width != null ? { width: `${Math.round(panel.width)}px` } : {}),
          ...(panel.height != null ? { height: `${Math.round(panel.height)}px` } : {}),
          ...(panel.z_index != null ? { zIndex: panel.z_index } : {}),
          ...(panel.clip_path
            ? { clipPath: panel.clip_path, WebkitClipPath: panel.clip_path }
            : {}),
          position: "absolute",
        }
      : {};

  // Separate bubbles into categories — mirrors Python _panel_html()
  const autoNarration = panel.bubbles.filter(
    (b) => b.type === "narration" && b.x == null,
  );
  const autoSpeech = panel.bubbles.filter(
    (b) => b.type !== "narration" && b.x == null,
  );
  const pinned = panel.bubbles.filter((b) => b.x != null);

  const imageSrc = `${imageBaseUrl}/${panel.image_path}`;

  return (
    <div
      className={`panel${selectedPanelId === panel.id ? " panel-active" : ""}`}
      data-panel-id={panel.id}
      style={{ ...gridStyle, ...freeformStyle }}
    >
      <PanelImage
        src={imageSrc}
        imageOffsetX={panel.image_offset_x}
        imageOffsetY={panel.image_offset_y}
      />

      {/* Auto narration → .captions container at top */}
      {autoNarration.length > 0 && (
        <div className="captions">
          {autoNarration.map((b) => (
            <BubbleElement
              key={b.id}
              bubble={b}
              selected={selectedType === "bubble" && selectedElementId === b.id}
            />
          ))}
        </div>
      )}

      {/* Auto speech/thought → .bubble-auto flex container at bottom */}
      {autoSpeech.length > 0 && (
        <div className="bubble-auto">
          {autoSpeech.map((b) => (
            <BubbleElement
              key={b.id}
              bubble={b}
              selected={selectedType === "bubble" && selectedElementId === b.id}
            />
          ))}
        </div>
      )}

      {/* Pinned bubbles → absolute within panel */}
      {pinned.map((b) => (
        <BubbleElement
          key={b.id}
          bubble={b}
          selected={selectedType === "bubble" && selectedElementId === b.id}
        />
      ))}

      {/* SFX */}
      {panel.sfx && (
        <SfxElement
          sfx={panel.sfx}
          panelId={panel.id}
          selected={selectedType === "sfx" && selectedElementId === `${panel.id}__sfx`}
        />
      )}

      {/* Panel ID debug label */}
      <div className="panel-id" data-panel-id={panel.id}>
        {panel.scene_id}/{panel.panel_number}
      </div>
    </div>
  );
}
