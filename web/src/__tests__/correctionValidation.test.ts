import { describe, expect, it } from "vitest";
import type { PageCorrectionAnnotation } from "../api/pages";
import { annotationProblem, moveAnnotation, serializeAnnotation } from "../components/pages/correctionValidation";

const pin: PageCorrectionAnnotation = { id: "pin-1", kind: "pin", points: [{ x: 0.55, y: 0.07 }] };

describe("optional correction locations", () => {
  it("grounds a location in its parent request without requiring duplicate wording", () => {
    const submitted = serializeAnnotation(pin);
    expect(submitted.note).toBe("Apply the enclosing change request at this location.");
    expect(submitted.points).toEqual(pin.points);
    expect(pin.note).toBeUndefined();
  });
  it("preserves an explicit note and label, and never mutates stored marks", () => {
    const mark = { ...pin, note: "  Only the coat.  ", label: "Coat" };
    expect(serializeAnnotation(mark)).toEqual({ ...mark, note: "Only the coat." });
    expect(mark.note).toBe("  Only the coat.  ");
  });
  it.each(["rectangle", "highlight", "arrow", "freehand"] as const)("rejects a zero-size %s before cost review", (kind) => {
    const mark = { ...pin, kind, points: [pin.points[0]!, pin.points[0]!] };
    expect(annotationProblem(mark)).not.toBeNull();
    expect(() => serializeAnnotation(mark)).toThrow();
  });
  it("rejects unfinished, nonfinite and over-limit geometry instead of dropping it", () => {
    for (const mark of [
      { ...pin, points: [] },
      { ...pin, points: [{ x: Number.NaN, y: 0.5 }] },
      { ...pin, points: [{ x: Infinity, y: 0.5 }] },
      { ...pin, points: [...pin.points, ...pin.points] },
      { ...pin, note: "a".repeat(501) },
      { ...pin, kind: "freehand" as const, points: Array.from({ length: 65 }, (_, x) => ({ x: x / 65, y: 0.2 })) },
    ]) expect(() => serializeAnnotation(mark)).toThrow();
  });
  it("checks degeneracy after rounding, and distinguishes areas from lines", () => {
    expect(annotationProblem({ ...pin, kind: "rectangle", points: [{ x: 0.2, y: 0.2 }, { x: 0.200001, y: 0.5 }] })).not.toBeNull();
    expect(annotationProblem({ ...pin, kind: "arrow", points: [{ x: 0.2, y: 0.2 }, { x: 0.2, y: 0.5 }] })).toBeNull();
  });
  it("supports every saved mark kind with or without extra detail", () => {
    for (const kind of ["rectangle", "highlight", "arrow", "freehand"] as const) {
      const mark = { ...pin, kind, points: [{ x: 0.2, y: 0.3 }, { x: 0.4, y: 0.6 }], note: " " };
      expect(serializeAnnotation(mark).note?.length).toBeGreaterThan(0);
    }
  });
  it("moves a whole shape to an edge without squashing its width or height", () => {
    const mark = { ...pin, kind: "rectangle" as const, points: [{ x: 0.75, y: 0.1 }, { x: 0.95, y: 0.4 }] };
    expect(moveAnnotation(mark, 0.1, -0.2).points).toEqual([{ x: 0.8, y: 0 }, { x: 1, y: 0.3 }]);
    expect(mark.points).toEqual([{ x: 0.75, y: 0.1 }, { x: 0.95, y: 0.4 }]);
  });
});
