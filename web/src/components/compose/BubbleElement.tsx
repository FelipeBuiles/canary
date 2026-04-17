import type { Bubble } from "../../types/api";
import { SvgTail } from "./SvgTail";

interface BubbleElementProps {
  bubble: Bubble;
  selected: boolean;
}

/** Resolve 'auto' tail direction based on bubble position. */
function resolveTailDirection(bubble: Bubble): "up" | "down" {
  if (bubble.tail_direction !== "auto") return bubble.tail_direction;
  if (bubble.y != null && bubble.y < 400) return "down";
  return "up";
}

function bubbleStyle(bubble: Bubble): React.CSSProperties | undefined {
  const style: React.CSSProperties & Record<`--${string}`, string> = {};
  const isPinned = bubble.x != null && bubble.y != null;

  if (isPinned) {
    style.left = `${Math.round(bubble.x!)}px`;
    style.top = `${Math.round(bubble.y!)}px`;
  }
  if (bubble.width != null) style.width = `${Math.round(bubble.width)}px`;
  if (bubble.font_family) style.fontFamily = bubble.font_family;
  if (bubble.font_size != null) style.fontSize = `${Math.round(bubble.font_size)}px`;
  if (bubble.font_color) style.color = bubble.font_color;
  if (bubble.fill_color) {
    style.background = bubble.fill_color;
    style["--bubble-bg"] = bubble.fill_color;
  }
  if (bubble.border_color) {
    style.borderColor = bubble.border_color;
    style["--bubble-border"] = bubble.border_color;
  }
  if (bubble.border_width != null) {
    const width = `${Math.round(bubble.border_width)}px`;
    style.borderWidth = width;
    style["--bubble-border-width"] = width;
  }
  if (bubble.border_radius != null) style.borderRadius = `${Math.round(bubble.border_radius)}px`;

  return Object.keys(style).length > 0 ? style : undefined;
}

/**
 * Unified bubble renderer — handles auto and pinned, all types.
 * Mirrors Python html_renderer._bubble_html().
 * Selection and drag are handled by the parent via event delegation on data-id.
 */
export function BubbleElement({ bubble, selected }: BubbleElementProps) {
  const isPinned = bubble.x != null && bubble.y != null;
  const isNarration = bubble.type === "narration";
  const hasSvgTail = bubble.tail_x != null && bubble.tail_y != null;

  // Build class list
  const classes: string[] = [];
  if (isNarration && !isPinned) {
    classes.push("caption");
  } else {
    classes.push("bubble", bubble.type, bubble.side);
  }

  if (isPinned) classes.push("pinned");
  if (hasSvgTail) classes.push("svg-tail");
  else if (bubble.type === "speech") classes.push(`tail-${resolveTailDirection(bubble)}`);
  if (selected) classes.push("selected");

  return (
    <div
      className={classes.join(" ")}
      data-id={bubble.id}
      data-editor-selectable
      style={bubbleStyle(bubble)}
    >
      {bubble.speaker_name && (
        <span className="speaker">{bubble.speaker_name}:</span>
      )}
      {bubble.text}
      {hasSvgTail && <SvgTail bubble={bubble} />}
    </div>
  );
}
