import type { ComicPage } from "../../types/api";

interface CommittedPanelReframe {
  panelId: string;
  startOffsetX: number;
  startOffsetY: number;
  dx: number;
  dy: number;
  scale: number;
}

export function panelReframeHasSettled(page: ComicPage, committed: CommittedPanelReframe): boolean {
  const panel = page.panels.find((candidate) => candidate.id === committed.panelId);
  if (!panel) return true;
  const expectedX = Math.round(committed.startOffsetX + committed.dx / committed.scale);
  const expectedY = Math.round(committed.startOffsetY + committed.dy / committed.scale);
  return (panel.image_offset_x ?? 0) === expectedX && (panel.image_offset_y ?? 0) === expectedY;
}
