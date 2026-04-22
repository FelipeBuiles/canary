import type { Sfx } from "../../types/api";

interface SfxElementProps {
  sfx: Sfx;
  panelId: string;
  selected: boolean;
}

/**
 * SFX renderer with rotation.
 * Mirrors Python html_renderer SFX rendering.
 * Selection and drag are handled by the parent via event delegation on data-sfx.
 */
export function SfxElement({ sfx, panelId, selected }: SfxElementProps) {
  const isPinned = sfx.x != null && sfx.y != null;

  const classes = ["sfx"];
  if (isPinned) classes.push("pinned");
  if (selected) classes.push("selected");

  const style: React.CSSProperties = {};
  if (isPinned) {
    style.left = `${Math.round(sfx.x!)}px`;
    style.top = `${Math.round(sfx.y!)}px`;
    style.transform = `rotate(${sfx.rotation}deg)`;
  } else if (sfx.rotation !== -4) {
    style.transform = `translateX(-50%) rotate(${sfx.rotation}deg)`;
  }
  if (sfx.font_size != null) {
    style.fontSize = `${sfx.font_size}px`;
  }

  return (
    <div
      className={classes.join(" ")}
      data-sfx={panelId}
      data-editor-selectable
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={`SFX: ${sfx.text}`}
      style={Object.keys(style).length > 0 ? style : undefined}
    >
      {sfx.text.toUpperCase()}
    </div>
  );
}
