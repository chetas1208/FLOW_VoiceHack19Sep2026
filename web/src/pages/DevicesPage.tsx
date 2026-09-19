import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { Chip, Dialog, EmptyState, PresenceDot, Spinner } from '../components/primitives';
import { api, ApiError } from '../lib/api';
import { ago } from '../lib/format';
import { useDocumentTitle, useNow } from '../lib/hooks';
import type { Device } from '../lib/types';
import { store, useStore } from '../store/store';
import { toast } from '../store/toasts';

const HEALTH_PARTS = ['observer', 'vision', 'voice', 'agent', 'daemon'];

function healthLevel(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v && typeof v === 'object' && 'status' in v) return String((v as { status: unknown }).status);
  return 'unknown';
}

export function DevicesPage() {
  useDocumentTitle('Devices');
  const devices = useStore((s) => s.devices);
  const loaded = useStore((s) => s.devicesLoaded);
  const now = useNow(15_000);
  const [revoking, setRevoking] = useState<Device | null>(null);
  const [busy, setBusy] = useState(false);
  const list = useMemo(() => Object.values(devices).sort((a, b) => Number(!!a.revoked_at) - Number(!!b.revoked_at) || (a.presence.state === 'offline' ? 1 : 0) - (b.presence.state === 'offline' ? 1 : 0) || a.name.localeCompare(b.name)), [devices]);

  async function revoke() {
    if (!revoking) return;
    setBusy(true);
    try {
      await api.revokeDevice(revoking.id);
      store.dispatch({ type: 'device/remove', deviceId: revoking.id });
      toast(`${revoking.name} was revoked.`, 'ok');
      setRevoking(null);
    } catch (e) { toast((e as ApiError).message, 'error'); }
    setBusy(false);
  }

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Devices</h1><p className="muted">Computers signed in to FLOW. Only devices that are online can start a session.</p></div>
      </header>
      {!loaded ? <Spinner /> : list.length === 0 ? (
        <EmptyState title="No devices yet">Sign in from a terminal with the FLOW command line tool. You will be sent here to authorize it.</EmptyState>
      ) : (
        <ul className="device-grid">
          {list.map((d) => (
            <li key={d.id} className={`device panel ${d.revoked_at ? 'is-revoked' : ''}`}>
              <div className="device-top">
                <span className={`device-glyph glyph-${d.presence.state}`}><Icon name="device" size={22} /></span>
                <div className="device-title">
                  <h2>{d.name}</h2>
                  <p className="muted">{d.os} on {d.architecture}, FLOW {d.flow_version}</p>
                </div>
                {d.revoked_at ? <Chip tone="bad">Revoked</Chip> : <PresenceDot state={d.presence.state} />}
              </div>
              <p className="muted small">
                {d.presence.state === 'offline' ? `Last seen ${ago(d.last_seen_at ?? d.presence.last_heartbeat_at, now)}` : `Heartbeat ${ago(d.presence.last_heartbeat_at, now)}`}
              </p>
              {!d.revoked_at && d.presence.state !== 'offline' && d.presence.health && (
                <ul className="health">
                  {HEALTH_PARTS.filter((p) => d.presence.health && p in d.presence.health).map((p) => {
                    const lvl = healthLevel(d.presence.health![p]);
                    return <li key={p} className={`health-${/error|fail/.test(lvl) ? 'bad' : /warn|degraded/.test(lvl) ? 'warn' : 'ok'}`}><i className="dot" aria-hidden="true" />{p} {lvl}</li>;
                  })}
                </ul>
              )}
              {(d.presence.active_sessions?.length ?? 0) > 0 && (
                <p className="small">Running: {d.presence.active_sessions!.map((sid) => <Link key={sid} to={`/session/${sid}`} className="link-quiet">open session</Link>)}</p>
              )}
              {!d.revoked_at && (
                <div className="device-actions">
                  <Link to={`/sessions/new?device=${d.id}`} className={`btn btn-secondary ${d.presence.state !== 'online' ? 'is-disabled' : ''}`} aria-disabled={d.presence.state !== 'online'} onClick={(e) => { if (d.presence.state !== 'online') e.preventDefault(); }}>Start session</Link>
                  <button type="button" className="btn btn-danger-ghost" onClick={() => setRevoking(d)}>Revoke</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <Dialog open={!!revoking} onClose={() => setRevoking(null)} title={`Revoke ${revoking?.name ?? 'device'}?`} tone="danger">
        <p>This device is signed out right away and can no longer upload activity or receive commands. Sessions on it stop syncing. To use it again, run the login command on that computer.</p>
        <div className="row-actions">
          <button type="button" className="btn btn-danger" disabled={busy} onClick={revoke}>{busy ? 'Revoking' : 'Revoke device'}</button>
          <button type="button" className="btn btn-secondary" onClick={() => setRevoking(null)}>Keep device</button>
        </div>
      </Dialog>
    </div>
  );
}
