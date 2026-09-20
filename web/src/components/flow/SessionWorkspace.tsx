import { useCallback, useState } from 'react';
import type { FlowDevice } from '../../lib/account';
import { pairingState, type PresenceState } from '../../lib/flowDeviceModel';
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
      <b>{value === '—' ? '—' : value}</b>
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
  const sessionActive = online && !stopped && !paused;
  const [stageIndex, setStageIndex] = useState(0);
  const [goalDraft, setGoalDraft] = useState('');
  const [editingGoal, setEditingGoal] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);

  const stage = WORKSPACE_STAGES[stageIndex]!;

  const selectStage = useCallback((index: number) => {
    setStageIndex(index);
    onAnnounce(`${WORKSPACE_STAGES[index]!.label} stage selected.`);
  }, [onAnnounce]);

  const goalText = goalDraft.trim()
    ? goalDraft
    : unpaired
      ? 'Link your device to start a session'
      : online
        ? 'Set a goal with flow start on your device'
        : 'Start the daemon, then flow start "your goal"';

  const stageLine = unpaired
    ? 'Setup'
    : stopped
      ? 'Stopped'
      : paused
        ? 'Paused'
        : `Stage ${stageIndex + 1} of ${WORKSPACE_STAGES.length} · ${stage.label}`;

  const sessionMeta = sessionActive ? 'Session active on device' : online ? 'Linked · no active session' : unpaired ? 'Not linked' : 'Device linked · offline';

  const currentActivity = unpaired
    ? 'Waiting to link'
    : !online
      ? 'Daemon offline'
      : stopped
        ? 'Session stopped'
        : paused
          ? 'Session paused'
          : sessionActive
            ? stage.activity
            : 'No active session';

  const insightTitle = online && !unpaired ? 'FLOW Insight' : 'FLOW Insight';
  const insightBadge = sessionActive ? 'Listening' : 'Standby';
  const insightBody = unpaired
    ? 'Pair your device in Docs to receive recommendations during local sessions.'
    : !online
      ? 'Your device stays linked. Run flow daemon start locally — insights appear when a session runs.'
      : sessionActive
        ? 'When FLOW observes aligned work, the next recommended action appears here.'
        : 'Start flow start on your device. This panel highlights one next action at a time.';

  return (
    <>
      <section className="session-workspace session-workspace-v2 cockpit-overlay" aria-label="Session workspace">
        <header className="session-goal-bar glass-panel level-2">
          <div className="session-goal-main">
            <span className="session-goal-eyebrow">Goal</span>
            {editingGoal ? (
              <label className="goal-field goal-field-inline">
                <span className="sr-only">Session goal</span>
                <input
                  value={goalDraft}
                  onChange={(e) => setGoalDraft(e.target.value)}
                  placeholder="What are you working on?"
                  onKeyDown={(e) => { if (e.key === 'Enter') { setEditingGoal(false); onAnnounce('Goal draft saved locally.'); } }}
                />
              </label>
            ) : (
              <h2>{goalText}</h2>
            )}
            <p className="session-goal-meta">{stageLine} · {sessionMeta}</p>
          </div>
          <button
            type="button"
            className="goal-edit-btn"
            disabled={!online}
            onClick={() => { setEditingGoal((v) => !v); onAnnounce(editingGoal ? 'Goal editor closed.' : 'Edit goal locally until flow start syncs.'); }}
          >
            <FlowIcon>✎</FlowIcon> Edit
          </button>
        </header>

        {(unpaired || (!online && !unpaired)) && (
          <SetupStrip
            variant={unpaired ? 'unpaired' : 'offline'}
            onDocs={onDocs}
            onCopied={onAnnounce}
          />
        )}

        <div className="session-main-grid">
          <aside className="glass-panel live-state-panel level-2" aria-label="Live state">
            <h3>Live state</h3>
            <div className="live-activity-line">
              <span className="live-activity-label">Current activity</span>
              <strong>{currentActivity}</strong>
            </div>
            <MetricBar label="Goal alignment" value="—" />
            <MetricBar label="Focus" value="—" />
            <MetricBar label="Progress" value="—" />
            <div className="live-meta-row"><span>Blocker</span><b>{unpaired ? 'Not linked' : online ? 'None' : 'Daemon offline'}</b></div>
            <div className="live-meta-row"><span>Focus block</span><b>{sessionActive ? '—' : '—'}</b></div>
            {unpaired && (
              <button type="button" className="secondary-action compact-action" onClick={onDocs}>Open Docs</button>
            )}
          </aside>

          <div className="session-stage-spine" aria-label="Workspace scene">
            {!unpaired && (
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
            )}
            <div className="cockpit-float-layer" aria-hidden={unpaired}>
              {!unpaired && (
                <>
                  <button type="button" className="scene-card editor-card scene-card-btn cockpit-float" onClick={() => onAnnounce(`${device?.name ?? 'Workspace'} · active app on device`)}>
                    <FlowIcon>⌘</FlowIcon><span>VS Code<small>{sessionActive ? 'auth/token.py' : 'When session runs'}</small></span>
                  </button>
                  <button type="button" className="scene-card test-card scene-card-btn cockpit-float" onClick={() => onAnnounce(sessionActive ? 'Test status from device' : 'Tests appear during active sessions')}>
                    <FlowIcon>⚠</FlowIcon><span>Tests<small>{sessionActive ? 'Live on device' : '—'}</small></span>
                  </button>
                </>
              )}
            </div>
          </div>

          <aside className="glass-panel insight-panel level-2" aria-label="Next action">
            <header><span><FlowIcon>☼</FlowIcon> {insightTitle}</span><b>{insightBadge}</b></header>
            <p>{insightBody}</p>
            {sessionActive && (
              <p className="insight-placeholder">Next recommended action appears here when FLOW has enough evidence from your session.</p>
            )}
            {!unpaired && !sessionActive && (
              <button type="button" className="secondary-action compact-action" onClick={onDocs}>Setup in Docs</button>
            )}
            {onGoAgent && online && (
              <button type="button" className="secondary-action compact-action" onClick={() => { onGoAgent(); onAnnounce('Opened Agent.'); }}>Delegate to Agent</button>
            )}
          </aside>
        </div>

        <InteractiveTimeline
          live={sessionActive}
          preview={false}
          compact
          onSelect={onAnnounce}
          onOpenActivity={() => setActivityOpen(true)}
        />
      </section>

      <FlowDrawer open={activityOpen} title="Activity" onClose={() => setActivityOpen(false)}>
        <SessionActivityDrawerContent
          rows={sessionActive ? [] : []}
          empty={sessionActive ? 'Live activity rows stream from your device during sessions.' : 'No active session — activity appears when flow start is running.'}
        />
      </FlowDrawer>
    </>
  );
}
