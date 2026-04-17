import { useParams } from "react-router-dom";
import { Outlet } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { useSSE } from "../hooks/useSSE";

export function ProjectRooms() {
  const { name } = useParams<{ name: string }>();
  const { data: status } = useProjectStatus(name);

  const shouldStream = !!name && status?.is_running === true;
  useSSE(name, shouldStream);

  return (
    <div className="min-h-full">
      <Outlet />
    </div>
  );
}
