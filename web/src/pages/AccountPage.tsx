import { FormEvent, useEffect, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { browserSession } from '../auth/browserSession';

type Mode = 'signin' | 'create';

function safeNext(value: string | null) {
  return value?.startsWith('/') && !value.startsWith('//') ? value : '/app';
}

export function AccountPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNext(params.get('next'));
  const [mode, setMode] = useState<Mode>('signin');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    browserSession().then((session) => setSignedIn(Boolean(session))).catch(() => undefined).finally(() => setReady(true));
  }, []);

  if (signedIn) return <Navigate to={next} replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    if (mode === 'create' && password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setBusy(true);
    try {
      const response = await fetch(`/api/auth/${mode === 'create' ? 'register' : 'login'}`, {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mode === 'create' ? { name, email, password } : { email, password }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.message || 'Unable to continue. Try again.');
      navigate(next, { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to continue. Try again.');
      setBusy(false);
    }
  }

  return <main className="account-page">
    <section className="account-intro"><div className="account-brand">FLOW</div><p className="account-kicker">FOCUS TODAY. A BETTER TOMORROW.</p><h1>Your local AI<br />work intelligence system.</h1><p className="account-copy">A private workspace for focused sessions, thoughtful agent help, and clear control of your connected devices.</p><small>All work-session data stays on your machine.</small></section>
    <section className="account-card" aria-busy={!ready || busy}>
      <div className="account-mode" role="tablist" aria-label="Account action"><button type="button" role="tab" aria-selected={mode === 'signin'} className={mode === 'signin' ? 'is-active' : ''} onClick={() => { setMode('signin'); setError(''); }}>Sign in</button><button type="button" role="tab" aria-selected={mode === 'create'} className={mode === 'create' ? 'is-active' : ''} onClick={() => { setMode('create'); setError(''); }}>Create account</button></div>
      <h2>{mode === 'signin' ? 'Welcome back' : 'Create your FLOW account'}</h2><p>{mode === 'signin' ? 'Sign in to view your connected FLOW workspace.' : 'Create an account to link your Mac and FLOW CLI.'}</p>
      <form onSubmit={submit}>
        {mode === 'create' && <label><span>Full name</span><input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" required maxLength={120} /></label>}
        <label><span>Email</span><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required /></label>
        <label><span>Password</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === 'create' ? 'new-password' : 'current-password'} required minLength={12} /></label>
        {mode === 'create' && <label><span>Confirm password</span><input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" required minLength={12} /></label>}
        {mode === 'create' && <small className="password-help">Use at least 12 characters.</small>}
        {error && <p className="account-error" role="alert">{error}</p>}
        <button type="submit" disabled={!ready || busy}>{busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}</button>
      </form>
    </section>
  </main>;
}
