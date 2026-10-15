import { describe, expect, it } from "vitest";
import { wordDiff } from "../lib/wordDiff";

describe("wordDiff", () => {
  it("marks replaced words and reproduces both texts", () => {
    const before = '"Thou art late," said the old man.';
    const after = '"You\'re late," said the old man.';
    const segments = wordDiff(before, after);
    expect(segments).toEqual([
      { kind: "removed", text: '"Thou art ' },
      { kind: "added", text: '"You\'re ' },
      { kind: "same", text: 'late," said the old man.' },
    ]);
    expect(segments.filter((s) => s.kind !== "removed").map((s) => s.text).join("")).toBe(after);
    expect(segments.filter((s) => s.kind !== "added").map((s) => s.text).join("")).toBe(before);
  });

  it("returns one unchanged segment for identical text", () => {
    expect(wordDiff("The fire crackled.", "The fire crackled.")).toEqual([{ kind: "same", text: "The fire crackled." }]);
  });
});
