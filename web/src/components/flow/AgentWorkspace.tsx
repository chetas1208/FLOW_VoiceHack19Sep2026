import { useEffect, useState, type FormEvent } from 'react';
import type { FlowDevice } from '../../lib/account';
import { modelStatus, pairingState, type PresenceState } from '../../lib/flowDeviceModel';
import { FlowIcon } from './FlowIcon';

const TOOLS = [
  ['▤', 'Read File'],
  ['⌕', 'Search Code'],
  ['▶', 'Run Tests'],
  ['⌁', 'Run Command'],
  ['⌘', 'Git Status'],
  ['↗', 'Apply Patch'],
] as const;

const PROMPT_PLACEHOLDERS = [
  'What should I do next?',
  'Why is this task blocked?',
  'What did the agent change?',
  'Are we done?',
];

type AgentPhase = 'thinking' | 'planning' | 'executing' | 'approval' | 'verifying' | 'done' | 'standby';

function phaseLabel(phase: AgentPhase): string {
  switch (phase) {
    case 'thinking': return 'Thinking';
    case 'planning': return 'Planning';
    case 'executing': return 'Executing';
    case 'approval': return 'Waiting for approval';
    case 'verifying': return 'Verifying';
    case 'done': return 'Done';
    default: return 'Standby';
  }
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
  const unpaired = pairing === 'unpaired' || pairing === 'revoked';
  const online = pairing === 'paired' && presence === 'online';
  const [prompt, setPrompt] = useState('');
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setPlaceholderIndex((i) => (i + 1) % PROMPT_PLACEHOLDERS.length), 4500);
    return () => window.clearInterval(id);
  }, []);
  const [showNewTask, setShowNewTask] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [contextTab, setContextTab] = useState<'plan' | 'tools' | 'approvals'>('plan');
  const [pendingApproval] = useState(0);

  const phase: AgentPhase = unpaired ? 'standby' : online ? 'standby' : 'standby';
  const health = device?.presence.health ?? {};

  const submitPrompt = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!prompt.trim()) return;
    onAnnounce(`FLOW received: ${prompt.trim()}`);
    setPrompt('');
  };

  const addTask = () => {
    if (!newTaskTitle.trim()) return;
    onAnnounce(`Task drafted: ${newTaskTitle.trim()} — queues on your device when agent API is connected.`);
    setNewTaskTitle('');
    setShowNewTask(false);
  };

  return (
    <section className="agent-workspace agent-workspace-v2 cockpit-overlay" aria-label="Agent workspace">
      <header className="agent-band glass-panel level-2">
        <div>
          <span className="agent-band-eyebrow">Agent</span>
          <h1>Your AI pair programmer and productivity partner</h1>
        </div>
        <span className={`agent-phase-pill phase-${phase}`}><i aria-hidden="true" />{phaseLabel(phase)}</span>
      </header>

      <div className="agent-main-grid">
        <aside className="glass-panel task-panel task-queue-panel level-2">
          <header>
            <h2>Task queue</h2>
            <button type="button" disabled={unpaired} onClick={() => { setShowNewTask((v) => !v); onAnnounce(showNewTask ? 'Task form closed.' : 'Describe a task to queue.'); }}>＋ New</button>
          </header>
          <div className="agent-task-filters" role="tablist" aria-label="Task filters">
            <button type="button" className="is-active" role="tab" aria-selected="true">All <b>0</b></button>
            <button type="button" role="tab" aria-selected="false">Running <b>0</b></button>
            <button type="button" role="tab" aria-selected="false">Queued <b>0</b></button>
            <button type="button" role="tab" aria-selected="false">Done <b>0</b></button>
          </div>
          {unpaired ? (
            <div className="agent-empty-state">
              <span className="agent-empty-icon">✦</span>
              <strong>Nothing queued yet</strong>
              <p>Link a device to delegate local work. <button type="button" className="text-link" onClick={onDocs}>Open Docs</button></p>
            </div>
          ) : (
            <>
              {showNewTask && (
                <div className="new-task-form">
                  <input value={newTaskTitle} onChange={(e) => setNewTaskTitle(e.target.value)} placeholder="Task title…" onKeyDown={(e) => e.key === 'Enter' && addTask()} />
                  <button type="button" className="primary-action" onClick={addTask}>Add</button>
                </div>
              )}
              <div className="task-queue-section">
                <h3>Running</h3>
                <p className="panel-empty">No running tasks</p>
              </div>
              <div className="task-queue-section">
                <h3>Queued</h3>
                <p className="panel-empty">Queue tasks from a session or Ask FLOW below.</p>
              </div>
              <div className="task-queue-section">
                <h3>Completed</h3>
                <p className="panel-empty">Completed work appears here.</p>
              </div>
            </>
          )}
        </aside>

        <div className="agent-core-spine" aria-label="Agent workspace scene">
          <div className="cockpit-float-layer agent-float-layer" aria-hidden="true">
            {!unpaired && (
              <button type="button" className="agent-float-card agent-analysis agent-float-btn cockpit-float" onClick={() => onAnnounce('Agent executes on your linked device only.')}>
                <strong><FlowIcon>✦</FlowIcon> FLOW</strong>
                <span>{online ? 'Ready on device' : 'Standby'}</span>
              </button>
            )}
          </div>
        </div>

        <aside className="glass-panel active-task-panel level-2" aria-label="Agent status and tools">
          <section className="agent-status-block">
            <header><h2>Agent status</h2><span className={`agent-status-label ${online ? 'is-online' : ''}`}><i />{online ? 'Ready' : 'Standby'}</span></header>
            <dl className="agent-status-list">
              <div><dt>Model</dt><dd>{modelStatus(health.model)}</dd></div>
              <div><dt>Tools</dt><dd>{online ? '6 available' : 'Available on device'}</dd></div>
              <div><dt>Workspace</dt><dd>{online ? device?.name ?? 'Linked machine' : 'Not linked'}</dd></div>
              <div><dt>Permissions</dt><dd>Safe Execute</dd></div>
            </dl>
          </section>
          <section className="agent-tools-block">
            <header><h3>Available tools</h3><span>View all</span></header>
            <div className="agent-tools-grid">
              {TOOLS.map(([icon, label]) => (
                <button type="button" key={label} disabled={!online} onClick={() => onAnnounce(`${label} runs locally when delegated.`)}><FlowIcon>{icon}</FlowIcon><span>{label}</span></button>
              ))}
            </div>
          </section>
          <section className="agent-approval-summary"><strong>Pending approval</strong><span>0</span><small>Changes wait for your review before execution.</small></section>
        </aside>
      </div>

      <div className="agent-context-bar glass-panel level-2">
        <div className="segmented-control" role="tablist" aria-label="Agent details">
          {(['plan', 'tools', 'approvals'] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={contextTab === id}
              className={contextTab === id ? 'is-active' : ''}
              onClick={() => setContextTab(id)}
            >
              {id === 'plan' ? 'Plan' : id === 'tools' ? 'Tools' : 'Approvals'}
              {id === 'approvals' && pendingApproval > 0 && <b>{pendingApproval}</b>}
            </button>
          ))}
        </div>
        <div className="agent-context-body">
          {contextTab === 'plan' && (
            <p className="panel-empty">Plan steps appear when an agent task is running on your device.</p>
          )}
          {contextTab === 'tools' && (
            <div className="tools-inline-grid">
              {TOOLS.map(([icon, label]) => (
                <button type="button" key={label} disabled={!online} onClick={() => onAnnounce(`${label} runs locally when delegated.`)}><FlowIcon>{icon}</FlowIcon>{label}</button>
              ))}
            </div>
          )}
          {contextTab === 'approvals' && (
            pendingApproval > 0 ? (
              <div className="approval-interrupt glass-panel is-primary-card">
                <h3>Approval required</h3>
                <p>File changes need your review on device.</p>
              </div>
            ) : (
              <p className="panel-empty">No pending approvals.</p>
            )
          )}
        </div>
      </div>

      <form className="agent-composer agent-composer-bar glass-panel level-2" onSubmit={submitPrompt}>
        <label className="sr-only" htmlFor="flow-agent-prompt">Ask FLOW</label>
        <input
          id="flow-agent-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={`Ask FLOW about this session… e.g. ${PROMPT_PLACEHOLDERS[placeholderIndex]}`}
          disabled={unpaired}
        />
        <button type="submit" aria-label="Send" disabled={unpaired}><FlowIcon>➤</FlowIcon> Send</button>
        <div className="composer-chips">
          {PROMPT_PLACEHOLDERS.map((chip) => (
            <button key={chip} type="button" disabled={unpaired} onClick={() => setPrompt(chip)}>{chip}</button>
          ))}
        </div>
      </form>
    </section>
  );
}
