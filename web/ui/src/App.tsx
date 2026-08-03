import { lazy, Suspense } from "react";
import { HashRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import {
  AiScientistWorkspace,
  type AiScientistWorkspaceView,
} from "./pages/AiScientistWorkspace";

const MuniStudy = lazy(() => import("./pages/MuniStudy"));
const ReportView = lazy(() => import("./pages/ReportView"));
const RunProgress = lazy(() => import("./pages/RunProgress"));
const Settings = lazy(() => import("./pages/Settings"));
const DesignSystemShowcase = lazy(async () => {
  const module = await import("./pages/DesignSystemShowcase");
  return { default: module.DesignSystemShowcase };
});

function HomeRedirect() {
  return <Navigate to="/scientific" replace />;
}

function BackButton() {
  const navigate = useNavigate();
  const location = useLocation();
  if (location.pathname === "/") return null;
  const goBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate("/");
  };
  return (
    <header
      className="sticky top-0 z-30 flex items-center border-b border-white/5 bg-transparent pl-[88px] pr-4 py-2.5 backdrop-blur-xl supports-[backdrop-filter]:bg-black/20"
    >
      <button
        type="button"
        onClick={goBack}
        className="flex size-7 items-center justify-center rounded-md text-tertiary transition hover:bg-white/5 hover:text-white"
        title="뒤로"
        aria-label="뒤로"
      >
        <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
      </button>
    </header>
  );
}

export default function App() {
  return (
    <HashRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <Suspense fallback={<RouteFallback />}>
        <AppRoutes />
      </Suspense>
    </HashRouter>
  );
}

function RouteFallback() {
  return (
    <main className="app-workspace flex min-h-dvh items-center justify-center p-6">
      <p role="status" className="text-sm text-secondary">화면을 불러오는 중입니다.</p>
    </main>
  );
}

function AppRoutes() {
  const location = useLocation();
  const scientificView = scientificWorkspaceView(location.pathname);

  if (location.pathname === "/") {
    return <HomeRedirect />;
  }

  if (scientificView) {
    return <AiScientistWorkspace view={scientificView} />;
  }

  if (location.pathname === "/design-system") {
    return import.meta.env.DEV ? <DesignSystemShowcase /> : <Navigate to="/" replace />;
  }

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="app-workspace flex-1 overflow-y-auto">
        <BackButton />
        <Routes>
          <Route path="/studio" element={<Navigate to="/scientific" replace />} />
          <Route path="/studio/:studioId" element={<Navigate to="/scientific" replace />} />
          <Route path="/browser" element={<Navigate to="/scientific" replace />} />
          <Route path="/muni" element={<MuniStudy />} />
          <Route path="/browser/:runId" element={<RunProgress />} />
          <Route path="/browser/:runId/report" element={<ReportView />} />
          <Route path="/run/:runId" element={<RunProgress />} />
          <Route path="/report/:runId" element={<ReportView />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function scientificWorkspaceView(pathname: string): AiScientistWorkspaceView | undefined {
  if (pathname === "/scientific") return "chat";
  if (pathname === "/scientific/sources") return "sources";
  if (pathname === "/scientific/validation") return "validation";
  return undefined;
}
