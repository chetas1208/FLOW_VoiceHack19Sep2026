import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/useAuth';
import { Shell } from './components/Shell';
import { Spinner } from './components/primitives';
import { LoginPage } from './pages/LoginPage';
import { OidcCallbackPage } from './pages/OidcCallbackPage';
import { DevicesPage } from './pages/DevicesPage';
import { SessionsPage } from './pages/SessionsPage';
import { StartSessionPage } from './pages/StartSessionPage';
import { CliAuthPage } from './pages/CliAuthPage';
import { NotFoundPage } from './pages/NotFoundPage';
import FlowDemoPage from './pages/FlowDemoPage';

const CockpitPage = lazy(() => import('./pages/CockpitPage'));
const ReportPage = lazy(() => import('./pages/ReportPage'));

function RequireAuth() {
  const { status } = useAuth();
  const loc = useLocation();
  if (status !== 'signedIn') return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  return <Shell />;
}

export function App() {
  return (
    <>
      <div className="floor" aria-hidden="true" />
      <Suspense fallback={<div className="page-loading"><Spinner /></div>}>
        <Routes>
          <Route path="/" element={<FlowDemoPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<OidcCallbackPage />} />
          <Route element={<RequireAuth />}>
            <Route index element={<Navigate to="/sessions" replace />} />
            <Route path="/sessions" element={<SessionsPage />} />
            <Route path="/sessions/new" element={<StartSessionPage />} />
            <Route path="/devices" element={<DevicesPage />} />
            <Route path="/cli/auth" element={<CliAuthPage />} />
            <Route path="/session/:id" element={<CockpitPage />} />
            <Route path="/session/:id/report" element={<ReportPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </Suspense>
    </>
  );
}
