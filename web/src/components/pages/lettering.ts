import type { PageIssue } from "../../types/api";

export const OCR_ISSUE_TYPES = new Set([
  "misspelled_lettering",
  "missing_lettering",
  "duplicated_lettering",
  "invented_lettering",
  "reordered_lettering",
  "unverified_lettering_order",
]);

export function isOcrIssue(issue: PageIssue): boolean {
  return OCR_ISSUE_TYPES.has(issue.issue_type);
}

/** Parse `prefix<json string[]>` evidence entries; null when absent or malformed. */
export function readTextEvidence(issue: PageIssue, prefix: string): string[] | null {
  const value = issue.evidence.find((item) => item.startsWith(prefix));
  if (!value) return null;
  try {
    const parsed = JSON.parse(value.slice(prefix.length)) as unknown;
    if (!Array.isArray(parsed) || !parsed.every((item) => typeof item === "string")) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function cropCheckStatus(issue: PageIssue): "agrees" | "disagrees" | "inconclusive" | null {
  const entry = issue.evidence.find((item) => item.startsWith("crop_check_status="));
  const value = entry?.slice("crop_check_status=".length);
  return value === "agrees" || value === "disagrees" || value === "inconclusive" ? value : null;
}

export interface SegmentDifference {
  type: "same" | "changed" | "missing" | "extra" | "moved";
  expected?: string;
  recognized?: string;
}

/**
 * True sequence alignment between the approved script and what the text check
 * found. A longest-common-subsequence pass yields same/inserted/deleted rows;
 * a deleted row whose text reappears as an insertion is proven movement and
 * only then labeled moved; adjacent deletion/insertion pairs read as one
 * substitution. Distant edits stay localized instead of collapsing the middle
 * into a single difference. Comparison is code-point safe throughout.
 */
export function alignLettering(expected: string[], recognized: string[]): SegmentDifference[] {
  const rows = expected.length;
  const cols = recognized.length;
  const table: number[][] = Array.from({ length: rows + 1 }, () => new Array<number>(cols + 1).fill(0));
  for (let i = rows - 1; i >= 0; i -= 1) {
    for (let j = cols - 1; j >= 0; j -= 1) {
      table[i]![j] = expected[i] === recognized[j]
        ? (table[i + 1]![j + 1] ?? 0) + 1
        : Math.max(table[i + 1]![j] ?? 0, table[i]![j + 1] ?? 0);
    }
  }
  type Op = { type: "same" | "del" | "ins"; text: string };
  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < rows && j < cols) {
    if (expected[i] === recognized[j]) {
      ops.push({ type: "same", text: expected[i]! });
      i += 1;
      j += 1;
    } else if ((table[i + 1]?.[j] ?? 0) >= (table[i]?.[j + 1] ?? 0)) {
      ops.push({ type: "del", text: expected[i]! });
      i += 1;
    } else {
      ops.push({ type: "ins", text: recognized[j]! });
      j += 1;
    }
  }
  while (i < rows) { ops.push({ type: "del", text: expected[i]! }); i += 1; }
  while (j < cols) { ops.push({ type: "ins", text: recognized[j]! }); j += 1; }

  // Proven movement: the same text deleted once and inserted once.
  const insertionsByText = new Map<string, number[]>();
  ops.forEach((op, index) => {
    if (op.type === "ins") {
      const list = insertionsByText.get(op.text) ?? [];
      list.push(index);
      insertionsByText.set(op.text, list);
    }
  });
  const consumedInsertions = new Set<number>();
  const movedAt = new Map<number, string>();
  ops.forEach((op, index) => {
    if (op.type !== "del") return;
    const candidates = insertionsByText.get(op.text) ?? [];
    const match = candidates.find((candidate) => !consumedInsertions.has(candidate));
    if (match === undefined) return;
    consumedInsertions.add(match);
    movedAt.set(index, op.text);
  });

  const differences: SegmentDifference[] = [];
  for (let index = 0; index < ops.length; index += 1) {
    const op = ops[index]!;
    if (op.type === "same") {
      differences.push({ type: "same", expected: op.text, recognized: op.text });
      continue;
    }
    if (op.type === "del" && movedAt.has(index)) {
      differences.push({ type: "moved", expected: op.text, recognized: op.text });
      continue;
    }
    if (op.type === "ins" && consumedInsertions.has(index)) continue;
    const next = ops[index + 1];
    if (op.type === "del" && next?.type === "ins" && !consumedInsertions.has(index + 1)) {
      differences.push({ type: "changed", expected: op.text, recognized: next.text });
      index += 1;
      continue;
    }
    if (op.type === "ins" && next?.type === "del" && !movedAt.has(index + 1)) {
      differences.push({ type: "changed", expected: next.text, recognized: op.text });
      index += 1;
      continue;
    }
    differences.push(op.type === "del"
      ? { type: "missing", expected: op.text }
      : { type: "extra", recognized: op.text });
  }
  return differences;
}

export interface CharDifference {
  prefix: string;
  changed: string;
  suffix: string;
}

/** Exact character policy: longest common prefix/suffix, code-point safe. */
export function exactCharDifference(before: string, after: string): CharDifference & { counterpart: CharDifference } {
  const left = Array.from(before);
  const right = Array.from(after);
  let prefix = 0;
  while (prefix < left.length && prefix < right.length && left[prefix] === right[prefix]) {
    prefix += 1;
  }
  let suffix = 0;
  while (
    suffix < left.length - prefix
    && suffix < right.length - prefix
    && left[left.length - 1 - suffix] === right[right.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  const take = (chars: string[], from: number, to: number) => chars.slice(from, to).join("");
  return {
    prefix: take(left, 0, prefix),
    changed: take(left, prefix, left.length - suffix),
    suffix: suffix ? take(left, left.length - suffix, left.length) : "",
    counterpart: {
      prefix: take(right, 0, prefix),
      changed: take(right, prefix, right.length - suffix),
      suffix: suffix ? take(right, right.length - suffix, right.length) : "",
    },
  };
}

/** Unchanged context kept around each edit, in code points. */
export const DIFFERENCE_CONTEXT_RADIUS = 40;

export function cropLeadingContext(text: string, radius: number = DIFFERENCE_CONTEXT_RADIUS): { cropped: boolean; text: string } {
  const chars = Array.from(text);
  if (chars.length <= radius) return { cropped: false, text };
  return { cropped: true, text: `…${chars.slice(chars.length - radius).join("")}` };
}

export function cropTrailingContext(text: string, radius: number = DIFFERENCE_CONTEXT_RADIUS): { cropped: boolean; text: string } {
  const chars = Array.from(text);
  if (chars.length <= radius) return { cropped: false, text };
  return { cropped: true, text: `${chars.slice(0, radius).join("")}…` };
}

export interface CharHunk {
  type: "same" | "changed";
  expected: string;
  recognized: string;
}

/**
 * Character-level alignment so edits far apart within one text block stay
 * localized: each maximal disagreement becomes its own hunk instead of one
 * giant changed middle. Code-point safe.
 */
export function alignChars(before: string, after: string): CharHunk[] {
  const left = Array.from(before);
  const right = Array.from(after);
  const rows = left.length;
  const cols = right.length;
  const table: number[][] = Array.from({ length: rows + 1 }, () => new Array<number>(cols + 1).fill(0));
  for (let i = rows - 1; i >= 0; i -= 1) {
    for (let j = cols - 1; j >= 0; j -= 1) {
      table[i]![j] = left[i] === right[j]
        ? (table[i + 1]![j + 1] ?? 0) + 1
        : Math.max(table[i + 1]![j] ?? 0, table[i]![j + 1] ?? 0);
    }
  }
  const hunks: CharHunk[] = [];
  let same = "";
  let del = "";
  let ins = "";
  function flushSame() {
    if (same) { hunks.push({ type: "same", expected: same, recognized: same }); same = ""; }
  }
  function flushChanged() {
    if (del || ins) { hunks.push({ type: "changed", expected: del, recognized: ins }); del = ""; ins = ""; }
  }
  let i = 0;
  let j = 0;
  while (i < rows && j < cols) {
    if (left[i] === right[j]) {
      flushChanged();
      same += left[i];
      i += 1;
      j += 1;
    } else if ((table[i + 1]?.[j] ?? 0) >= (table[i]?.[j + 1] ?? 0)) {
      flushSame();
      del += left[i]!;
      i += 1;
    } else {
      flushSame();
      ins += right[j]!;
      j += 1;
    }
  }
  while (i < rows) { flushSame(); del += left[i]!; i += 1; }
  while (j < cols) { flushSame(); ins += right[j]!; j += 1; }
  flushSame();
  flushChanged();
  return hunks;
}

/** Crop a middle same-hunk to its edges so distant edits stay in view. */
export function cropMiddleContext(text: string, edge: number = DIFFERENCE_CONTEXT_RADIUS): string {
  const chars = Array.from(text);
  if (chars.length <= edge * 2) return text;
  return `${chars.slice(0, edge).join("")} … ${chars.slice(chars.length - edge).join("")}`;
}

const OCR_TITLES: Record<string, string> = {
  misspelled_lettering: "Possible wording difference",
  missing_lettering: "Some lettering was not recognized",
  duplicated_lettering: "Some lettering appears more than once",
  invented_lettering: "The checker found unexpected lettering",
  reordered_lettering: "The lettering may be in the wrong reading order",
};

export function ocrIssueTitle(issue: PageIssue): string {
  const cropStatus = cropCheckStatus(issue);
  if (cropStatus === "disagrees" || cropStatus === "inconclusive") return "Text check is uncertain";
  return OCR_TITLES[issue.issue_type] ?? issue.requested_correction;
}

export function issueConfirmed(issue: PageIssue): boolean {
  return issue.status === "accepted" || issue.status === "resolved";
}
