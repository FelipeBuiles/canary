import { useMemo } from "react";
import { useMutation } from "@tanstack/react-query";
import { createCheckout } from "../api/billing";
import { useCreditPackages } from "../api/queries";
import type { CreditPackage } from "../types/api";

/** Does this package cover the shortfall on its own? */
export function packageMeetsShortfall(pkg: CreditPackage, shortfall: number): boolean {
  return pkg.credits >= shortfall;
}

/**
 * Pick the smallest package that covers the shortfall. Falls back to the
 * cheapest available package when none covers it (so the user still has a
 * starting point). Returns `undefined` when there are no packages.
 */
export function pickRecommendedPackage(
  packages: CreditPackage[],
  shortfall: number,
): CreditPackage | undefined {
  if (packages.length === 0) return undefined;
  const sorted = [...packages].sort((a, b) => a.credits - b.credits);
  return (
    sorted.find((p) => packageMeetsShortfall(p, shortfall)) ?? sorted[0]
  );
}

/**
 * Wraps the packages query + the recommended-package picker. The panel and
 * the InsufficientCreditsDialog both use this so they agree on which package
 * to highlight.
 */
export function useRecommendedPackage(shortfall: number): {
  pkg: CreditPackage | undefined;
  packages: CreditPackage[];
  isLoading: boolean;
} {
  const { data: packagesData, isLoading } = useCreditPackages();
  const packages = useMemo(
    () => packagesData?.packages ?? [],
    [packagesData?.packages],
  );
  const pkg = useMemo(
    () => pickRecommendedPackage(packages, shortfall),
    [packages, shortfall],
  );
  return { pkg, packages, isLoading };
}

/**
 * Open Stripe Checkout for a package in a new tab. Mirrors the dialog's
 * checkout mutation but is reusable. `mutate` is async-safe to call repeatedly.
 */
export function useBuyCredits() {
  return useMutation({
    mutationFn: ({ packageId }: { packageId: string }) => createCheckout(packageId),
    onSuccess: ({ url }) => {
      window.open(url, "_blank", "noopener,noreferrer");
    },
  });
}
