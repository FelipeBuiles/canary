import type { LetteringStyle } from "../../types/api";
import { resolveLetteringVars } from "./themes";
import "./comic-page.css";

/**
 * A small, self-contained sample panel rendered in the resolved lettering style
 * (real colors, borders, bubble shapes, and typeface). Used in the Look station
 * so the user sees exactly how their book will be lettered before committing.
 *
 * Font-size vars are shrunk to fit the thumbnail; everything else (the look)
 * comes straight from the project lettering style, so this matches the book.
 */
export function LetteringPreview({ lettering }: { lettering: LetteringStyle | undefined }) {
  const resolved = resolveLetteringVars(lettering) as Record<string, string>;
  const vars = {
    ...resolved,
    "--caption-font-size": "13px",
    "--bubble-font-size": "15px",
    "--sfx-font-size": "24px",
    "--speaker-font-size": "8px",
  } as React.CSSProperties;

  return (
    <div
      className="comic-page-root"
      style={{
        ...vars,
        background: resolved["--page-bg"],
        fontFamily: resolved["--letter-font"],
        padding: 10,
      }}
    >
      <div
        style={{
          position: "relative",
          display: "flex",
          flexDirection: "column",
          gap: 10,
          padding: "12px 12px 18px",
          minHeight: 168,
          border: "var(--panel-border-width) solid var(--panel-border)",
          background: resolved["--panel-bg"],
        }}
      >
        <div className="caption" style={{ position: "static", alignSelf: "flex-start" }}>
          A quiet street, just past midnight.
        </div>
        <div className="bubble speech left tail-up" style={{ alignSelf: "flex-start", marginTop: 18 }}>
          Who&apos;s there?
        </div>
        <div className="bubble thought right" style={{ alignSelf: "flex-end" }}>
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
  );
}
