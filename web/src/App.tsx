import { lazy, Suspense, useEffect, type ComponentType, type ReactElement } from "react";
import { BrowserRouter, Navigate, Routes, Route, useLocation } from "react-router-dom";
import { AuthGuard } from "./components/AuthGuard";
import { LoadingBlock } from "./components/ui/StateBlock";
import { useAuth } from "./hooks/useAuth";
import { I18nProvider } from "./i18n";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import { trackPageview } from "./telemetry";

const Shell = lazy(() => import("./layout/Shell").then(({ Shell }) => ({ default: Shell })));
const ProjectRooms = lazy(() =>
  import("./layout/ProjectRooms").then(({ ProjectRooms }) => ({ default: ProjectRooms })),
);
const LoginPage = lazy(() => import("./pages/auth/LoginPage").then(({ LoginPage }) => ({ default: LoginPage })));
const SignupPage = lazy(() => import("./pages/auth/SignupPage").then(({ SignupPage }) => ({ default: SignupPage })));
const ResetPasswordPage = lazy(() =>
  import("./pages/auth/ResetPasswordPage").then(({ ResetPasswordPage }) => ({ default: ResetPasswordPage })),
);
const PublicBookPage = lazy(() => import("./pages/PublicBookPage").then(({ PublicBookPage }) => ({ default: PublicBookPage })));
const HomePage = lazy(() => import("./pages/HomePage").then(({ HomePage }) => ({ default: HomePage })));
const SampleLibraryPage = lazy(() => import("./pages/SampleLibraryPage").then(({ SampleLibraryPage }) => ({ default: SampleLibraryPage })));
const TermsPage = lazy(() => import("./pages/legal/TermsPage").then(({ TermsPage }) => ({ default: TermsPage })));
const PrivacyPage = lazy(() => import("./pages/legal/PrivacyPage").then(({ PrivacyPage }) => ({ default: PrivacyPage })));
const AcceptableUsePage = lazy(() =>
  import("./pages/legal/AcceptableUsePage").then(({ AcceptableUsePage }) => ({ default: AcceptableUsePage })),
);
const Library = lazy(() => import("./pages/Library").then(({ Library }) => ({ default: Library })));
const LabsRoom = import.meta.env.DEV
  ? lazy(() => import("./pages/LabsRoom").then(({ LabsRoom }) => ({ default: LabsRoom })))
  : null;
const PrimitiveReference = lazy(() =>
  import("./pages/PrimitiveReference").then(({ PrimitiveReference }) => ({ default: PrimitiveReference })),
);
const AccountPage = lazy(() => import("./pages/AccountPage").then(({ AccountPage }) => ({ default: AccountPage })));
const CreditsPage = lazy(() => import("./pages/CreditsPage").then(({ CreditsPage }) => ({ default: CreditsPage })));
const BackofficePage = lazy(() => import("./pages/BackofficePage").then(({ BackofficePage }) => ({ default: BackofficePage })));
const ProjectSettingsPage = lazy(() =>
  import("./pages/ProjectSettingsPage").then(({ ProjectSettingsPage }) => ({ default: ProjectSettingsPage })),
);
const NavigateToRoom = lazy(() =>
  import("./pages/NavigateToRoom").then(({ NavigateToRoom }) => ({ default: NavigateToRoom })),
);
const StoryRoom = lazy(() =>
  import("./pages/rooms/StoryRoom").then(({ StoryRoom }) => ({ default: StoryRoom })),
);
const StyleRoom = lazy(() => import("./pages/rooms/StyleRoom").then(({ StyleRoom }) => ({ default: StyleRoom })));
const CastRoom = lazy(() => import("./pages/rooms/CastRoom").then(({ CastRoom }) => ({ default: CastRoom })));
const PagesRoom = lazy(() =>
  import("./pages/rooms/PagesRoom").then(({ PagesRoom }) => ({ default: PagesRoom })),
);
const BookRoom = lazy(() =>
  import("./pages/rooms/BookRoom").then(({ BookRoom }) => ({ default: BookRoom })),
);
const NotFound = lazy(() => import("./pages/NotFound").then(({ NotFound }) => ({ default: NotFound })));

function lazyRoute(Component: ComponentType): ReactElement {
  return (
    <Suspense fallback={<LoadingBlock label="LOADING…" />}>
      <Component />
    </Suspense>
  );
}

/**
 * Keep `/` as the signed-in Library destination while giving signed-out
 * visitors a real public homepage. Existing in-app links can keep pointing to
 * `/`, and the Library remains the first screen after authentication.
 */
function RootRoute() {
  const { session, loading } = useAuth();

  if (loading) {
    return <LoadingBlock label="OPENING SCENEWRIGHT…" />;
  }

  return session ? lazyRoute(Shell) : lazyRoute(HomePage);
}

function BackofficeRoute() {
  return lazyRoute(BackofficePage);
}

/** One canonical page view per route change, once auth state is known. */
function PageviewTracker() {
  const { pathname } = useLocation();
  const { session, loading } = useAuth();
  const signedIn = !!session;
  useEffect(() => {
    if (!loading) trackPageview(pathname, signedIn);
  }, [pathname, signedIn, loading]);
  return null;
}

export function App() {
  return (
    <I18nProvider>
      <PageviewTracker />
      <Routes>
        <Route path="/read/:id" element={lazyRoute(PublicBookPage)} />
        <Route path="/samples" element={lazyRoute(SampleLibraryPage)} />
        {/* Public auth routes */}
        <Route path="/login" element={lazyRoute(LoginPage)} />
        <Route path="/signup" element={lazyRoute(SignupPage)} />
        <Route path="/reset-password" element={lazyRoute(ResetPasswordPage)} />

        {/* Operator token gates every backoffice API request. */}
        <Route path="/backoffice" element={<BackofficeRoute />} />

        {/* Public homepage for visitors; signed-in users keep `/` as Library. */}
        <Route path="/" element={<RootRoute />}>
          <Route index element={lazyRoute(Library)} />
        </Route>

        {/* Public legal routes */}
        <Route path="/legal/terms" element={lazyRoute(TermsPage)} />
        <Route path="/legal/privacy" element={lazyRoute(PrivacyPage)} />
        <Route path="/legal/acceptable-use" element={lazyRoute(AcceptableUsePage)} />

        {/* Protected app routes */}
        <Route
          element={
            <AuthGuard>
              {lazyRoute(Shell)}
            </AuthGuard>
          }
        >
          <Route path="labs" element={LabsRoom ? lazyRoute(LabsRoom) : <Navigate to="/" replace />} />
          <Route
            path="dev/primitives"
            element={import.meta.env.DEV ? lazyRoute(PrimitiveReference) : <Navigate to="/" replace />}
          />
          <Route path="account" element={lazyRoute(AccountPage)} />
          <Route path="credits" element={lazyRoute(CreditsPage)} />
          <Route path="project/:id" element={lazyRoute(ProjectRooms)}>
            <Route path="settings" element={lazyRoute(ProjectSettingsPage)} />
            <Route index element={lazyRoute(NavigateToRoom)} />
            <Route path="story" element={lazyRoute(StoryRoom)} />
            <Route path="cast" element={lazyRoute(CastRoom)} />
            <Route path="pages" element={lazyRoute(PagesRoom)} />
            <Route path="book" element={lazyRoute(BookRoom)} />
            <Route path="styles" element={lazyRoute(StyleRoom)} />
            <Route path="*" element={lazyRoute(NavigateToRoom)} />
          </Route>
          <Route path="*" element={lazyRoute(NotFound)} />
        </Route>
      </Routes>
    </I18nProvider>
  );
}

export function AccountApp() {
  const { user, loading } = useAuth();
  if (loading) return null;
  return (
    <QueryClientProvider key={user?.id ?? "signed-out"} client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
