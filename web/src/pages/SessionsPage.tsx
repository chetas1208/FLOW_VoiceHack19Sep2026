import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Chip, EmptyState, Spinner } from '../components/primitives';
import { api, ApiError } from '../lib/api';
import { ago, dateTime, duration, STATUS_LABEL } from '../lib/format';
import { useDocumentTitle, useNow } from '../lib/hooks';
import type { SessionOut } from '../lib/types';
import { store, useStore } from '../store/store';

const FILTERS: Array<{ id: string; label: string }> = [
  { id: '', label: 'All' }, { id: 'active', label: 'Active' }, { id: 'paused', label: 'Paused' }, { id: 'completed', label: 'Completed' },
];
const PAGE = 20;

const tone = (s: string) => (s === 'active' || s === 'executing_delegated_task' ? 'cyan' : s === 'paused' || s === 'waiting_for_user' ? 'warn' : s === 'completed' ? 'ok' : s === 'failed' ? 'bad' : 'neutral');

export function SessionsPage() {
  useDocumentTitle('Sessions');
  const [status, setStatus] = useState('');
  const [device, setDevice] = useState('');
  const [ids, setIds] = useState<string[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const index = useStore((s) => s.sessionIndex);
  const devices = useStore((s) => s.devices);
  const now = useNow(1000);

  const load = useCallback(async (reset: boolean, from: string | null) => {
    reset ? setLoading(true) : setMore(true);
    setError(null);
    try {
      const page = await api.sessions({ status, device_id: device, limit: PAGE, cursor: from });
      for (const s of page.items) store.dispatch({ type: 'session/upsert', session: s });
      setIds((prev) => (reset ? page.items.map((s) => s.id) : [...prev, ...page.items.map((s) => s.id).filter((id) => !prev.includes(id))]));
      setCursor(page.next_cursor ?? null);
    } catch (e) { setError(e as ApiError); }
    setLoading(false); setMore(false);
  }, [status, device]);

  useEffect(() => { void load(true, null); }, [load]);

  const rows = useMemo(() => ids.map((id) => index[id]).filter((s): s is SessionOut => !!s && (!status || s.status === status)), [ids, index, status]);

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Sessions</h1><p className="muted">Everything you have run, newest first.</p></div>
        <Link to="/sessions/new" className="btn btn-primary">Start a session</Link>
      </header>
      <div className="filters" role="group" aria-label="Filter sessions">
        <div className="seg">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" className={status === f.id ? 'is-on' : ''} aria-pressed={status === f.id} onClick={() => setStatus(f.id)}>{f.label}</button>
          ))}
        </div>
        <label className="select-field">
          <span className="sr-only">Device</span>
          <select value={device} onChange={(e) => setDevice(e.target.value)}>
            <option value="">All devices</option>
            {Object.values(devices).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
      </div>
      {loading ? <Spinner /> : error ? (
        <p className="banner banner-bad" role="alert">{error.message} <button className="link-btn" onClick={() => load(true, null)}>Try again</button></p>
      ) : rows.length === 0 ? (
        <EmptyState title={status ? `No ${status} sessions` : 'No sessions yet'} action={<Link to="/sessions/new" className="btn btn-primary">Start a session</Link>}>
          Pick a device, say what you are working on, and FLOW starts coaching.
        </EmptyState>
      ) : (
        <ul className="session-list">
          {rows.map((s) => {
            const live = s.status !== 'completed' && s.status !== 'failed';
            const end = s.ended_at ? new Date(s.ended_at).getTime() : now;
            return (
              <li key={s.id}>
                <Link to={live ? `/session/${s.id}` : `/session/${s.id}/report`} className="session-row">
                  <div className="session-main">
                    <h2>{s.goal}</h2>
                    <p className="muted small">{s.device_name ?? 'Unknown device'}<span className="sep" aria-hidden="true" />{dateTime(s.started_at)}<span className="sep" aria-hidden="true" />{live ? `running ${duration((end - new Date(s.started_at).getTime()) / 1000)}` : `${duration((end - new Date(s.started_at).getTime()) / 1000)} total`}</p>
                  </div>
                  <div className="session-side">
                    {s.runtime_state?.voice_muted_until && new Date(s.runtime_state.voice_muted_until).getTime() > now && <Chip tone="neutral">Quiet</Chip>}
                    <Chip tone={tone(s.status) as 'ok'}>{STATUS_LABEL[s.status] ?? s.status}</Chip>
                    <span className="muted small">{live ? 'Open cockpit' : `Ended ${ago(s.ended_at, now)}`}</span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      {cursor && !loading && <div className="center"><button className="btn btn-secondary" disabled={more} onClick={() => load(false, cursor)}>{more ? 'Loading' : 'Load more'}</button></div>}
    </div>
  );
}
