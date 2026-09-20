import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/useAuth';
import { Shell } from './components/Shell';
import { Spinner } from './components/primitives';
import { OidcCallbackPage } from './pages/OidcCallbackPage';
import { DevicesPage } from './pages/DevicesPage';
import { SessionsPage } from './pages/SessionsPage';
import { StartSessionPage } from './pages/StartSessionPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { AccountPage } from './pages/AccountPage';
import { AuthenticatedFlowPage } from './pages/AuthenticatedFlowPage';
import { CliConnectPage } from './pages/CliConnectPage';
import { DocsPage } from './pages/DocsPage';

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
          <Route path="/" element={<Navigate to="/app" replace />} />
          <Route path="/app" element={<AuthenticatedFlowPage />} />
          <Route path="/auth" element={<AccountPage />} />
          <Route path="/login" element={<Navigate to="/auth" replace />} />
          <Route path="/docs" element={<DocsPage />} />
          <Route path="/cli/authorize" element={<CliConnectPage />} />
          <Route path="/auth/callback" element={<OidcCallbackPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/sessions" element={<SessionsPage />} />
            <Route path="/sessions/new" element={<StartSessionPage />} />
            <Route path="/devices" element={<DevicesPage />} />
            <Route path="/session/:id" element={<CockpitPage />} />
            <Route path="/session/:id/report" element={<ReportPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </Suspense>
    </>
  );
}
