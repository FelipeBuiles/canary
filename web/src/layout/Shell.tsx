import { Outlet, useParams } from "react-router-dom";
import { Footer } from "./Footer";
import { SideNav } from "./SideNav";
import { TopNav } from "./TopNav";
import { LiveSpecPill } from "../components/ui/LiveSpecPill";
import { useProjectStatus } from "../api/queries";

function LiveIndicator() {
  const { name } = useParams();
  const { data: status } = useProjectStatus(name);
  const running = !!status?.is_running;

  return (
    <LiveSpecPill
      label={running ? "LIVE PIPELINE" : name ? "SPEC READY" : "LIVE SPEC ACTIVE"}
      active={running || !name}
    />
  );
}

export function Shell() {
  return (
    <div className="flex min-h-screen flex-col bg-pulp-paper">
      <TopNav />
      <div className="flex flex-1 overflow-hidden">
        <SideNav />
        <main className="flex-1 overflow-y-auto bg-pulp-paper">
          <div className="mx-auto flex min-h-full w-full max-w-[1318px] flex-col px-5 py-6">
            <Outlet />
          </div>
        </main>
      </div>
      <Footer />
      <LiveIndicator />
    </div>
  );
}
