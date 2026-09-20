import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { browserSession, type BrowserSession } from '../auth/browserSession';
import FlowDemoPage from './FlowDemoPage';

export function AuthenticatedFlowPage() {
  const [session, setSession] = useState<BrowserSession | null | undefined>(undefined);
  const [error, setError] = useState(false);

  useEffect(() => {
    browserSession().then(setSession).catch(() => setError(true));
  }, []);

  if (error) return <main className="account-status"><h1>FLOW is temporarily unavailable.</h1><p>Try refreshing the page in a moment.</p></main>;
  if (session === undefined) return <main className="account-status" aria-live="polite">Checking your secure FLOW session…</main>;
  if (!session) return <Navigate to="/auth?next=/app" replace />;
  return <FlowDemoPage account={session.user} />;
}
