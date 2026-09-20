import { useState, type CSSProperties } from 'react';
import type { FlowDevice } from '../../lib/account';
import { ago, daemonStatus, pairingState, presenceLabel, type PresenceState } from '../../lib/flowDeviceModel';
import { SessionHeroScene, SessionTimelineTrack, WORKSPACE_STAGES } from './CockpitScenes';
import { FlowIcon } from './FlowIcon';

const METRIC_DEFS = [
  { label: 'Session Efficiency', color: 'mint' as const },
  { label: 'Goal Alignment', color: 'mint' as const },
  { label: 'Focus', color: 'blue' as const },
  { label: 'Progress', color: 'gold' as const },
];

function MetricRing({ label, value, status, color }: { label: string; value: number | '—'; status: string; color: 'mint' | 'blue' | 'gold' }) {
  const n = value === '—' ? 0 : value;
  return (
    <div className="metric">
      <span className={`metric-ring ${color}`} style={{ '--progress': `${n * 3.6}deg` } as CSSProperties}><b>{value}</b></span>
      <span className="metric-copy"><strong>{label}</strong><em>{status}</em></span>
    </div>
  );
}

export function SessionWorkspace({
  device,
  pairing,
  presence,
  onDocs,
}: {
  device: FlowDevice | null;
  pairing: ReturnType<typeof pairingState>;
  presence: PresenceState;
  onDocs: () => void;
  onShowcase?: () => void;
}) {
  const health = device?.presence.health ?? {};
  const unpaired = pairing === 'unpaired' || pairing === 'revoked';
  const online = pairing === 'paired' && presence === 'online';
  const [stageIndex, setStageIndex] = useState(0);

  let title = 'Ready when you are';
  let detail = 'Run flow start with a goal on your linked computer.';
  if (unpaired) {
    title = 'Link your machine';
    detail = 'Pair with flow login — this cockpit connects to your device when the daemon is online.';
  } else if (!online) {
    title = presence === 'connecting' ? 'Connecting…' : `${device!.name}`;
    detail = `${presenceLabel(presence)} · still linked · last seen ${ago(device!.last_seen_at ?? device!.presence.last_heartbeat_at)}`;
  }

  const sceneLabel = unpaired ? 'Your workspace' : (device?.name ?? 'Device');
  const sceneSub = unpaired ? 'Link to begin' : online ? 'Ready for flow start' : daemonStatus(health.daemon, presence);

  return (
    <section className="session-workspace" aria-label="Session workspace">
      <aside className="glass-panel goal-panel">
        {unpaired && (
          <p className="connect-banner">Run <code>flow login</code> on your computer, then approve this browser.</p>
        )}
        {!unpaired && !online && (
          <p className="connect-banner">On your machine: <code>flow daemon start</code></p>
        )}
        <div className="eyebrow-row"><span>Current Goal</span><button type="button" disabled={!online}><FlowIcon>✎</FlowIcon> Edit</button></div>
        <h2>{online ? <>Waiting for your<br />next session goal</> : <>Set a goal with<br /><code>flow start</code></>}</h2>
        <p className="session-started"><i aria-hidden="true" />{online ? 'No active session' : unpaired ? 'Not linked' : 'Device linked'}</p>
        <div className="metric-stack">
          {METRIC_DEFS.map((m, i) => (
            <MetricRing
              key={m.label}
              label={m.label}
              value="—"
              status={online ? 'Live when session runs' : i === 0 ? 'No session yet' : '—'}
              color={m.color}
            />
          ))}
        </div>
        <blockquote>“Consistent steps<br />create extraordinary results.”<small>— FLOW</small></blockquote>
      </aside>

      <section className="session-center" aria-label="Session focus">
        <div className="stage-title">
          <small>{unpaired ? 'Setup' : `Stage ${stageIndex + 1} of ${WORKSPACE_STAGES.length}`}</small>
          <h1>{title}</h1>
          <p>{detail}</p>
        </div>
        {!unpaired && (
          <ol className="stage-rail" aria-label="Session stages">
            {WORKSPACE_STAGES.map((item, index) => (
              <li key={item.label} className={index === stageIndex ? 'is-current' : index < stageIndex ? 'is-complete' : ''}>
                <button type="button" onClick={() => setStageIndex(index)} aria-label={`${item.label} stage`}>
                  <span>{index < stageIndex ? '✓' : item.symbol}</span>
                  <small>{item.label}</small>
                </button>
              </li>
            ))}
          </ol>
        )}
        <SessionHeroScene deviceLabel={sceneLabel} sublabel={sceneSub} activity={online ? 'Listening on device' : 'GOOD THINGS TAKE FOCUS'} />
      </section>

      <aside className="glass-panel insight-panel">
        <header><span><FlowIcon>☼</FlowIcon> AI Insight</span><b>{online ? 'Listening' : 'Standby'}</b></header>
        <p>
          {unpaired && 'Pair your device to receive live insights from local sessions.'}
          {!unpaired && !online && 'Your device is still linked. Start the daemon locally — this panel fills in when a session is running.'}
          {online && 'Insights and recommendations appear when you run flow start and observations stream from your machine.'}
        </p>
        {!unpaired && (
          <>
            <div className="panel-divider" />
            <p className="panel-empty">Evidence and next actions show here during an active session.</p>
            {!online && (
              <button type="button" className="secondary-action" onClick={onDocs}>Daemon help in Docs</button>
            )}
          </>
        )}
        {unpaired && <button type="button" className="primary-action" onClick={onDocs}>Setup in Docs</button>}
      </aside>

      <SessionTimelineTrack />

      <section className="glass-panel activity-panel" aria-label="Live activity">
        <header><strong><i aria-hidden="true" />Live Activity</strong></header>
        <p className="panel-empty">{online ? 'No observations yet — start a session with flow start.' : 'Activity appears here from your linked device during sessions.'}</p>
      </section>
    </section>
  );
}
