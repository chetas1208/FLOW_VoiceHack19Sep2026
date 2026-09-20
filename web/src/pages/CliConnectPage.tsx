import { useEffect, useState } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import { browserSession } from '../auth/browserSession';
import { accountApi, type CliRequest } from '../lib/account';

export function CliConnectPage() {
  const [params] = useSearchParams();
  const requestId = params.get('request') ?? '';
  const state = params.get('state') ?? '';
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [request, setRequest] = useState<CliRequest | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    browserSession().then((value) => setSignedIn(Boolean(value))).catch(() => setMessage('FLOW could not verify your account.')).finally(() => setReady(true));
  }, []);
  useEffect(() => {
    if (!signedIn || !requestId || !state) return;
    accountApi.cliRequest(requestId).then(setRequest).catch((error: Error) => setMessage(error.message));
  }, [requestId, signedIn, state]);

  if (!ready) return <main className="account-status">Checking your secure FLOW session…</main>;
  if (!signedIn) return <Navigate to={`/auth?next=${encodeURIComponent(`/cli/authorize?request=${requestId}&state=${state}`)}`} replace />;

  async function decide(decision: 'approve' | 'deny') {
    if (!request) return;
    setBusy(true); setMessage('');
    try {
      const result = decision === 'approve' ? await accountApi.approveCliRequest(request.request_id, state) : await accountApi.denyCliRequest(request.request_id);
      setRequest({ ...request, status: result.status as CliRequest['status'] });
      setMessage(result.status === 'approved' ? 'Device approved. Return to your terminal; FLOW will finish signing in.' : 'Device request denied. No local credential was issued.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'FLOW could not update this device request.'); }
    setBusy(false);
  }

  return <main className="connect-page"><section className="connect-card">
    <Link to="/app" className="docs-brand">FLOW</Link><p className="account-kicker">DEVICE AUTHORIZATION</p>
    {!request && !message && <p>Loading device request…</p>}
    {request && <><h1>Connect {request.device.name}?</h1><p>This grants the local FLOW CLI access to your account’s device control plane. It does not upload screen, session, source-code, prompt, or voice data.</p>
      <dl><div><dt>System</dt><dd>{request.device.os} · {request.device.architecture}</dd></div><div><dt>FLOW</dt><dd>{request.device.flow_version}</dd></div><div><dt>Expires</dt><dd>{new Date(request.expires_at).toLocaleTimeString()}</dd></div></dl>
      {request.status === 'pending' ? <div className="connect-actions"><button type="button" disabled={busy} onClick={() => decide('approve')}>{busy ? 'Please wait…' : 'Approve device'}</button><button type="button" disabled={busy} onClick={() => decide('deny')}>Deny</button></div> : <p className="connect-status">This request is {request.status}.</p>}</>}
    {message && <p className="connect-status" role="status">{message}</p>}<Link to="/docs" className="docs-back">Read connection docs</Link>
  </section></main>;
}
