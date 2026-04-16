import { Routes, Route } from "react-router-dom";
import { Shell } from "./layout/Shell";
import { Library } from "./pages/Library";
import { ProjectRooms } from "./layout/ProjectRooms";
import { NavigateToRoom } from "./pages/NavigateToRoom";
import { StoryBibleRoom } from "./pages/rooms/StoryBibleRoom";
import { CastRoom } from "./pages/rooms/CastRoom";
import { AdaptRoom } from "./pages/rooms/AdaptRoom";
import { StoryboardRoom } from "./pages/rooms/StoryboardRoom";
import { DirectRoom } from "./pages/rooms/DirectRoom";
import { DrawRoom } from "./pages/rooms/DrawRoom";
import { ComposeRoom } from "./pages/rooms/ComposeRoom";

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Library />} />
        <Route path="project/:name" element={<ProjectRooms />}>
          <Route index element={<NavigateToRoom />} />
          <Route path="extract" element={<StoryBibleRoom />} />
          <Route path="cast" element={<CastRoom />} />
          <Route path="adapt" element={<AdaptRoom />} />
          <Route path="storyboard" element={<StoryboardRoom />} />
          <Route path="direct" element={<DirectRoom />} />
          <Route path="draw" element={<DrawRoom />} />
          <Route path="compose" element={<ComposeRoom />} />
        </Route>
      </Route>
    </Routes>
  );
}
