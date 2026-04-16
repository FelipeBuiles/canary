import { Outlet } from "react-router-dom";
import { Footer } from "./Footer";
import { SideNav } from "./SideNav";
import { TopNav } from "./TopNav";

export function Shell() {
  return (
    <div className="flex min-h-screen flex-col bg-pulp-paper">
      <TopNav />
      <div className="flex flex-1 overflow-hidden">
        <SideNav />
        <main className="flex-1 overflow-y-auto bg-pulp-paper">
          <div className="mx-auto flex min-h-full w-full max-w-[1318px] flex-col px-5 py-5">
            <Outlet />
          </div>
        </main>
      </div>
      <Footer />
    </div>
  );
}
