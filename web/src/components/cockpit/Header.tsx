import { Link } from 'react-router-dom';
import { duration, STATUS_LABEL } from '../../lib/format';
import { useNow } from '../../lib/hooks';
import type { PresenceState } from '../../lib/types';
import type { ConnStatus, SessionSlice } from '../../store/reducer';
import { Icon } from '../Icon';
import { Chip, PresenceDot } from '../primitives';

const statusTone = (s: string) => (s === 'active' || s === 'executing_delegated_task' ? 'cyan' : s === 'paused' || s === 'waiting_for_user' || s === 'recovering' ? 'warn' : s === 'completed' ? 'ok' : s === 'failed' || s === 'offline' ? 'bad' : 'neutral');

export function CockpitHeader({ slice, presence, deviceName }: { slice: SessionSlice; presence: PresenceState; deviceName: string }) {
  const s = slice.session;
  const ended = !!s?.ended_at || s?.status === 'completed' || s?.status === 'failed';
  const now = useNow(1000);
  const start = s ? new Date(s.started_at).getTime() : now;
  const end = s?.ended_at ? new Date(s.ended_at).getTime() : now;
  const paused = s?.status === 'paused';
  return (
    <header className="ck-head">
      <Link to="/sessions" className="back" aria-label="Back to sessions"><Icon name="chevron" style={{ transform: 'rotate(90deg)' }} /></Link>
      <div className="ck-head-main">
        <p className="ck-device"><span>{deviceName}</span><PresenceDot state={presence} /></p>
        <h1 className="ck-goal" title={slice.goal.text || s?.goal}>{slice.goal.text || s?.goal || 'Session'}</h1>
      </div>
      <div className="ck-head-side">
        <span className={`ck-clock ${paused ? 'is-paused' : ''}`} aria-label="Session duration"><Icon name="clock" size={15} />{duration((end - start) / 1000)}</span>
        {s && <Chip tone={statusTone(s.status) as 'ok'}>{STATUS_LABEL[s.status] ?? s.status}</Chip>}
        <ConnBadge conn={slice.conn} ended={ended} />
      </div>
    </header>
  );
}

function ConnBadge({ conn, ended }: { conn: ConnStatus; ended: boolean }) {
  if (ended) return null;
  const map: Record<ConnStatus, [string, string]> = {
    live: ['live', 'Live'], connecting: ['wait', 'Connecting'], reconnecting: ['wait', 'Reconnecting'], unauthorized: ['bad', 'Signed out'], idle: ['wait', 'Connecting'],
  };
  const [cls, text] = map[conn];
  return <span className={`conn conn-${cls}`} role="status"><i aria-hidden="true" />{text}</span>;
}
