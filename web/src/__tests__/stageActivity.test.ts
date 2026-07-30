import { describe, expect, it } from "vitest";
import {
  STALLED_AFTER_MS,
  barSegments,
  isStalled,
  reduceStageActivity,
  type StageActivityMap,
} from "../lib/stageActivity";

const AT = "2026-07-29T12:00:00.000Z";

describe("reduceStageActivity", () => {
  it("records fraction, detail and heartbeat for a stage_activity event", () => {
    const next = reduceStageActivity(
      {},
      { type: "stage_activity", stage: "adapt", fraction: 0.42, detail: "drafting 4 shards", at: AT },
    );
    expect(next.adapt).toEqual({
      fraction: 0.42,
      detail: "drafting 4 shards",
      at: AT,
    });
  });

  it("keeps a null fraction for heartbeat-only activity", () => {
    const next = reduceStageActivity(
      {},
      { type: "stage_activity", stage: "adapt", fraction: null, detail: "writing treatment", at: AT },
    );
    expect(next.adapt.fraction).toBeNull();
    expect(next.adapt.detail).toBe("writing treatment");
  });

  it("lets a retry move the fraction backwards", () => {
    const current: StageActivityMap = {
      adapt: { fraction: 0.8, detail: "drafting", at: AT },
    };
    const next = reduceStageActivity(current, {
      type: "stage_activity",
      stage: "adapt",
      fraction: 0.1,
      detail: "drafting",
      at: AT,
    });
    // Advisory signal — unlike items_done it is allowed to regress.
    expect(next.adapt.fraction).toBe(0.1);
  });

  it("clears activity when the stage begins, completes or fails", () => {
    const current: StageActivityMap = {
      adapt: { fraction: 0.5, detail: "drafting", at: AT },
    };
    for (const type of ["stage_begin", "stage_complete", "stage_fail"]) {
      expect(reduceStageActivity(current, { type, stage: "adapt" })).toEqual({});
    }
  });

  it("leaves other stages alone when one clears", () => {
    const current: StageActivityMap = {
      adapt: { fraction: 0.5, detail: "drafting", at: AT },
      plan: { fraction: 0.2, detail: "planning", at: AT },
    };
    const next = reduceStageActivity(current, { type: "stage_complete", stage: "adapt" });
    expect(Object.keys(next)).toEqual(["plan"]);
  });

  it("returns the same reference for unrelated events", () => {
    const current: StageActivityMap = {};
    expect(reduceStageActivity(current, { type: "log", stage: "adapt" })).toBe(current);
    expect(reduceStageActivity(current, { type: "stage_activity" })).toBe(current);
  });
});

describe("isStalled", () => {
  const now = Date.parse(AT);

  it("is false while chunks are recent", () => {
    expect(isStalled({ fraction: 0.5, detail: null, at: AT }, now + 1_000)).toBe(false);
  });

  it("is true once the heartbeat goes quiet", () => {
    expect(
      isStalled({ fraction: 0.5, detail: null, at: AT }, now + STALLED_AFTER_MS + 1),
    ).toBe(true);
  });

  it("treats an unparseable timestamp as not stalled", () => {
    expect(isStalled({ fraction: null, detail: null, at: "nonsense" }, now)).toBe(false);
  });
});

describe("barSegments", () => {
  const now = Date.parse(AT);

  it("is empty when the stage has no item total", () => {
    expect(barSegments(0, 0, undefined, now)).toEqual({ donePct: 0, inFlightPct: 0 });
  });

  it("reports only settled items when there is no activity", () => {
    expect(barSegments(2, 4, undefined, now)).toEqual({ donePct: 50, inFlightPct: 0 });
  });

  it("adds at most one item's worth for the in-flight fraction", () => {
    const { donePct, inFlightPct } = barSegments(
      2,
      4,
      { fraction: 0.5, detail: "drafting", at: AT },
      now,
    );
    // Half of the third of four items => 12.5% on top of 50%.
    expect(donePct).toBe(50);
    expect(inFlightPct).toBe(12.5);
  });

  it("never lets the in-flight segment overflow the bar", () => {
    const { donePct, inFlightPct } = barSegments(
      4,
      4,
      { fraction: 1, detail: "drafting", at: AT },
      now,
    );
    expect(donePct + inFlightPct).toBe(100);
  });

  it("drops the in-flight segment for a heartbeat-only activity", () => {
    expect(
      barSegments(1, 4, { fraction: null, detail: "writing treatment", at: AT }, now),
    ).toEqual({ donePct: 25, inFlightPct: 0 });
  });

  it("drops the in-flight segment once the stream stalls", () => {
    const stalledNow = now + STALLED_AFTER_MS + 1;
    expect(
      barSegments(1, 4, { fraction: 0.9, detail: "drafting", at: AT }, stalledNow),
    ).toEqual({ donePct: 25, inFlightPct: 0 });
  });
});
