/** Rows of panels for a page thumbnail: a plausible grid, never a claimed layout. */
export function panelRows(count: number): number[] {
  const fixed: Record<number, number[]> = {
    1: [1], 2: [1, 1], 3: [1, 2], 4: [2, 2], 5: [2, 1, 2], 6: [2, 2, 2],
  };
  if (fixed[count]) return fixed[count];
  const rows: number[] = [];
  for (let remaining = count; remaining > 0; remaining -= 3) rows.push(Math.min(3, remaining));
  return rows;
}
