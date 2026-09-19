import { useMemo, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { auth } from '../auth/auth';
import { useAuth } from '../auth/useAuth';
import { config } from '../config';
import { useUserChannel } from '../realtime/useUserChannel';
import { dismissToast, useToasts } from '../store/toasts';
import { useStore } from '../store/store';
import { ApprovalCard } from './ApprovalCard';
import { Icon } from './Icon';
import { Dialog } from './primitives';
import { Link } from 'react-router-dom';

export function Wordmark() {
  return (
    <span className="wordmark" aria-label="FLOW">
      <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
        <path d="M6 24 L16 6 L26 24" fill="none" stroke="#8b6cff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M10.5 24 L16 14.5 L21.5 24" fill="none" stroke="#38e1ff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="wordmark-text">flow</span>
    </span>
  );
}

export function Shell() {
  useUserChannel(true);
  const { email } = useAuth();
  const navigate = useNavigate();
  const inbox = useStore((s) => s.inbox);
  const devices = useStore((s) => s.devices);
  const userConn = useStore((s) => s.userConn);
  const sessionIndex = useStore((s) => s.sessionIndex);
  const [open, setOpen] = useState(false);
  const pending = useMemo(() => Object.values(inbox).sort((a, b) => a.requested_at.localeCompare(b.requested_at)), [inbox]);

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <Link to="/sessions" className="brand"><Wordmark /></Link>
        <nav className="nav" aria-label="Primary">
          <NavLink to="/sessions" end>Sessions</NavLink>
          <NavLink to="/sessions/new">Start session</NavLink>
          <NavLink to="/devices">Devices</NavLink>
        </nav>
        <div className="topbar-right">
          {userConn === 'reconnecting' && <span className="conn-note" role="status">Reconnecting</span>}
          <button type="button" className={`inbox-btn ${pending.length ? 'has-items' : ''}`} onClick={() => setOpen(true)} aria-label={pending.length ? `Approvals inbox, ${pending.length} waiting` : 'Approvals inbox'}>
            <Icon name="shield" size={16} />
            {pending.length > 0 ? <><span className="inbox-flag">ACTION NEEDED</span><span className="inbox-count">{pending.length}</span></> : <span className="inbox-quiet">No approvals</span>}
          </button>
          <div className="me">
            <span className="me-email" title={email}>{email ?? 'Signed in'}</span>
            <button type="button" className="icon-btn" onClick={() => { auth.signOut(); navigate('/login'); }} aria-label="Sign out" title="Sign out"><Icon name="logout" /></button>
          </div>
        </div>
      </header>
      {config.authMode === 'local' && <div className="devbar">Development sign-in is on. Do not use this build with real accounts.</div>}
      <main id="main" className="main"><Outlet /></main>

      <Dialog open={open} onClose={() => setOpen(false)} title={pending.length ? `Waiting for you (${pending.length})` : 'Approvals inbox'}>
        {pending.length === 0 ? (
          <p className="muted">Nothing is waiting. When a delegated task needs permission, it appears here and on the session.</p>
        ) : (
          <div className="stack">
            {pending.map((a) => (
              <div key={a.id}>
                <ApprovalCard approval={a} deviceId={sessionIndex[a.session_id]?.device_id}
                  sessionLabel={sessionIndex[a.session_id]?.goal ? `In session: ${sessionIndex[a.session_id]!.goal}` : undefined}
                  disabledReason={devices[sessionIndex[a.session_id]?.device_id ?? '']?.presence.state === 'offline' ? 'This device is offline. Approvals cannot be queued.' : null} />
                <Link className="link-quiet" to={`/session/${a.session_id}`} onClick={() => setOpen(false)}>Open session</Link>
              </div>
            ))}
          </div>
        )}
      </Dialog>
      <Toasts />
    </div>
  );
}

function Toasts() {
  const toasts = useToasts();
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.tone}`}>
          <span>{t.text}</span>
          <button type="button" className="icon-btn" onClick={() => dismissToast(t.id)} aria-label="Dismiss"><Icon name="x" size={14} /></button>
        </div>
      ))}
    </div>
  );
}
