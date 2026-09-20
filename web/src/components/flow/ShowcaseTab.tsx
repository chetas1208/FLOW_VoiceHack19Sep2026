import { useState, type CSSProperties, type FormEvent } from 'react';
import { InteractiveTimeline } from './InteractiveTimeline';
import { SessionControls } from './SessionControls';
import { FlowIcon } from './FlowIcon';

type PreviewView = 'session' | 'agent';
type ApprovalState = 'pending' | 'approved' | 'denied';

type Stage = {
  label: string;
  detail: string;
  symbol: string;
  insight: string;
  activity: string;
};

const STAGES: readonly Stage[] = [
  { label: 'Understand', detail: 'Reading the goal and project context', symbol: '⌕', insight: 'FLOW is mapping the authentication goal into a small, verifiable sequence.', activity: 'Mapped project context' },
  { label: 'Plan', detail: 'Breaking the work into focused steps', symbol: '▤', insight: 'The plan keeps the next change small and leaves a clear verification point.', activity: 'Created an implementation plan' },
  { label: 'Implement', detail: 'Writing code and making changes', symbol: '</>', insight: 'The targeted expiry test now passes, but your goal requires all tests to pass.', activity: 'Editing token.py' },
  { label: 'Validate', detail: 'Running tests and checking evidence', symbol: '☑', insight: 'Validation is the next confidence jump: run the full authentication test suite.', activity: 'Ran pytest tests/auth' },
  { label: 'Complete', detail: 'Goal completed with evidence', symbol: '⚑', insight: 'The goal is ready to close once the final evidence has been reviewed.', activity: 'Collected final evidence' },
];

const SAMPLE_METRICS = [
  { label: 'Goal alignment', value: 91 },
  { label: 'Focus', value: 84 },
  { label: 'Progress', value: 72 },
] as const;

const ACTIVITIES = [
  { icon: '⌘', label: 'VS Code', detail: 'Editing token.py', time: '18:36' },
  { icon: '⌁', label: 'Terminal', detail: 'Ran pytest tests/auth', time: '18:34' },
  { icon: '▤', label: 'Git', detail: 'Modified services/auth/', time: '18:31' },
] as const;

const TASKS = [
  { title: 'Diagnose auth failures', detail: '2m 13s', kind: 'running' as const },
  { title: 'Run full test suite', detail: 'Queued', kind: 'queued' as const },
  { title: 'Dependency audit', detail: 'Completed', kind: 'done' as const },
];

export function ShowcaseTab({ onAnnounce, onViewChange }: { onAnnounce: (message: string) => void; onViewChange?: (view: PreviewView) => void }) {
  const [view, setView] = useState<PreviewView>('session');
  const pickView = (next: PreviewView) => { setView(next); onViewChange?.(next); };
  const [stageIndex, setStageIndex] = useState(2);
  const [paused, setPaused] = useState(false);
  const [muted, setMuted] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const stage = STAGES[stageIndex]!;

  return (
    <div className="showcase-root" aria-label="Interactive product preview">
      <p className="showcase-banner">Sample data for exploration — Session and Agent tabs show your real device.</p>
      <div className="showcase-switch" role="tablist" aria-label="Preview view">
        <button type="button" role="tab" aria-selected={view === 'session'} className={view === 'session' ? 'is-active' : ''} onClick={() => pickView('session')}>Session story</button>
        <button type="button" role="tab" aria-selected={view === 'agent'} className={view === 'agent' ? 'is-active' : ''} onClick={() => pickView('agent')}>Agent story</button>
      </div>
      <div className="showcase-body">
        {view === 'session' ? (
          <>
            <SessionStory
              stage={stage}
              stageIndex={stageIndex}
              stopped={stopped}
              onSelectStage={(i) => { setStopped(false); setStageIndex(i); onAnnounce(`${STAGES[i]!.label} stage.`); }}
              onAnnounce={onAnnounce}
              onOpenActivity={() => setActivityOpen(true)}
            />
            <SessionControls
              paused={paused}
              muted={muted}
              stopped={stopped}
              onPause={() => { setPaused((v) => !v); setStopped(false); onAnnounce(paused ? 'Resumed.' : 'Paused.'); }}
              onMute={() => { setMuted((v) => !v); onAnnounce(muted ? 'Unmuted.' : 'Muted.'); }}
              onAsk={() => { pickView('agent'); onAnnounce('Ask FLOW.'); }}
              onDelegate={() => { pickView('agent'); onAnnounce('Delegate.'); }}
              onStop={() => { setStopped(true); setPaused(true); onAnnounce('Stopped.'); }}
            />
          </>
        ) : (
          <AgentStory stage={stage} onAnnounce={onAnnounce} />
        )}
      </div>
      {activityOpen && view === 'session' && (
        <div className="showcase-activity-inline glass-panel level-2">
          <header><strong>Activity</strong><button type="button" onClick={() => setActivityOpen(false)}>Close</button></header>
          <ul className="activity-drawer-list">
            {ACTIVITIES.map((a) => (
              <li key={a.time}><time>{a.time}</time><FlowIcon>{a.icon}</FlowIcon><span><strong>{a.label}</strong><small>{a.detail}</small></span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SessionStory({
  stage,
  stageIndex,
  stopped,
  onSelectStage,
  onAnnounce,
  onOpenActivity,
}: {
  stage: Stage;
  stageIndex: number;
  stopped: boolean;
  onSelectStage: (i: number) => void;
  onAnnounce: (m: string) => void;
  onOpenActivity: () => void;
}) {
  const [accepted, setAccepted] = useState(false);
  const title = stopped ? 'Session stopped' : stage.label;

  return (
    <section className="session-workspace session-workspace-v2 session-workspace-demo cockpit-overlay" aria-label="Session preview">
      <header className="session-goal-bar glass-panel level-2">
        <div className="session-goal-main">
          <span className="session-goal-eyebrow">Goal</span>
          <h2>Finish authentication and get all tests passing</h2>
          <p className="session-goal-meta">Stage {stageIndex + 1} of {STAGES.length} · {title} · 42m</p>
        </div>
        <button type="button" className="goal-edit-btn"><FlowIcon>✎</FlowIcon> Edit</button>
      </header>

      <div className="session-main-grid">
        <aside className="glass-panel live-state-panel level-2">
          <h3>Live state</h3>
          <div className="live-activity-line">
            <span className="live-activity-label">Current activity</span>
            <strong>{stopped ? 'Paused' : stage.activity}</strong>
          </div>
          {SAMPLE_METRICS.map((m) => (
            <div className="metric-bar" key={m.label}>
              <span className="metric-bar-label">{m.label}</span>
              <span className="metric-bar-track"><i style={{ width: `${m.value}%` } as CSSProperties} /></span>
              <b>{m.value}</b>
            </div>
          ))}
          <div className="live-meta-row"><span>Focus block</span><b>12m 41s</b></div>
        </aside>

        <div className="session-stage-spine">
          <nav className="stage-rail-inline" aria-label="Stages">
            {STAGES.map((item, index) => (
              <button
                key={item.label}
                type="button"
                className={index === stageIndex ? 'is-current' : index < stageIndex ? 'is-complete' : ''}
                onClick={() => onSelectStage(index)}
              >
                <span>{index + 1}</span> {item.label}
              </button>
            ))}
          </nav>
          <div className="cockpit-float-layer">
            <button type="button" className="scene-card editor-card scene-card-btn cockpit-float" onClick={() => onAnnounce('VS Code · token.py')}>
              <FlowIcon>⌘</FlowIcon><span>VS Code<small>auth/token.py</small></span>
            </button>
            <button type="button" className="scene-card test-card scene-card-btn cockpit-float" onClick={() => onAnnounce('3 failing tests')}>
              <FlowIcon>⚠</FlowIcon><span>Tests<small>3 failing</small></span>
            </button>
          </div>
        </div>

        <aside className="glass-panel insight-panel level-2 is-primary-card">
          <header><span><FlowIcon>☼</FlowIcon> FLOW Insight</span><b>High confidence</b></header>
          <p>{stage.insight}</p>
          <ul className="evidence-list compact-evidence">
            <li className="confirmed">Expiry test passed</li>
            <li className="confirmed">Implementation changed</li>
            <li>Full auth suite not run</li>
          </ul>
          <p className="next-action-title">Run the full authentication test suite</p>
          <button type="button" className="primary-action" onClick={() => { setAccepted(true); onAnnounce('Queued full suite.'); }}>{accepted ? '✓ Queued' : 'Do it'}</button>
        </aside>
      </div>

      <InteractiveTimeline live preview compact onSelect={onAnnounce} onOpenActivity={onOpenActivity} />
    </section>
  );
}

function AgentStory({ stage, onAnnounce }: { stage: Stage; onAnnounce: (m: string) => void }) {
  const [contextTab, setContextTab] = useState<'plan' | 'tools' | 'approvals'>('plan');
  const [approval, setApproval] = useState<ApprovalState>('pending');
  const [prompt, setPrompt] = useState('');

  return (
    <section className="agent-workspace agent-workspace-v2 agent-workspace-demo cockpit-overlay" aria-label="Agent preview">
      <header className="agent-band glass-panel level-2">
        <div>
          <span className="agent-band-eyebrow">Agent</span>
          <h1>Your AI pair programmer and productivity partner</h1>
        </div>
        <span className="agent-phase-pill phase-executing"><i aria-hidden="true" />Executing</span>
      </header>

      <div className="agent-main-grid">
        <aside className="glass-panel task-queue-panel level-2">
          <header><h2>Task queue</h2><button type="button" onClick={() => onAnnounce('New task')}>＋ New</button></header>
          <div className="task-queue-section"><h3>Running</h3>
            <button type="button" className="task-card is-selected running" onClick={() => onAnnounce('Diagnose selected')}>
              <i>◔</i><span>{TASKS[0]!.title}<small>{TASKS[0]!.detail}</small></span><b>50%</b>
            </button>
          </div>
          <div className="task-queue-section"><h3>Queued</h3>
            <button type="button" className="task-card queued"><i>◌</i><span>{TASKS[1]!.title}<small>{TASKS[1]!.detail}</small></span><b>›</b></button>
          </div>
          <div className="task-queue-section"><h3>Completed</h3>
            <button type="button" className="task-card done"><i>✓</i><span>{TASKS[2]!.title}<small>{TASKS[2]!.detail}</small></span><b>✓</b></button>
          </div>
        </aside>

        <div className="agent-core-spine">
          <div className="cockpit-float-layer agent-float-layer">
            <div className="agent-float-card agent-analysis cockpit-float">
              <strong><FlowIcon>✦</FlowIcon> Analyzing</strong>
              <span>✓ Reading test output</span><span>✓ Inspecting code</span><span>○ Identifying root cause</span>
            </div>
          </div>
        </div>

        <aside className="glass-panel active-task-panel level-2">
          <h2>Current task</h2>
          <p className="next-action-title">Diagnose failing authentication test</p>
          <p className="active-task-meta">Step 2 of 5 · Running pytest tests/auth</p>
          <p className="active-task-meta">Elapsed 01:42 · 3 failures found</p>
          <button type="button" className="secondary-action compact-action" onClick={() => onAnnounce('Cancel task')}>Cancel task</button>
        </aside>
      </div>

      <div className="agent-context-bar glass-panel level-2">
        <div className="segmented-control">
          {(['plan', 'tools', 'approvals'] as const).map((id) => (
            <button key={id} type="button" className={contextTab === id ? 'is-active' : ''} onClick={() => setContextTab(id)}>
              {id === 'plan' ? 'Plan' : id === 'tools' ? 'Tools' : 'Approvals'}
              {id === 'approvals' && approval === 'pending' && <b>1</b>}
            </button>
          ))}
        </div>
        <div className="agent-context-body">
          {contextTab === 'plan' && <p className="panel-empty">Inspect failure → confirm timestamp contract → patch → run full suite.</p>}
          {contextTab === 'tools' && <p className="panel-empty">Read File, Search Code, Run Tests — sample tools available in live Agent tab.</p>}
          {contextTab === 'approvals' && approval === 'pending' && (
            <div className="approval-interrupt is-primary-card glass-panel">
              <h3>Approval required</h3>
              <p>Modify <code>services/auth/token.py</code> — UTC timestamp mismatch.</p>
              <div className="approval-actions">
                <button type="button" className="primary-action" onClick={() => { setApproval('approved'); onAnnounce('Approved.'); }}>Approve</button>
                <button type="button" className="secondary-action" onClick={() => { setApproval('denied'); onAnnounce('Denied.'); }}>Deny</button>
              </div>
            </div>
          )}
        </div>
      </div>

      <form className="agent-composer agent-composer-bar glass-panel level-2" onSubmit={(e: FormEvent) => { e.preventDefault(); onAnnounce(`FLOW: ${prompt}`); setPrompt(''); }}>
        <input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ask FLOW about this session…" />
        <button type="submit"><FlowIcon>➤</FlowIcon> Send</button>
      </form>
      <p className="showcase-sample-note">Sample agent narrative · {stage.label} stage context</p>
    </section>
  );
}
