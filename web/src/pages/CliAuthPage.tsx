import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { Spinner } from '../components/primitives';
import { api, ApiError } from '../lib/api';
import { untilLabel } from '../lib/format';
import { useDocumentTitle, useNow } from '../lib/hooks';
import type { CliAuthRequest } from '../lib/types';

const ID_RE = /^[A-Za-z0-9_-]{8,80}$/;

export function CliAuthPage() {
  useDocumentTitle('Authorize a device');
  const [params] = useSearchParams();
  const id = params.get('request') ?? '';
  const now = useNow(1000);
  const [req, setReq] = useState<CliAuthRequest | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [matches, setMatches] = useState(false);
  const [busy, setBusy] = useState<null | 'approve' | 'deny'>(null);
  const [outcome, setOutcome] = useState<null | 'approved' | 'denied'>(null);

  useEffect(() => {
    if (!ID_RE.test(id)) { setError(new ApiError(400, 'invalid_request', 'This link is missing its request id.')); return; }
    let live = true;
    api.cliRequest(id).then((r) => live && setReq(r)).catch((e) => live && setError(e));
    return () => { live = false; };
  }, [id]);

  async function decide(kind: 'approve' | 'deny') {
    setBusy(kind); setError(null);
    try {
      await (kind === 'approve' ? api.cliApprove(id) : api.cliDeny(id));
      setOutcome(kind === 'approve' ? 'approved' : 'denied');
    } catch (e) { setError(e as ApiError); }
    setBusy(null);
  }

  const expired = req ? new Date(req.expires_at).getTime() <= now : false;
  const left = req ? untilLabel(req.expires_at, now) : null;
  const done = outcome ?? (req && req.status !== 'pending' ? (req.status as string) : null);

  return (
    <div className="narrow-page">
      <h1>Authorize a device</h1>
      {!req && !error && <Spinner />}
      {error && !req && (
        <div className="panel">
          <p className="banner banner-bad" role="alert">{error.code === 'not_found' ? 'This request was not found. It may have expired, or it belongs to a different account.' : error.message}</p>
          <p className="muted">Run the login command in your terminal again to get a fresh link.</p>
          <Link className="btn btn-secondary" to="/devices">View devices</Link>
        </div>
      )}
      {req && (
        <div className="panel auth-request">
          <div className="auth-device">
            <span className="auth-device-icon"><Icon name="device" size={22} /></span>
            <div>
              <h2>{req.device.name}</h2>
              <p className="muted">{req.device.os} on {req.device.architecture}, FLOW {req.device.flow_version}</p>
            </div>
          </div>

          <div className="code-block">
            <p className="code-caption">Code shown in your terminal</p>
            <p className="user-code" aria-label={`Verification code ${req.user_code.split('').join(' ')}`}>{req.user_code}</p>
          </div>

          {done ? (
            <p className={`banner ${done === 'approved' ? 'banner-ok' : 'banner-warn'}`} role="status">
              {done === 'approved' ? 'Device authorized. Return to your terminal; it will finish signing in.'
                : done === 'denied' ? 'Request denied. The device was not given access.'
                : done === 'expired' ? 'This request expired. Run the login command again.'
                : `This request is already ${done}.`}
            </p>
          ) : expired ? (
            <p className="banner banner-warn" role="status">This request expired. Run the login command in your terminal again.</p>
          ) : (
            <>
              <div className="banner banner-caution">
                <Icon name="alert" />
                <p>Only continue if you just started signing in on this device yourself and the code above matches your terminal exactly. FLOW never asks you to approve a code that someone else sent you.</p>
              </div>
              <ul className="grant-list">
                <li>Can upload activity summaries from this device. Screen images are never uploaded.</li>
                <li>Can receive the commands you send from this app.</li>
                <li>Can be revoked at any time from Devices.</li>
              </ul>
              <label className="check check-strong">
                <input type="checkbox" checked={matches} onChange={(e) => setMatches(e.target.checked)} />
                <span>The code matches my terminal and I started this sign-in.</span>
              </label>
              {error && <p className="banner banner-bad" role="alert">{error.message}</p>}
              <div className="row-actions">
                <button type="button" className="btn btn-primary btn-lg" disabled={!matches || busy !== null} onClick={() => decide('approve')}>{busy === 'approve' ? 'Authorizing' : 'Authorize device'}</button>
                <button type="button" className="btn btn-danger-ghost btn-lg" disabled={busy !== null} onClick={() => decide('deny')}>{busy === 'deny' ? 'Denying' : 'Deny'}</button>
              </div>
              {left && <p className="hint">Expires in {left}.</p>}
            </>
          )}
          {done === 'approved' && <Link className="btn btn-secondary" to="/devices">View devices</Link>}
        </div>
      )}
    </div>
  );
}
