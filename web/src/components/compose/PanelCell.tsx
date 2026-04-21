import type { PagePanel } from "../../types/api";
import { PanelImage } from "./PanelImage";
import { BubbleElement } from "./BubbleElement";
import { SfxElement } from "./SfxElement";
import { resolveGridPlacement } from "./layouts";

interface PanelCellProps {
  panel: PagePanel;
  panelIndex: number;
  layoutId: string;
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
  selectedElementId,
  selectedType,
  imageBaseUrl,
}: PanelCellProps) {
  const gridStyle = resolveGridPlacement(
    layoutId,
    panelIndex,
    panel.grid_column,
    panel.grid_row,
  );

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
      className="panel"
      data-panel-id={panel.id}
      style={gridStyle}
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
