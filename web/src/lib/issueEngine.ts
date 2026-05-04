import type { ComicPage, ImageStatus } from "../types/api";

export type IssueSeverity = "error" | "warning";

export type IssueType =
  | "unaccepted_panel"
  | "missing_image"
  | "empty_bubble_text"
  | "bubble_outside_safe_area"
  | "text_too_long"
  | "low_contrast";

export interface ComposeIssue {
  id: string;
  type: IssueType;
  severity: IssueSeverity;
  message: string;
  pageNumber: number;
  panelId?: string;
  bubbleId?: string;
}

const PAGE_W = 2480;
const PAGE_H = 3508;
const SAFE_X = PAGE_W * 0.05; // 124
const SAFE_Y = PAGE_H * 0.05; // 175

function issueId(type: IssueType, pageNumber: number, panelId?: string, bubbleId?: string): string {
  return [type, pageNumber, panelId ?? "", bubbleId ?? ""].join(":");
}

function parseHex(color: string): [number, number, number] | null {
  const s = color.trim().replace(/^#/, "");
  if (s.length === 3) {
    const r = parseInt(s[0] + s[0], 16);
    const g = parseInt(s[1] + s[1], 16);
    const b = parseInt(s[2] + s[2], 16);
    if (isNaN(r) || isNaN(g) || isNaN(b)) return null;
    return [r, g, b];
  }
  if (s.length === 6) {
    const r = parseInt(s.slice(0, 2), 16);
    const g = parseInt(s.slice(2, 4), 16);
    const b = parseInt(s.slice(4, 6), 16);
    if (isNaN(r) || isNaN(g) || isNaN(b)) return null;
    return [r, g, b];
  }
  return null;
}

function relativeLuminance(r: number, g: number, b: number): number {
  const toLinear = (c: number) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

export function contrastRatio(hex1: string, hex2: string): number {
  const c1 = parseHex(hex1);
  const c2 = parseHex(hex2);
  if (!c1 || !c2) return Infinity;
  const l1 = relativeLuminance(...c1);
  const l2 = relativeLuminance(...c2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

function checkUnacceptedPanels(pages: ComicPage[], imageMap: Map<string, ImageStatus>): ComposeIssue[] {
  const issues: ComposeIssue[] = [];
  for (const page of pages) {
    for (const panel of page.panels) {
      const key = `${panel.scene_id}-${panel.panel_number}`;
      const status = imageMap.get(key);
      if (status && status.status === "done" && status.accepted === false) {
        issues.push({
          id: issueId("unaccepted_panel", page.page_number, panel.id),
          type: "unaccepted_panel",
          severity: "warning",
          message: `Panel ${panel.panel_number} image has not been accepted.`,
          pageNumber: page.page_number,
          panelId: panel.id,
        });
      }
    }
  }
  return issues;
}

function checkMissingImages(pages: ComicPage[], imageMap: Map<string, ImageStatus>): ComposeIssue[] {
  const issues: ComposeIssue[] = [];
  for (const page of pages) {
    for (const panel of page.panels) {
      const key = `${panel.scene_id}-${panel.panel_number}`;
      const status = imageMap.get(key);
      if (!status || status.image_available === false) {
        issues.push({
          id: issueId("missing_image", page.page_number, panel.id),
          type: "missing_image",
          severity: "error",
          message: `Panel ${panel.panel_number} has no image available.`,
          pageNumber: page.page_number,
          panelId: panel.id,
        });
      }
    }
  }
  return issues;
}

function checkEmptyBubbleText(pages: ComicPage[]): ComposeIssue[] {
  const issues: ComposeIssue[] = [];
  for (const page of pages) {
    for (const panel of page.panels) {
      for (const bubble of panel.bubbles) {
        if (bubble.text.trim() === "") {
          issues.push({
            id: issueId("empty_bubble_text", page.page_number, panel.id, bubble.id),
            type: "empty_bubble_text",
            severity: "warning",
            message: "Bubble has no text.",
            pageNumber: page.page_number,
            panelId: panel.id,
            bubbleId: bubble.id,
          });
        }
      }
    }
  }
  return issues;
}

function checkBubbleOutsideSafeArea(pages: ComicPage[]): ComposeIssue[] {
  const issues: ComposeIssue[] = [];
  for (const page of pages) {
    for (const panel of page.panels) {
      for (const bubble of panel.bubbles) {
        if (bubble.x === null || bubble.y === null) continue;
        const { x, y } = bubble;
        if (x < SAFE_X || y < SAFE_Y || x > PAGE_W - SAFE_X || y > PAGE_H - SAFE_Y) {
          issues.push({
            id: issueId("bubble_outside_safe_area", page.page_number, panel.id, bubble.id),
            type: "bubble_outside_safe_area",
            severity: "warning",
            message: "Bubble is pinned outside the safe print area.",
            pageNumber: page.page_number,
            panelId: panel.id,
            bubbleId: bubble.id,
          });
        }
      }
    }
  }
  return issues;
}

function checkTextTooLong(pages: ComicPage[]): ComposeIssue[] {
  const issues: ComposeIssue[] = [];
  for (const page of pages) {
    for (const panel of page.panels) {
      for (const bubble of panel.bubbles) {
        if (bubble.text.length > 200) {
          issues.push({
            id: issueId("text_too_long", page.page_number, panel.id, bubble.id),
            type: "text_too_long",
            severity: "warning",
            message: `Bubble text is ${bubble.text.length} characters — may overflow.`,
            pageNumber: page.page_number,
            panelId: panel.id,
            bubbleId: bubble.id,
          });
        }
      }
    }
  }
  return issues;
}

function checkLowContrast(pages: ComicPage[]): ComposeIssue[] {
  const issues: ComposeIssue[] = [];
  for (const page of pages) {
    for (const panel of page.panels) {
      for (const bubble of panel.bubbles) {
        const { font_color, fill_color } = bubble;
        if (!font_color || !fill_color) continue;
        const ratio = contrastRatio(font_color, fill_color);
        if (ratio !== Infinity && ratio < 3.0) {
          issues.push({
            id: issueId("low_contrast", page.page_number, panel.id, bubble.id),
            type: "low_contrast",
            severity: "warning",
            message: `Bubble text contrast ratio is ${ratio.toFixed(1)}:1 (minimum 3.0:1).`,
            pageNumber: page.page_number,
            panelId: panel.id,
            bubbleId: bubble.id,
          });
        }
      }
    }
  }
  return issues;
}

export function detectIssues(pages: ComicPage[], images: ImageStatus[]): ComposeIssue[] {
  const imageMap = new Map<string, ImageStatus>();
  for (const img of images) {
    imageMap.set(`${img.scene_id}-${img.panel_number}`, img);
  }

  const all = [
    ...checkMissingImages(pages, imageMap),
    ...checkUnacceptedPanels(pages, imageMap),
    ...checkEmptyBubbleText(pages),
    ...checkBubbleOutsideSafeArea(pages),
    ...checkTextTooLong(pages),
    ...checkLowContrast(pages),
  ];

  // errors first, then warnings; within each severity sort by page number
  return all.sort((a, b) => {
    if (a.severity !== b.severity) return a.severity === "error" ? -1 : 1;
    return a.pageNumber - b.pageNumber;
  });
}
