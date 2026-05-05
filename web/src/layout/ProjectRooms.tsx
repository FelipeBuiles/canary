import { useParams, useLocation } from "react-router-dom";
import { Outlet } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { useSSE } from "../hooks/useSSE";

const FULL_HEIGHT_ROUTES = ["/shot-plan", "/adapt", "/direct"];

export function ProjectRooms() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const { data: status } = useProjectStatus(id);
  const isFullHeight = FULL_HEIGHT_ROUTES.some((r) => location.pathname.endsWith(r));

  const shouldStream = !!id && status?.is_running === true;
  useSSE(id, shouldStream);

  return (
    <div className={isFullHeight ? "h-full" : "min-h-full"}>
      <Outlet />
    </div>
  );
}
