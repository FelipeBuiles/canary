import type { ComicPage } from "../types/api";
import type { ComposeIssue } from "./issueEngine";

export const LETTERING_WARNING_COVERAGE = 0.25;
export const LETTERING_MAX_COVERAGE = 0.4;
export const LETTERING_MAX_AUTO_STACK = 0.4;

export interface PanelLetteringMetrics {
  pageNumber: number;
  panelId: string;
  panelNumber: number;
  coverageRatio: number;
  maxAutoStackRatio: number;
  overflowingBubbleIds: string[];
}

interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

function issueId(type: ComposeIssue["type"], pageNumber: number, panelId: string, bubbleId?: string): string {
  return [type, pageNumber, panelId, bubbleId ?? ""].join(":");
}

function unionArea(rects: Rect[]): number {
  const xs = [...new Set(rects.flatMap((rect) => [rect.left, rect.right]))].sort((a, b) => a - b);
  let area = 0;
  for (let index = 0; index < xs.length - 1; index += 1) {
    const left = xs[index];
    const right = xs[index + 1];
    if (right <= left) continue;
    const ranges = rects
      .filter((rect) => rect.left < right && rect.right > left)
      .map((rect) => [rect.top, rect.bottom] as const)
      .sort((a, b) => a[0] - b[0]);
    let start: number | undefined;
    let end: number | undefined;
    let covered = 0;
    for (const [top, bottom] of ranges) {
      if (start === undefined || end === undefined) {
        start = top;
        end = bottom;
      } else if (top > end) {
        covered += end - start;
        start = top;
        end = bottom;
      } else {
        end = Math.max(end, bottom);
      }
    }
    if (start !== undefined && end !== undefined) covered += end - start;
    area += (right - left) * covered;
  }
  return area;
}

function toRect(element: Element): Rect {
  const rect = element.getBoundingClientRect();
  return {
    left: rect.left,
    top: rect.top,
    right: rect.right,
    bottom: rect.bottom,
    width: rect.width,
    height: rect.height,
  };
}

function autoStackRatio(group: Element, panelRect: Rect): number {
  const rects = [...group.children]
    .filter((child) => child.matches(".bubble, .caption"))
    .map(toRect)
    .filter((rect) => rect.width > 0 && rect.height > 0);
  if (rects.length === 0 || panelRect.height <= 0) return 0;
  const top = Math.min(...rects.map((rect) => rect.top));
  const bottom = Math.max(...rects.map((rect) => rect.bottom));
  return Math.max(0, bottom - top) / panelRect.height;
}

export function classifyLetteringMetrics(metrics: PanelLetteringMetrics[]): ComposeIssue[] {
  const issues: ComposeIssue[] = [];
  for (const panel of metrics) {
    if (panel.overflowingBubbleIds.length > 0) {
      issues.push({
        id: issueId("lettering_overflow", panel.pageNumber, panel.panelId),
        type: "lettering_overflow",
        severity: "warning",
        message: `Panel ${panel.panelNumber} may have lettering close to its panel edge.`,
        pageNumber: panel.pageNumber,
        panelId: panel.panelId,
        bubbleId: panel.overflowingBubbleIds[0],
      });
    }
    if (panel.coverageRatio > LETTERING_MAX_COVERAGE) {
      issues.push({
        id: issueId("lettering_obscures_art", panel.pageNumber, panel.panelId),
        type: "lettering_obscures_art",
        severity: "error",
        message: `Panel ${panel.panelNumber} lettering covers ${Math.round(panel.coverageRatio * 100)}% of the art area.`,
        pageNumber: panel.pageNumber,
        panelId: panel.panelId,
      });
    } else if (panel.coverageRatio >= LETTERING_WARNING_COVERAGE) {
      issues.push({
        id: issueId("lettering_obscures_art", panel.pageNumber, panel.panelId),
        type: "lettering_obscures_art",
        severity: "warning",
        message: `Panel ${panel.panelNumber} lettering covers ${Math.round(panel.coverageRatio * 100)}% of the art area.`,
        pageNumber: panel.pageNumber,
        panelId: panel.panelId,
      });
    }
    if (panel.maxAutoStackRatio > LETTERING_MAX_AUTO_STACK) {
      issues.push({
        id: issueId("lettering_stack_too_tall", panel.pageNumber, panel.panelId),
        type: "lettering_stack_too_tall",
        severity: "error",
        message: `Panel ${panel.panelNumber} automatic lettering uses ${Math.round(panel.maxAutoStackRatio * 100)}% of the panel height.`,
        pageNumber: panel.pageNumber,
        panelId: panel.panelId,
      });
    }
  }
  return issues;
}

export function measureLetteringIssues(root: Element, page: ComicPage): ComposeIssue[] {
  const panelNumbers = new Map(page.panels.map((panel) => [panel.id, panel.panel_number]));
  const metrics = [...root.querySelectorAll<HTMLElement>(".panel[data-panel-id]")].map((panel) => {
    const panelRect = toRect(panel);
    const lettering = [...panel.querySelectorAll<HTMLElement>(".bubble[data-id], .caption[data-id]")]
      .map((element) => ({ id: element.dataset.id ?? "", rect: toRect(element) }))
      .filter(({ rect }) => rect.width > 0 && rect.height > 0);
    const overflowingBubbleIds = lettering
      .filter(({ rect }) => (
        rect.left < panelRect.left - 0.5 || rect.top < panelRect.top - 0.5 ||
        rect.right > panelRect.right + 0.5 || rect.bottom > panelRect.bottom + 0.5
      ))
      .map(({ id }) => id);
    const groups = [...panel.querySelectorAll(":scope > .captions, :scope > .bubble-auto")];
    return {
      pageNumber: page.page_number,
      panelId: panel.dataset.panelId ?? "",
      panelNumber: panelNumbers.get(panel.dataset.panelId ?? "") ?? 0,
      coverageRatio: panelRect.width > 0 && panelRect.height > 0
        ? unionArea(lettering.map(({ rect }) => rect)) / (panelRect.width * panelRect.height)
        : 0,
      maxAutoStackRatio: groups.length > 0
        ? Math.max(...groups.map((group) => autoStackRatio(group, panelRect)))
        : 0,
      overflowingBubbleIds,
    } satisfies PanelLetteringMetrics;
  });
  return classifyLetteringMetrics(metrics);
}
