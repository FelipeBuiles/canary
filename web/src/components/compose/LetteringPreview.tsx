import { useLayoutEffect, useRef } from "react";
import type { LetteringStyle } from "../../types/api";
import { resolveLetteringVars } from "./themes";
import { AutoSpeechTail, BalloonShape } from "./BalloonShape";
import { verifyLetteringSafeAreas } from "./letteringSafeArea";
import "./comic-page.css";

// Render a real-proportioned mini panel at native sizes, then scale the whole
// thing down uniformly. Scaling only the fonts (as before) distorts radii,
// padding, and the thought-bubble puffs — so everything must scale together for
// the preview to match the actual composed page.
const NATIVE_W = 720;
const NATIVE_H = 640;
const SCALE = 0.34;

/**
 * A small, faithful sample panel rendered in the resolved lettering style (real
 * colors, borders, bubble shapes, and typeface). Used in the Look station so the
 * user sees exactly how their book will be lettered before committing.
 */
export function LetteringPreview({ lettering }: { lettering: LetteringStyle | undefined }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const vars = resolveLetteringVars(lettering) as Record<string, string>;

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const verify = () => verifyLetteringSafeAreas(root);
    verify();
    void document.fonts?.ready.then(verify);
  }, [lettering]);

  return (
    <div ref={rootRef} style={{ width: NATIVE_W * SCALE, height: NATIVE_H * SCALE, overflow: "hidden" }}>
      <div
        className="comic-page-root"
        style={{
          ...(vars as React.CSSProperties),
          width: NATIVE_W,
          height: NATIVE_H,
          transform: `scale(${SCALE})`,
          transformOrigin: "top left",
          backgroundColor: vars["--page-bg"],
          fontFamily: vars["--letter-font"],
          padding: 16,
          boxSizing: "border-box",
        }}
      >
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            padding: 22,
            boxSizing: "border-box",
            border: "var(--panel-border-width) solid var(--panel-border)",
            background: vars["--panel-bg"],
            overflow: "hidden",
          }}
        >
          <div className="caption" style={{ position: "absolute", left: 28, top: 28, maxWidth: 620 }}>
            <BalloonShape type="narration" />
            <span className="letter-content">A quiet street, just past midnight.</span>
          </div>
          <div className="bubble speech left tail-down" style={{ position: "absolute", left: 34, top: 225 }}>
            <BalloonShape type="speech" />
            <span className="letter-content">Who&apos;s there?</span>
            <AutoSpeechTail />
          </div>
          <div className="bubble thought" style={{ position: "absolute", right: 32, top: 350, maxWidth: 350 }}>
            <BalloonShape type="thought" />
            <span className="letter-content">…something is wrong.</span>
          </div>
          <div
            className="sfx"
            style={{ left: "50%", bottom: 28, transform: "translateX(-50%) rotate(-4deg)" }}
          >
            KRAK!
          </div>
        </div>
      </div>
    </div>
  );
}
