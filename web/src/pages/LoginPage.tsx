import { FormEvent, useEffect, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { auth } from '../auth/auth';
import { beginLogin } from '../auth/oidc';
import { jwtExpiry, safeReturnTo } from '../auth/storage';
import { useAuth } from '../auth/useAuth';
import { Wordmark } from '../components/Shell';
import { config } from '../config';
import { devLogin } from '../lib/api';
import { useDocumentTitle } from '../lib/hooks';

export function LoginPage() {
  useDocumentTitle('Sign in');
  const { status, notice } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeReturnTo(params.get('next'), '/sessions');
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => () => auth.clearNotice(), []);
  if (status === 'signedIn') return <Navigate to={next} replace />;

  async function submitLocal(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const token = await devLogin(email.trim());
      auth.setCredentials({ token, email: email.trim(), expiresAt: jwtExpiry(token) });
      navigate(next, { replace: true });
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }
  async function submitOidc() {
    setBusy(true); setError(null);
    try { await beginLogin(next); } catch (err) { setError((err as Error).message); setBusy(false); }
  }

  return (
    <div className="login">
      <section className="login-hero" aria-hidden="false">
        <Wordmark />
        <h1>Your work session, from any screen.</h1>
        <p>Watch what you and your agent are doing, approve what it asks for, and steer without touching your Mac.</p>
        <div className="runway-art" aria-hidden="true">
          <span className="rail rail-h" /><span className="rail rail-a" />
          {[0, 1, 2, 3, 4].map((i) => <i key={i} className={`pip pip-${i % 2 ? 'a' : 'h'}`} style={{ ['--i' as string]: i }} />)}
        </div>
      </section>
      <section className="login-card panel">
        <h2>Sign in</h2>
        {notice && <p className="banner banner-warn" role="alert">{notice}</p>}
        {config.authMode === 'local' ? (
          <form onSubmit={submitLocal} className="form">
            <p className="muted">Development sign-in. Use any email; the API creates a dev token.</p>
            <label className="field">
              <span>Email</span>
              <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoFocus />
            </label>
            <button className="btn btn-primary btn-lg" disabled={busy || !email}>{busy ? 'Signing in' : 'Sign in'}</button>
          </form>
        ) : (
          <div className="form">
            <p className="muted">You will sign in with your organization's identity provider.</p>
            <button className="btn btn-primary btn-lg" onClick={submitOidc} disabled={busy}>{busy ? 'Redirecting' : 'Continue to sign in'}</button>
          </div>
        )}
        {error && <p className="banner banner-bad" role="alert">{error}</p>}
      </section>
    </div>
  );
}
