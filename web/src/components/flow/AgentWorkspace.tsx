import { useState, type FormEvent } from 'react';
import type { FlowDevice } from '../../lib/account';
import { daemonStatus, modelStatus, pairingState, presenceLabel, type PresenceState } from '../../lib/flowDeviceModel';
import { FlowIcon } from './FlowIcon';

const TOOLS = [
  ['▤', 'Read File'],
  ['⌕', 'Search Code'],
  ['▶', 'Run Tests'],
  ['⌁', 'Run Command'],
  ['⌘', 'Git Status'],
  ['↗', 'Apply Patch'],
] as const;

const PROMPT_CHIPS = ['Check daemon status', 'Show me the plan', 'Run tests locally', 'Explain presence', 'Open Docs'];

const TASKS = [
  { id: 'start', title: 'Start a session', detail: 'flow start "goal"', kind: 'queued' as const },
  { id: 'linked', title: 'Device linked', detail: 'Pairing persists across offline periods', kind: 'done' as const },
  { id: 'daemon', title: 'Ensure daemon is running', detail: 'flow daemon start', kind: 'queued' as const },
];

function StatusRow({ icon, label, value }: { icon: string; label: string; value: string }) {
  return <p className="status-row"><FlowIcon>{icon}</FlowIcon><span>{label}</span><b>{value}</b></p>;
}

export function AgentWorkspace({
  device,
  pairing,
  presence,
  onDocs,
  onAnnounce,
}: {
  device: FlowDevice | null;
  pairing: ReturnType<typeof pairingState>;
  presence: PresenceState;
  onDocs: () => void;
  onAnnounce: (message: string) => void;
}) {
  const health = device?.presence.health ?? {};
  const unpaired = pairing === 'unpaired' || pairing === 'revoked';
  const online = pairing === 'paired' && presence === 'online';
  const [prompt, setPrompt] = useState('');
  const [selectedTask, setSelectedTask] = useState('linked');
  const [detail, setDetail] = useState('');
  const [showNewTask, setShowNewTask] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');

  const visibleTasks = unpaired ? [] : TASKS;

  const agentLine = unpaired
    ? 'Connect a device with flow login to run the local agent.'
    : !online
      ? `${device?.name ?? 'Your device'} is still linked. Start the daemon to resume agent work.`
      : selectedTask === 'start'
        ? 'When you run flow start, delegated tasks queue here and execute on your machine.'
        : selectedTask === 'daemon'
          ? 'Run flow daemon start locally — the browser reconnects automatically.'
          : 'Device pairing is active. Delegate work from a session or ask FLOW below.';

  const submitPrompt = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!prompt.trim()) return;
    onAnnounce(`FLOW received: ${prompt.trim()}`);
    setPrompt('');
  };

  const addTask = () => {
    if (!newTaskTitle.trim()) return;
    onAnnounce(`Task drafted: ${newTaskTitle.trim()} — syncs when agent API is wired.`);
    setNewTaskTitle('');
    setShowNewTask(false);
  };

  return (
    <section className="agent-workspace cockpit-overlay" aria-label="Agent workspace">
      <div className="cockpit-float-layer agent-float-layer" aria-hidden="true">
        <button type="button" className="agent-float-card agent-analysis agent-float-btn cockpit-float" onClick={() => onAnnounce('Agent runs on your linked device — nothing executes in the cloud.')}>
          <strong><FlowIcon>✦</FlowIcon> FLOW agent</strong>
          <span>{online ? '✓ Ready on device' : '○ Standby'}</span>
        </button>
      </div>
      <aside className="glass-panel task-panel">
        <header>
          <h1>Agent Tasks</h1>
          <button type="button" disabled={unpaired} onClick={() => { setShowNewTask((v) => !v); onAnnounce(showNewTask ? 'Task form closed.' : 'Describe a task to queue locally.'); }}>＋ New Task</button>
        </header>
        {unpaired ? (
          <p className="connect-banner" style={{ marginTop: 12 }}>Link a device to queue local tasks. <button type="button" className="secondary-action" style={{ marginTop: 8 }} onClick={onDocs}>Docs</button></p>
        ) : (
          <>
            {showNewTask && (
              <div className="new-task-form">
                <input value={newTaskTitle} onChange={(e) => setNewTaskTitle(e.target.value)} placeholder="Task title…" onKeyDown={(e) => e.key === 'Enter' && addTask()} />
                <button type="button" className="primary-action" onClick={addTask}>Add</button>
              </div>
            )}
            <div className="task-list" style={{ marginTop: 16 }}>
              {visibleTasks.map((task) => (
                <button
                  type="button"
                  key={task.id}
                  className={`task-card ${selectedTask === task.id ? 'is-selected' : ''} ${task.kind}`}
                  onClick={() => { setSelectedTask(task.id); onAnnounce(`${task.title} selected.`); }}
                >
                  <i aria-hidden="true">{task.kind === 'done' ? '✓' : '◌'}</i>
                  <span>{task.title}<small>{task.detail}</small></span>
                  <b>{task.kind === 'done' ? '✓' : '›'}</b>
                </button>
              ))}
            </div>
          </>
        )}
        <blockquote>“Delegate the routine.<br />Focus on what matters.”<small>— FLOW</small></blockquote>
      </aside>

      <section className="agent-center agent-center-overlay">
        <div className="glass-panel agent-title-card">
          <h1>Your AI pair programmer and productivity partner</h1>
          <p>Understand. Plan. Execute. Verify. Together.</p>
        </div>
        <section className="agent-response glass-panel">
          <header><strong><FlowIcon>✦</FlowIcon> FLOW</strong><time>{new Date().toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</time></header>
          <p>{agentLine}</p>
          {(['Status', 'Tools', 'Privacy'] as const).map((label) => (
            <div key={label}>
              <button type="button" aria-expanded={detail === label} onClick={() => setDetail(detail === label ? '' : label)}>
                <FlowIcon>{label === 'Status' ? '▤' : label === 'Tools' ? '⌁' : '◉'}</FlowIcon>
                {label}
                <small>Tap to expand</small>
                <b>›</b>
              </button>
              {detail === label && (
                <p className="detail-copy">
                  {label === 'Status' && `Model: ${modelStatus(health.model)} · Daemon: ${daemonStatus(health.daemon, presence)} · ${presenceLabel(presence)}`}
                  {label === 'Tools' && 'Six safe-execute tools unlock when the daemon is online and a session is active.'}
                  {label === 'Privacy' && 'Prompts and results stay on your machine; this UI only reflects metadata.'}
                </p>
              )}
            </div>
          ))}
        </section>
        <form className="agent-composer glass-panel" onSubmit={submitPrompt}>
          <label className="sr-only" htmlFor="flow-agent-prompt">Ask FLOW anything</label>
          <input id="flow-agent-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ask FLOW anything..." disabled={unpaired} />
          <button type="submit" aria-label="Send prompt" disabled={unpaired}><FlowIcon>➤</FlowIcon></button>
          <div>{PROMPT_CHIPS.map((value) => (
            <button
              key={value}
              type="button"
              disabled={unpaired}
              onClick={() => {
                if (value === 'Open Docs') { onDocs(); onAnnounce('Opened Docs.'); return; }
                setPrompt(value);
              }}
            >
              {value}
            </button>
          ))}</div>
        </form>
      </section>

      <aside className="agent-sidebar">
        <section className="glass-panel agent-status">
          <header><h2>Agent Status</h2><span><i />{online ? 'Ready' : 'Standby'}</span></header>
          <StatusRow icon="▤" label="Model" value={modelStatus(health.model)} />
          <StatusRow icon="⌘" label="Daemon" value={daemonStatus(health.daemon, presence)} />
          <StatusRow icon="▱" label="Device" value={device?.name ?? 'Not linked'} />
          <StatusRow icon="♢" label="Presence" value={presenceLabel(presence)} />
        </section>
        <section className="glass-panel tools-panel">
          <header><h2>Available Tools</h2><button type="button" disabled={!online} onClick={() => onAnnounce('Tools execute locally after approval.')}>View all</button></header>
          <div>{TOOLS.map(([icon, label]) => (
            <button type="button" key={label} disabled={!online} onClick={() => onAnnounce(`${label} — runs on your device when delegated.`)}><FlowIcon>{icon}</FlowIcon>{label}</button>
          ))}</div>
        </section>
        <section className="glass-panel approval-panel">
          <header><h2>Pending Approval <b>0</b></h2><button type="button" disabled={!online} onClick={() => onAnnounce('No pending file changes.')}>Review all</button></header>
          <p className="panel-empty">Approvals for file changes appear here during agent work.</p>
        </section>
        <section className="glass-panel recent-panel">
          <header><h2>Recent Activity</h2><button type="button" onClick={() => onAnnounce('Activity is read from your device history.')}>View all</button></header>
          <button type="button" className="activity-row activity-row-btn" onClick={() => onAnnounce('Device linked — pairing OK.')}>
            <FlowIcon>⌘</FlowIcon><span>Device linked</span><time>Now</time>
          </button>
        </section>
      </aside>
    </section>
  );
}
