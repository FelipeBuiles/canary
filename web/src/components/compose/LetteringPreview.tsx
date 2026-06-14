import type { LetteringStyle } from "../../types/api";
import { resolveLetteringVars } from "./themes";
import "./comic-page.css";

// Render a real-proportioned mini panel at native sizes, then scale the whole
// thing down uniformly. Scaling only the fonts (as before) distorts radii,
// padding, and the thought-bubble puffs — so everything must scale together for
// the preview to match the actual composed page.
const NATIVE_W = 720;
const NATIVE_H = 520;
const SCALE = 0.34;

/**
 * A small, faithful sample panel rendered in the resolved lettering style (real
 * colors, borders, bubble shapes, and typeface). Used in the Look station so the
 * user sees exactly how their book will be lettered before committing.
 */
export function LetteringPreview({ lettering }: { lettering: LetteringStyle | undefined }) {
  const vars = resolveLetteringVars(lettering) as Record<string, string>;

  return (
    <div style={{ width: NATIVE_W * SCALE, height: NATIVE_H * SCALE, overflow: "hidden" }}>
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
            display: "flex",
            flexDirection: "column",
            gap: 18,
            width: "100%",
            height: "100%",
            padding: 22,
            boxSizing: "border-box",
            border: "var(--panel-border-width) solid var(--panel-border)",
            background: vars["--panel-bg"],
          }}
        >
          <div className="caption" style={{ position: "static", alignSelf: "flex-start" }}>
            A quiet street, just past midnight.
          </div>
          <div className="bubble speech left tail-up" style={{ alignSelf: "flex-start", marginTop: 22 }}>
            Who&apos;s there?
          </div>
          <div className="bubble thought" style={{ alignSelf: "flex-end" }}>
            …something is wrong.
          </div>
          <div
            className="sfx"
            style={{ position: "static", alignSelf: "center", marginTop: "auto", transform: "rotate(-4deg)" }}
          >
            KRAK!
          </div>
        </div>
      </div>
    </div>
  );
}
