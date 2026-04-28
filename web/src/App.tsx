import { Navigate, Routes, Route } from "react-router-dom";
import { Shell } from "./layout/Shell";
import { Library } from "./pages/Library";
import { Settings } from "./pages/Settings";
import { ProjectRooms } from "./layout/ProjectRooms";
import { NavigateToRoom } from "./pages/NavigateToRoom";
import { StoryBibleRoom } from "./pages/rooms/StoryBibleRoom";
import { CastRoom } from "./pages/rooms/CastRoom";
import { AdaptRoom } from "./pages/rooms/AdaptRoom";
import { PlanRoom } from "./pages/rooms/PlanRoom";
import { StoryboardRoom } from "./pages/rooms/StoryboardRoom";
import { DirectRoom } from "./pages/rooms/DirectRoom";
import { DrawRoom } from "./pages/rooms/DrawRoom";
import { ComposeRoom } from "./pages/rooms/ComposeRoom";
import { StyleRoom } from "./pages/rooms/StyleRoom";
import { PrimitiveReference } from "./pages/PrimitiveReference";
import { LoginPage } from "./pages/auth/LoginPage";
import { SignupPage } from "./pages/auth/SignupPage";
import { CreditsPage } from "./pages/CreditsPage";
import { AuthGuard } from "./components/AuthGuard";
import { I18nProvider } from "./i18n";

export function App() {
  return (
    <I18nProvider>
      <Routes>
        {/* Public auth routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />

        {/* Protected app routes */}
        <Route
          element={
            <AuthGuard>
              <Shell />
            </AuthGuard>
          }
        >
          <Route index element={<Library />} />
          <Route
            path="dev/primitives"
            element={import.meta.env.DEV ? <PrimitiveReference /> : <Navigate to="/" replace />}
          />
          <Route path="settings" element={<Settings />} />
          <Route path="credits" element={<CreditsPage />} />
          <Route path="project/:name/settings" element={<Settings />} />
          <Route path="project/:name" element={<ProjectRooms />}>
            <Route index element={<NavigateToRoom />} />
            <Route path="extract" element={<StoryBibleRoom />} />
            <Route path="cast" element={<CastRoom />} />
            <Route path="adapt" element={<AdaptRoom />} />
            <Route path="plan" element={<PlanRoom />} />
            <Route path="storyboard" element={<StoryboardRoom />} />
            <Route path="direct" element={<DirectRoom />} />
            <Route path="draw" element={<DrawRoom />} />
            <Route path="compose" element={<ComposeRoom />} />
            <Route path="styles" element={<StyleRoom />} />
          </Route>
        </Route>
      </Routes>
    </I18nProvider>
  );
}
