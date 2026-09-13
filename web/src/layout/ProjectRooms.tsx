import { useEffect } from "react";
import { Navigate, useParams, useLocation } from "react-router-dom";
import { Outlet } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { useSSE } from "../hooks/useSSE";
import { trackProductEvent } from "../api/events";
import { stationForRoute } from "../lib/stations";
import { isNotFoundError } from "../api/client";

export function ProjectRooms() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const { data: status, error } = useProjectStatus(id);
  const missing = isNotFoundError(error);
  const projectExists = !!status;

  const shouldStream = !!id && !missing && status?.is_running === true;
  useSSE(id, shouldStream);

  useEffect(() => {
    if (!id || !projectExists || missing) return;
    const route = location.pathname.split("/").filter(Boolean).at(-1);
    const station = route ? stationForRoute(route) : undefined;
    if (station) {
      void trackProductEvent("station_viewed", {
        projectId: id,
        properties: { station: station.key },
      });
    }
  }, [id, location.pathname, missing, projectExists]);

  if (missing) return <Navigate to="/" replace />;

  return (
    <div className="min-h-full">
      <Outlet />
    </div>
  );
}
