import type { ComicPage } from "../../types/api";
import { PanelCell } from "./PanelCell";
import { getLayout } from "./layouts";
import { resolveThemeVars } from "./themes";

interface ComicPageCanvasProps {
  page: ComicPage;
  selectedElementId: string | null;
  selectedType: "bubble" | "sfx" | null;
  imageBaseUrl: string;
}

/**
 * Full page renderer at 2480x3508 native size.
 * The parent ScaledContainer handles viewport scaling.
 * Events are handled by PageEditor via event delegation.
 */
export function ComicPageCanvas({
  page,
  selectedElementId,
  selectedType,
  imageBaseUrl,
}: ComicPageCanvasProps) {
  const layout = getLayout(page.layout);
  const vars = { ...resolveThemeVars(page.theme), ...(page.style_vars ?? {}) };

  // Apply CSS variables as inline styles for the page root
  const cssVars = vars as unknown as React.CSSProperties;

  return (
    <div
      className="comic-page-root"
      style={{
        width: 2480,
        height: 3508,
        background: vars["--page-bg"],
        overflow: "hidden",
        position: "relative",
        fontFamily: "'ComicNeue', 'Comic Neue', cursive, sans-serif",
        ...cssVars,
      }}
    >
      <div
        className="comic-page"
        style={{
          ...layout.gridStyle,
        }}
      >
        {page.panels.map((panel, i) => (
          <PanelCell
            key={panel.id}
            panel={panel}
            panelIndex={i}
            layoutId={page.layout}
            selectedElementId={selectedElementId}
            selectedType={selectedType}
            imageBaseUrl={imageBaseUrl}
          />
        ))}
      </div>
      <div className="page-number">{page.page_number}</div>
    </div>
  );
}
