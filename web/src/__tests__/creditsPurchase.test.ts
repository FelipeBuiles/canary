import { describe, it, expect } from "vitest";
import {
  packageMeetsShortfall,
  pickRecommendedPackage,
} from "../lib/creditsPurchase";
import type { CreditPackage } from "../types/api";

function pkg(id: string, credits: number, priceCents = credits * 2): CreditPackage {
  return { id, label: id, price_cents: priceCents, credits };
}

const PACKAGES = [pkg("starter", 1200, 1900), pkg("standard", 3000, 3900), pkg("creator", 7500, 8900)];

describe("packageMeetsShortfall", () => {
  it("returns true when credits equal the shortfall (boundary)", () => {
    expect(packageMeetsShortfall(pkg("a", 100), 100)).toBe(true);
  });

  it("returns true when credits exceed the shortfall", () => {
    expect(packageMeetsShortfall(pkg("a", 200), 100)).toBe(true);
  });

  it("returns false when credits are below the shortfall", () => {
    expect(packageMeetsShortfall(pkg("a", 50), 100)).toBe(false);
  });
});

describe("pickRecommendedPackage", () => {
  it("picks the smallest package that covers the shortfall", () => {
    // shortfall 2000 → standard (3000) is the smallest that covers; starter (1200) does not.
    expect(pickRecommendedPackage(PACKAGES, 2000)?.id).toBe("standard");
  });

  it("picks the smallest package when shortfall is tiny", () => {
    expect(pickRecommendedPackage(PACKAGES, 50)?.id).toBe("starter");
  });

  it("falls back to the cheapest package when none covers the shortfall", () => {
    // shortfall beyond the largest package → cheapest is the starting point.
    expect(pickRecommendedPackage(PACKAGES, 999999)?.id).toBe("starter");
  });

  it("returns undefined when there are no packages", () => {
    expect(pickRecommendedPackage([], 100)).toBeUndefined();
  });
});
