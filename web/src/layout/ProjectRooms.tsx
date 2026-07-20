import { useEffect } from "react";
import { useParams, useLocation } from "react-router-dom";
import { Outlet } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { useSSE } from "../hooks/useSSE";
import { trackProductEvent } from "../api/events";
import { stationForRoute } from "../lib/stations";

const FULL_HEIGHT_ROUTES = ["/shot-plan", "/adapt", "/direct"];

export function ProjectRooms() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const { data: status } = useProjectStatus(id);
  const isFullHeight = FULL_HEIGHT_ROUTES.some((r) => location.pathname.endsWith(r));

  const shouldStream = !!id && status?.is_running === true;
  useSSE(id, shouldStream);

  useEffect(() => {
    if (!id) return;
    const route = location.pathname.split("/").filter(Boolean).at(-1);
    const station = route ? stationForRoute(route) : undefined;
    if (station) {
      void trackProductEvent("station_viewed", {
        projectId: id,
        properties: { station: station.key },
      });
    }
  }, [id, location.pathname]);

  return (
    <div className={isFullHeight ? "h-full" : "min-h-full"}>
      <Outlet />
    </div>
  );
}
