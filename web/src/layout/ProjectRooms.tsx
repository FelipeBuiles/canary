import { useEffect } from "react";
import { Navigate, useParams, useLocation } from "react-router-dom";
import { Outlet } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { useSSE } from "../hooks/useSSE";
import { useAssetVersions } from "../hooks/useAssetVersions";
import { trackProductEvent } from "../api/events";
import { stationForRoute } from "../lib/stations";
import { isNotFoundError } from "../api/client";
import { partProjectKey, splitProjectKey, withProjectKey } from "../api/projectScope";
import { getRoomAccess } from "../lib/stationAccess";
import { StationLocked } from "../components/composites/StationLocked";
import { LoadingBlock, StateBlock } from "../components/ui/StateBlock";
import { Button } from "../components/ui/Button";
import { useI18n } from "../i18n";

export function ProjectRooms() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const { data: status, error, refetch, isFetching } = useProjectStatus(id);
  const assetsReady = useAssetVersions(id, status);
  const { t } = useI18n();
  const route = location.pathname.split("/").filter(Boolean).at(-1) ?? "";
  const station = stationForRoute(route);
  const access = getRoomAccess(route, status);
  const missing = isNotFoundError(error);
  const projectExists = !!status;
  const { id: projectId, part } = splitProjectKey(id ?? "");

  const shouldStream = !!id && !missing && status?.is_running === true;
  useSSE(id, shouldStream);

  useEffect(() => {
    if (!id || !projectExists || missing || error || access.state !== "available") return;
    const route = location.pathname.split("/").filter(Boolean).at(-1);
    const station = route ? stationForRoute(route) : undefined;
    if (station) {
      void trackProductEvent("station_viewed", {
        projectId,
        properties: { station: station.key },
      });
    }
  }, [id, projectId, location.pathname, missing, projectExists, error, access.state]);

  // A part that no longer exists opens the project's current part instead.
  if (missing && part) {
    return <Navigate to={{ pathname: withProjectKey(location.pathname, projectId), search: location.search }} replace />;
  }
  if (missing) return <Navigate to="/" replace />;
  // Page work belongs to a part: open the part the server suggests.
  if (!part && status?.part_id) {
    return <Navigate replace to={{
      pathname: withProjectKey(location.pathname, partProjectKey(projectId, status.part_id)),
      search: location.search,
    }} />;
  }
  if (route !== "settings") {
    if (error) return <StateBlock title={t("Could not check station availability")}
      description={t("Try again to load your project's current progress.")} tone="danger"
      action={<Button onClick={() => void refetch()} disabled={isFetching}>{t("Try again")}</Button>} />;
    if (!status || !assetsReady) return <LoadingBlock label={t("Checking project progress…")} />;
    if (station && access.state === "locked" && id) {
      return <StationLocked project={id} station={station} access={access} status={status} />;
    }
  }

  return (
    <div className="min-h-full has-[[data-bleed]]:flex has-[[data-bleed]]:flex-col studio-desktop:has-[[data-bleed]]:h-full">
      <Outlet />
    </div>
  );
}
