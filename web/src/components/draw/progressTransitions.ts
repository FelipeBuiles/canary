export function isAllInkedTransition(
  prevGenerated: number | null,
  counts: { generated: number; failed: number; total: number },
): boolean {
  return (
    prevGenerated != null &&
    counts.total > 0 &&
    prevGenerated < counts.total &&
    counts.generated === counts.total &&
    counts.failed === 0
  );
}
