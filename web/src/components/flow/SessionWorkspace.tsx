import { useCallback, useState, type CSSProperties } from 'react';
import type { FlowDevice } from '../../lib/account';
import { ago, daemonStatus, pairingState, presenceLabel, type PresenceState } from '../../lib/flowDeviceModel';
import { WORKSPACE_STAGES } from './CockpitScenes';
import { FlowIcon } from './FlowIcon';
import { InteractiveTimeline } from './InteractiveTimeline';

const METRIC_DEFS = [
  { label: 'Session Efficiency', color: 'mint' as const, blurb: 'How steadily you moved toward the goal without thrash.' },
  { label: 'Goal Alignment', color: 'mint' as const, blurb: 'Share of observed activity linked to your stated goal.' },
  { label: 'Focus', color: 'blue' as const, blurb: 'Longest uninterrupted blocks of aligned work.' },
  { label: 'Progress', color: 'gold' as const, blurb: 'Evidence-backed steps completed toward the goal.' },
];

const ACTIVITY_STUBS = [
  { icon: '⌘', label: 'Waiting for observations', detail: 'Start flow start on your device to populate this feed.' },
  { icon: '⌁', label: 'Daemon channel', detail: 'Live rows stream from your linked machine only.' },
  { icon: '▤', label: 'Privacy', detail: 'No screen content is uploaded — metadata stays local.' },
];

function MetricRing({
  label,
  value,
  status,
  color,
  active,
  blurb,
  onToggle,
}: {
  label: string;
  value: number | '—';
  status: string;
  color: 'mint' | 'blue' | 'gold';
  active: boolean;
  blurb: string;
  onToggle: () => void;
}) {
  const n = value === '—' ? 0 : value;
  return (
    <div className={`metric${active ? ' is-active' : ''}`}>
      <button type="button" className="metric-hit" onClick={onToggle} aria-pressed={active}>
        <span className={`metric-ring ${color}`} style={{ '--progress': `${n * 3.6}deg` } as CSSProperties}><b>{value}</b></span>
        <span className="metric-copy"><strong>{label}</strong><em>{status}</em></span>
      </button>
      {active && <p className="metric-blurb">{blurb}</p>}
    </div>
  );
}

export function SessionWorkspace({
  device,
  pairing,
  presence,
  onDocs,
  onAnnounce,
  onGoAgent,
  stopped,
  paused,
}: {
  device: FlowDevice | null;
  pairing: ReturnType<typeof pairingState>;
  presence: PresenceState;
  onDocs: () => void;
  onAnnounce: (message: string) => void;
  onGoAgent?: () => void;
  stopped?: boolean;
  paused?: boolean;
}) {
  const health = device?.presence.health ?? {};
  const unpaired = pairing === 'unpaired' || pairing === 'revoked';
  const online = pairing === 'paired' && presence === 'online';
  const [stageIndex, setStageIndex] = useState(0);
  const [metricFocus, setMetricFocus] = useState<number | null>(null);
  const [goalDraft, setGoalDraft] = useState('');
  const [editingGoal, setEditingGoal] = useState(false);
  const [activityOpen, setActivityOpen] = useState<number | null>(0);

  const stage = WORKSPACE_STAGES[stageIndex]!;

  const selectStage = useCallback((index: number) => {
    setStageIndex(index);
    onAnnounce(`${WORKSPACE_STAGES[index]!.label} stage selected.`);
  }, [onAnnounce]);

  let title = stopped ? 'Session stopped' : paused ? 'Session paused' : stage.label;
  let detail = stopped ? 'Use controls below to resume or pick a stage.' : paused ? 'FLOW is holding observations until you resume.' : stage.detail;
  if (unpaired) {
    title = 'Link your machine';
    detail = 'Pair with flow login — this cockpit connects to your device when the daemon is online.';
  } else if (!online && !stopped) {
    title = presence === 'connecting' ? 'Connecting…' : `${device!.name}`;
    detail = `${presenceLabel(presence)} · still linked · last seen ${ago(device!.last_seen_at ?? device!.presence.last_heartbeat_at)}`;
  }

  const sceneLabel = unpaired ? 'Your workspace' : (device?.name ?? 'Device');
  const sceneSub = unpaired ? 'Link to begin' : online ? 'Ready for flow start' : daemonStatus(health.daemon, presence);
  const sceneActivity = stopped ? 'Paused' : online ? stage.activity : stage.activity;

  const copyStart = () => {
    void navigator.clipboard.writeText('flow start "your goal"').then(
      () => onAnnounce('Copied: flow start "your goal"'),
      () => onAnnounce('Copy flow start from Docs'),
    );
  };

  return (
    <section className="session-workspace cockpit-overlay" aria-label="Session workspace">
      <div className="cockpit-float-layer" aria-hidden="true">
        <button type="button" className="scene-card editor-card scene-card-btn cockpit-float" onClick={() => onAnnounce(unpaired ? 'Link a device to mirror your workspace.' : `${sceneLabel}: ${sceneSub}`)}>
          <FlowIcon>⌘</FlowIcon><span>{sceneLabel}<small>{sceneSub}</small></span>
        </button>
        <button type="button" className="scene-card test-card scene-card-btn cockpit-float" onClick={() => onAnnounce(online ? 'Daemon connected on your device.' : 'Run flow daemon start on your linked machine.')}>
          <FlowIcon>⌁</FlowIcon><span>Local FLOW<small>{sceneActivity}</small></span>
        </button>
      </div>
      <aside className="glass-panel goal-panel">
        {unpaired && (
          <p className="connect-banner">Run <code>flow login</code> on your computer, then approve this browser.</p>
        )}
        {!unpaired && !online && (
          <p className="connect-banner">On your machine: <code>flow daemon start</code></p>
        )}
        <div className="eyebrow-row">
          <span>Current Goal</span>
          <button type="button" disabled={!online} onClick={() => { setEditingGoal((v) => !v); onAnnounce(editingGoal ? 'Goal editor closed.' : 'Edit your goal — saved locally until flow start syncs.'); }}>
            <FlowIcon>✎</FlowIcon> Edit
          </button>
        </div>
        {editingGoal ? (
          <label className="goal-field">
            <span className="sr-only">Session goal</span>
            <input
              value={goalDraft}
              onChange={(e) => setGoalDraft(e.target.value)}
              placeholder="What are you working on?"
              onKeyDown={(e) => { if (e.key === 'Enter') { setEditingGoal(false); onAnnounce('Goal draft saved locally.'); } }}
            />
          </label>
        ) : (
          <h2>{goalDraft.trim() ? goalDraft : online ? <>Waiting for your<br />next session goal</> : <>Set a goal with<br /><code>flow start</code></>}</h2>
        )}
        <p className="session-started"><i aria-hidden="true" />{online ? (paused ? 'Paused' : stopped ? 'Stopped' : 'No active session') : unpaired ? 'Not linked' : 'Device linked'}</p>
        <div className="metric-stack">
          {METRIC_DEFS.map((m, i) => (
            <MetricRing
              key={m.label}
              label={m.label}
              value="—"
              status={online ? 'Live when session runs' : i === 0 ? 'Tap to learn more' : '—'}
              color={m.color}
              blurb={m.blurb}
              active={metricFocus === i}
              onToggle={() => { setMetricFocus(metricFocus === i ? null : i); onAnnounce(`${m.label}: ${m.blurb}`); }}
            />
          ))}
        </div>
        <div className="goal-actions">
          <button type="button" className="secondary-action" onClick={copyStart}>Copy flow start</button>
          {onGoAgent && online && (
            <button type="button" className="secondary-action" onClick={() => { onGoAgent(); onAnnounce('Opened Agent tab.'); }}>Ask FLOW</button>
          )}
        </div>
        <blockquote>“Consistent steps<br />create extraordinary results.”<small>— FLOW</small></blockquote>
      </aside>

      <section className="glass-panel session-head-panel" aria-label="Session focus">
        <div className="stage-title">
          <small>{unpaired ? 'Setup' : `Stage ${stageIndex + 1} of ${WORKSPACE_STAGES.length}`}</small>
          <h1>{title}</h1>
          <p>{detail}</p>
        </div>
        {!unpaired && (
          <ol className="stage-rail stage-rail-compact" aria-label="Session stages">
            {WORKSPACE_STAGES.map((item, index) => (
              <li key={item.label} className={index === stageIndex ? 'is-current' : index < stageIndex ? 'is-complete' : ''}>
                <button type="button" onClick={() => selectStage(index)} aria-current={index === stageIndex ? 'step' : undefined} aria-label={`${item.label} stage`}>
                  <span>{index < stageIndex ? '✓' : item.symbol}</span>
                  <small>{item.label}</small>
                </button>
              </li>
            ))}
          </ol>
        )}
      </section>

      <aside className="glass-panel insight-panel">
        <header><span><FlowIcon>☼</FlowIcon> AI Insight</span><b>{online ? 'Listening' : 'Standby'}</b></header>
        <p>
          {unpaired && 'Pair your device to receive live insights from local sessions.'}
          {!unpaired && !online && 'Your device is still linked. Start the daemon locally — this panel fills in when a session is running.'}
          {online && `At the ${stage.label} stage, FLOW waits for observations from flow start on ${device?.name ?? 'your device'}.`}
        </p>
        {!unpaired && (
          <>
            <div className="panel-divider" />
            <div className="insight-actions">
              <button type="button" className="primary-action" disabled={!online} onClick={() => onAnnounce('When a session runs, recommended actions appear here.')}>▶ Next action</button>
              <button type="button" className="secondary-action" onClick={onDocs}>Docs</button>
              {onGoAgent && (
                <button type="button" className="secondary-action" disabled={!online} onClick={() => { onGoAgent(); onAnnounce('Delegate from Agent tab.'); }}>Delegate</button>
              )}
            </div>
          </>
        )}
        {unpaired && <button type="button" className="primary-action" onClick={onDocs}>Setup in Docs</button>}
      </aside>

      <InteractiveTimeline live={online} onSelect={onAnnounce} />

      <section className="glass-panel activity-panel" aria-label="Live activity">
        <header>
          <strong><i aria-hidden="true" />Live Activity</strong>
          <button type="button" onClick={() => onAnnounce('Full activity history stays on your device.')}>View all</button>
        </header>
        {ACTIVITY_STUBS.map((row, index) => (
          <div key={row.label}>
            <button
              type="button"
              className="activity-row activity-row-btn"
              aria-expanded={activityOpen === index}
              onClick={() => { setActivityOpen(activityOpen === index ? null : index); onAnnounce(row.label); }}
            >
              <FlowIcon>{row.icon}</FlowIcon><span>{row.label}</span><time>{online ? 'Live soon' : 'Preview'}</time>
            </button>
            {activityOpen === index && <p className="activity-detail">{row.detail}</p>}
          </div>
        ))}
      </section>
    </section>
  );
}
