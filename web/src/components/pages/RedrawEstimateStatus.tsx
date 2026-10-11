import type { UseQueryResult } from "@tanstack/react-query";
import { useI18n } from "../../i18n";
import { ErrorNotice } from "../composites/ErrorNotice";

/**
 * What a redraw sheet shows while its cost loads or after something fails.
 * It renders inside the sheet: anything behind the backdrop is invisible, and
 * a sheet with a disabled button and no explanation looks stuck.
 */
export function RedrawEstimateStatus({ estimate, error }: {
  estimate: Pick<UseQueryResult<unknown>, "data" | "error" | "isFetching" | "refetch">;
  error?: unknown;
}) {
  const { t } = useI18n();
  return (
    <>
      {!estimate.data && !estimate.error && <p role="status" className="font-body text-sm text-ink-muted">{t("Loading estimate…")}</p>}
      {estimate.error && (
        <ErrorNotice error={estimate.error} operation="estimate" title="The cost could not be loaded. Nothing has been started."
          onRetry={() => void estimate.refetch()} retryDisabled={estimate.isFetching} retryLabel={t("RETRY ESTIMATE")} />
      )}
      {error != null && <ErrorNotice error={error} operation="generate" />}
    </>
  );
}
