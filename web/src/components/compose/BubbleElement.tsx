import { useLayoutEffect, useRef } from "react";
import type { Bubble } from "../../types/api";
import { BalloonShape } from "./BalloonShape";
import { verifyLetteringSafeArea } from "./letteringSafeArea";
import { SpeakerTail } from "./SvgTail";

interface BubbleElementProps {
  bubble: Bubble;
  selected: boolean;
}

function bubbleStyle(bubble: Bubble): React.CSSProperties | undefined {
  const style: React.CSSProperties & Record<`--${string}`, string> = {};
  const isPinned = bubble.x != null && bubble.y != null;
  const isNarration = bubble.type === "narration";

  if (isPinned) {
    style.left = `${Math.round(Math.max(8, bubble.x!))}px`;
    style.top = `${Math.round(Math.max(8, bubble.y!))}px`;
  }
  if (bubble.width != null) style.width = `${Math.round(bubble.width)}px`;
  if (bubble.font_family) style.fontFamily = bubble.font_family;
  if (bubble.font_size != null) style.fontSize = `${Math.round(bubble.font_size)}px`;
  if (bubble.font_color) style.color = bubble.font_color;
  if (bubble.fill_color) {
    style[isNarration ? "--caption-bg" : "--bubble-bg"] = bubble.fill_color;
  }
  if (bubble.border_color) {
    style[isNarration ? "--caption-border" : "--bubble-border"] = bubble.border_color;
  }
  if (bubble.border_width != null) {
    const width = `${Math.round(bubble.border_width)}px`;
    style[isNarration ? "--caption-border-width" : "--bubble-border-width"] = width;
  }
  return Object.keys(style).length > 0 ? style : undefined;
}

function fitPinnedElement(host: HTMLElement) {
  const panel = host.closest<HTMLElement>(".panel");
  if (!panel) return;
  const gutter = 8;
  const maxLeft = Math.max(gutter, panel.clientWidth - host.offsetWidth - gutter);
  const maxTop = Math.max(gutter, panel.clientHeight - host.offsetHeight - gutter);
  host.style.left = `${Math.min(maxLeft, Math.max(gutter, host.offsetLeft))}px`;
  host.style.top = `${Math.min(maxTop, Math.max(gutter, host.offsetTop))}px`;
}

/**
 * Unified bubble renderer — handles auto and pinned, all types.
 * Mirrors Python html_renderer._bubble_html().
 * Selection and drag are handled by the parent via event delegation on data-id.
 */
export function BubbleElement({ bubble, selected }: BubbleElementProps) {
  const ref = useRef<HTMLDivElement>(null);
  const isPinned = bubble.x != null && bubble.y != null;
  const isNarration = bubble.type === "narration";

  // Build class list
  const classes: string[] = [];
  if (isNarration) {
    classes.push("caption", bubble.type);
  } else {
    classes.push("bubble", bubble.type, bubble.side);
  }

  if (isPinned) classes.push("pinned");
  if (bubble.full_width) classes.push("full-width");
  if (selected) classes.push("selected");

  useLayoutEffect(() => {
    const host = ref.current;
    if (!host) return;
    let active = true;
    const fit = () => {
      if (!active) return;
      if (isPinned) fitPinnedElement(host);
      verifyLetteringSafeArea(host);
    };
    fit();
    void document.fonts?.ready.then(fit);
    return () => {
      active = false;
    };
  }, [
    bubble.type,
    bubble.text,
    bubble.speaker_name,
    bubble.x,
    bubble.y,
    bubble.width,
    bubble.font_family,
    bubble.font_size,
    isPinned,
  ]);

  return (
    <div
      ref={ref}
      className={classes.join(" ")}
      data-id={bubble.id}
      data-editor-selectable
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={`${bubble.type} bubble: ${bubble.text}`}
      style={bubbleStyle(bubble)}
    >
      <BalloonShape type={bubble.type} />
      <span className="letter-content">
        {bubble.speaker_name && !isNarration && (
          <span className="speaker">{bubble.speaker_name}:</span>
        )}
        {bubble.text}
      </span>
      {!isNarration && <SpeakerTail bubble={bubble} selected={selected} />}
    </div>
  );
}
