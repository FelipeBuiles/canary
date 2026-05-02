import { useParams } from "react-router-dom";
import { Outlet } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { useSSE } from "../hooks/useSSE";

export function ProjectRooms() {
  const { id } = useParams<{ id: string }>();
  const { data: status } = useProjectStatus(id);

  const shouldStream = !!id && status?.is_running === true;
  useSSE(id, shouldStream);

  return (
    <div className="min-h-full">
      <Outlet />
    </div>
  );
}
