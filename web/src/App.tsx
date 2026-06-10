import { lazy, Suspense, type ComponentType, type ReactElement } from "react";
import { Navigate, Routes, Route } from "react-router-dom";
import { AuthGuard } from "./components/AuthGuard";
import { LoadingBlock } from "./components/ui/StateBlock";
import { I18nProvider } from "./i18n";

const Shell = lazy(() => import("./layout/Shell").then(({ Shell }) => ({ default: Shell })));
const ProjectRooms = lazy(() =>
  import("./layout/ProjectRooms").then(({ ProjectRooms }) => ({ default: ProjectRooms })),
);
const LoginPage = lazy(() => import("./pages/auth/LoginPage").then(({ LoginPage }) => ({ default: LoginPage })));
const SignupPage = lazy(() => import("./pages/auth/SignupPage").then(({ SignupPage }) => ({ default: SignupPage })));
const Library = lazy(() => import("./pages/Library").then(({ Library }) => ({ default: Library })));
const LabsRoom = lazy(() => import("./pages/LabsRoom").then(({ LabsRoom }) => ({ default: LabsRoom })));
const PrimitiveReference = lazy(() =>
  import("./pages/PrimitiveReference").then(({ PrimitiveReference }) => ({ default: PrimitiveReference })),
);
const AccountPage = lazy(() => import("./pages/AccountPage").then(({ AccountPage }) => ({ default: AccountPage })));
const CreditsPage = lazy(() => import("./pages/CreditsPage").then(({ CreditsPage }) => ({ default: CreditsPage })));
const ProjectSettingsPage = lazy(() =>
  import("./pages/ProjectSettingsPage").then(({ ProjectSettingsPage }) => ({ default: ProjectSettingsPage })),
);
const NavigateToRoom = lazy(() =>
  import("./pages/NavigateToRoom").then(({ NavigateToRoom }) => ({ default: NavigateToRoom })),
);
const StoryBibleRoom = lazy(() =>
  import("./pages/rooms/StoryBibleRoom").then(({ StoryBibleRoom }) => ({ default: StoryBibleRoom })),
);
const StyleRoom = lazy(() => import("./pages/rooms/StyleRoom").then(({ StyleRoom }) => ({ default: StyleRoom })));
const CastRoom = lazy(() => import("./pages/rooms/CastRoom").then(({ CastRoom }) => ({ default: CastRoom })));
const AdaptRoom = lazy(() => import("./pages/rooms/AdaptRoom").then(({ AdaptRoom }) => ({ default: AdaptRoom })));
const ShotPlanRoom = lazy(() =>
  import("./pages/rooms/ShotPlanRoom").then(({ ShotPlanRoom }) => ({ default: ShotPlanRoom })),
);
const DirectRoom = lazy(() => import("./pages/rooms/DirectRoom").then(({ DirectRoom }) => ({ default: DirectRoom })));
const DrawRoom = lazy(() => import("./pages/rooms/DrawRoom").then(({ DrawRoom }) => ({ default: DrawRoom })));
const ComposeRoom = lazy(() =>
  import("./pages/rooms/ComposeRoom").then(({ ComposeRoom }) => ({ default: ComposeRoom })),
);
const NotFound = lazy(() => import("./pages/NotFound").then(({ NotFound }) => ({ default: NotFound })));

function lazyRoute(Component: ComponentType): ReactElement {
  return (
    <Suspense fallback={<LoadingBlock label="LOADING…" />}>
      <Component />
    </Suspense>
  );
}

export function App() {
  return (
    <I18nProvider>
      <Routes>
        {/* Public auth routes */}
        <Route path="/login" element={lazyRoute(LoginPage)} />
        <Route path="/signup" element={lazyRoute(SignupPage)} />

        {/* Protected app routes */}
        <Route
          element={
            <AuthGuard>
              {lazyRoute(Shell)}
            </AuthGuard>
          }
        >
          <Route index element={lazyRoute(Library)} />
          <Route path="labs" element={lazyRoute(LabsRoom)} />
          <Route
            path="dev/primitives"
            element={import.meta.env.DEV ? lazyRoute(PrimitiveReference) : <Navigate to="/" replace />}
          />
          <Route path="account" element={lazyRoute(AccountPage)} />
          <Route path="credits" element={lazyRoute(CreditsPage)} />
          <Route path="project/:id/settings" element={lazyRoute(ProjectSettingsPage)} />
          <Route path="project/:id" element={lazyRoute(ProjectRooms)}>
            <Route index element={lazyRoute(NavigateToRoom)} />
            <Route path="extract" element={lazyRoute(StoryBibleRoom)} />
            <Route path="cast" element={lazyRoute(CastRoom)} />
            <Route path="adapt" element={lazyRoute(AdaptRoom)} />
            <Route path="shot-plan" element={lazyRoute(ShotPlanRoom)} />
            <Route path="direct" element={lazyRoute(DirectRoom)} />
            <Route path="draw" element={lazyRoute(DrawRoom)} />
            <Route path="compose" element={lazyRoute(ComposeRoom)} />
            <Route path="styles" element={lazyRoute(StyleRoom)} />
            <Route path="*" element={lazyRoute(NavigateToRoom)} />
          </Route>
          <Route path="*" element={lazyRoute(NotFound)} />
        </Route>
      </Routes>
    </I18nProvider>
  );
}
