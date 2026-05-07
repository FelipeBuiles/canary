import type { Sfx } from "../../types/api";

interface SfxElementProps {
  sfx: Sfx;
  panelId: string;
  index: number;
  selected: boolean;
}

const AUTO_ANCHORS = [
  "bottom-center",
  "top-right",
  "top-left",
  "bottom-right",
  "bottom-left",
  "top-center",
] as const;
const AUTO_ROTATIONS = [-4, 6, -8, 3, -2, 5];

/**
 * SFX renderer.
 * Mirrors Python html_renderer SFX rendering: kind/intensity/anchor classes
 * with auto-cycling for non-pinned SFX so they don't all stack at the same
 * spot. Selection and drag are handled by the parent via event delegation
 * on data-sfx.
 */
export function SfxElement({ sfx, panelId, index, selected }: SfxElementProps) {
  const isPinned = sfx.x != null && sfx.y != null;
  const kind = sfx.kind ?? "impact";
  const intensity = sfx.intensity ?? 2;

  const classes = ["sfx", `kind-${kind}`, `intensity-${intensity}`];

  const style: React.CSSProperties = {};
  if (isPinned) {
    classes.push("pinned");
    style.left = `${Math.round(sfx.x!)}px`;
    style.top = `${Math.round(sfx.y!)}px`;
    style.transform = `rotate(${sfx.rotation}deg)`;
  } else {
    const anchor =
      sfx.anchor && sfx.anchor !== "auto"
        ? sfx.anchor
        : AUTO_ANCHORS[index % AUTO_ANCHORS.length];
    classes.push(`anchor-${anchor}`);
    const rot =
      sfx.rotation !== -4 ? sfx.rotation : AUTO_ROTATIONS[index % AUTO_ROTATIONS.length];
    (style as React.CSSProperties & Record<string, string>)["--sfx-rotation"] = `${rot}deg`;
  }
  if (sfx.font_size != null) {
    style.fontSize = `${sfx.font_size}px`;
  }
  if (selected) classes.push("selected");

  return (
    <div
      className={classes.join(" ")}
      data-sfx={panelId}
      data-sfx-index={index}
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
