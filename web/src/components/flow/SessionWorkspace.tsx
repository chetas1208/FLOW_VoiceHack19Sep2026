import { useCallback, useState } from 'react';
import type { FlowDevice } from '../../lib/account';
import { syncedSessionFromDevice } from '../../lib/deviceSessionSync';
import { daemonStatus, pairingState, type PresenceState } from '../../lib/flowDeviceModel';
import { WORKSPACE_STAGES } from './CockpitScenes';
import { FlowDrawer } from './FlowDrawer';
import { FlowIcon } from './FlowIcon';
import { InteractiveTimeline } from './InteractiveTimeline';
import { SessionActivityDrawerContent } from './SessionActivityDrawer';
import { SetupStrip } from './SetupStrip';

function MetricBar({ label, value }: { label: string; value: number | '—' }) {
  const n = value === '—' ? 0 : value;
  return (
    <div className="metric-bar">
      <span className="metric-bar-label">{label}</span>
      <span className="metric-bar-track" aria-hidden="true"><i style={{ width: `${n}%` }} /></span>
      <b>{value}</b>
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
  const unpaired = pairing === 'unpaired' || pairing === 'revoked';
  const online = pairing === 'paired' && presence === 'online';
  const synced = syncedSessionFromDevice(device, presence);
  const daemonRunning = online && device?.presence.health?.daemon === 'running';
  const sessionActive = daemonRunning && synced.live && !stopped && !paused;
  const [stageIndex, setStageIndex] = useState(0);
  const [goalDraft, setGoalDraft] = useState('');
  const [editingGoal, setEditingGoal] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);

  const stage = WORKSPACE_STAGES[stageIndex]!;
  const selectStage = useCallback((index: number) => {
    setStageIndex(index);
    onAnnounce(`${WORKSPACE_STAGES[index]!.label} stage selected.`);
  }, [onAnnounce]);

  const goalText = goalDraft.trim() || synced.goal || (unpaired
    ? 'Link your device to start a session'
    : online && daemonRunning
      ? 'Set a goal with flow start on your device'
      : 'Start the daemon, then flow start "your goal"');
  const stageLine = unpaired ? 'Setup' : stopped ? 'Stopped' : paused ? 'Paused' : `Stage ${stageIndex + 1} of ${WORKSPACE_STAGES.length} · ${stage.label}`;
  const sessionMeta = sessionActive
    ? `Session active · ${synced.status ?? 'live'}`
    : synced.live && online
      ? 'Session on device · refreshing from heartbeat'
      : online
        ? `Linked · ${daemonStatus(device?.presence.health?.daemon, presence)}`
        : unpaired ? 'Not linked' : 'Device linked · offline';
  const insightBody = unpaired
    ? 'Link your machine to let FLOW receive local session evidence and recommendations.'
    : !online
      ? 'Your device stays linked. Start the local daemon and this cockpit will reconnect.'
      : sessionActive
        ? 'FLOW is listening locally. The next recommended action appears when evidence is strong enough.'
        : 'Start a session on your device. FLOW will keep the control plane here and the work local.';

  return (
    <>
      <section className="session-workspace session-workspace-v2 cockpit-overlay" aria-label="Session workspace">
        <div className="session-main-grid">
          <aside className="glass-panel session-goal-panel level-2" aria-label="Current goal">
            <div className="goal-panel-head">
              <span className="session-goal-eyebrow">Current goal</span>
              <button
                type="button"
                className="goal-edit-btn"
                disabled={!online}
                onClick={() => { setEditingGoal((value) => !value); onAnnounce(editingGoal ? 'Goal editor closed.' : 'Edit goal locally until flow start syncs.'); }}
              >
                <FlowIcon>✎</FlowIcon> Edit
              </button>
            </div>
            {editingGoal ? (
              <label className="goal-field goal-field-inline">
                <span className="sr-only">Session goal</span>
                <input
                  value={goalDraft}
                  onChange={(event) => setGoalDraft(event.target.value)}
                  placeholder="What are you working on?"
                  onKeyDown={(event) => { if (event.key === 'Enter') { setEditingGoal(false); onAnnounce('Goal draft saved locally.'); } }}
                />
              </label>
            ) : <h2>{goalText}</h2>}
            <p className="session-goal-meta">{stageLine} · {sessionMeta}</p>
            <div className="goal-score-summary">
              <div className="score-ring score-ring-mint"><span>—</span></div>
              <div><strong>{online ? 'Session readiness' : 'Ready to begin'}</strong><small>{online ? 'Waiting for local evidence' : 'Link your machine to see live scores'}</small></div>
            </div>
            <div className="goal-metric-list">
              <MetricBar label="Goal alignment" value="—" />
              <MetricBar label="Focus" value="—" />
              <MetricBar label="Progress" value="—" />
            </div>
            <p className="goal-quote">“Consistent steps create extraordinary results.”<br /><span>— FLOW</span></p>
          </aside>

          <div className="session-stage-spine" aria-label="Workspace scene">
            {(unpaired || !online) && (
              <SetupStrip variant={unpaired ? 'unpaired' : 'offline'} onDocs={onDocs} onCopied={onAnnounce} />
            )}
            <nav className="stage-rail-inline" aria-label="Session stages">
              {WORKSPACE_STAGES.map((item, index) => (
                <button
                  key={item.label}
                  type="button"
                  className={index === stageIndex ? 'is-current' : index < stageIndex ? 'is-complete' : ''}
                  onClick={() => selectStage(index)}
                  aria-current={index === stageIndex ? 'step' : undefined}
                >
                  <span>{index + 1}</span> {item.label}
                </button>
              ))}
            </nav>
            <div className="cockpit-float-layer">
              <button type="button" className="scene-card editor-card scene-card-btn cockpit-float" onClick={() => onAnnounce(sessionActive ? `${device?.name ?? 'Workspace'} · active app on device` : 'FLOW CLI is ready to connect')}>
                <FlowIcon>{sessionActive ? '⌘' : '↗'}</FlowIcon>
                <span>{sessionActive ? 'VS Code' : 'FLOW CLI'}<small>{sessionActive ? 'auth/token.py' : 'flow login'}</small></span>
              </button>
              <button type="button" className="scene-card test-card scene-card-btn cockpit-float" onClick={() => onAnnounce(sessionActive ? 'Test status from device' : 'Local evidence appears after pairing')}>
                <FlowIcon>{sessionActive ? '⚠' : '◌'}</FlowIcon>
                <span>{sessionActive ? 'Tests' : 'Local state'}<small>{sessionActive ? 'Live on device' : 'Waiting for device'}</small></span>
              </button>
            </div>
          </div>

          <aside className="glass-panel insight-panel level-2 is-primary-card" aria-label="FLOW insight">
            <header><span><FlowIcon>☼</FlowIcon> {unpaired ? 'FLOW Setup' : 'FLOW Insight'}</span><b>{unpaired ? 'Ready' : sessionActive ? 'Listening' : 'Standby'}</b></header>
            <p>{insightBody}</p>
            <ul className="evidence-list compact-evidence">
              <li className="confirmed">Account session active</li>
              <li className={pairing === 'paired' ? 'confirmed' : ''}>{pairing === 'paired' ? 'Machine linked' : 'Machine not linked'}</li>
              <li className={online ? 'confirmed' : ''}>{online ? 'Daemon heartbeat received' : 'Local session not running'}</li>
            </ul>
            <p className="next-action-title">{unpaired ? 'Connect your machine' : online ? 'Open your agent workspace' : 'Wake your device'}</p>
            <button type="button" className="primary-action" onClick={unpaired || !online ? onDocs : onGoAgent}>
              {unpaired ? 'Open Docs' : online ? 'Open Agent' : 'View setup'}
            </button>
          </aside>
        </div>

        <InteractiveTimeline live={sessionActive} preview={false} compact onSelect={onAnnounce} onOpenActivity={() => setActivityOpen(true)} />
      </section>

      <FlowDrawer open={activityOpen} title="Activity" onClose={() => setActivityOpen(false)}>
        <SessionActivityDrawerContent
          rows={[]}
          empty={sessionActive ? 'Live activity rows stream from your device during sessions.' : 'No active session — activity appears when flow start is running on your device.'}
        />
      </FlowDrawer>
    </>
  );
}
