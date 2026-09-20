import { useState, type CSSProperties, type FormEvent } from 'react';
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
  { label: 'Session Efficiency', value: 86, status: '↗ 12%', note: 'Good Progress', color: 'mint' as const },
  { label: 'Goal Alignment', value: 91, status: 'On track', note: '', color: 'mint' as const },
  { label: 'Focus', value: 84, status: 'Strong', note: '', color: 'blue' as const },
  { label: 'Progress', value: 72, status: 'Building', note: '', color: 'gold' as const },
];

const ACTIVITIES = [
  { icon: '⌘', label: 'Editing token.py', time: '2m ago' },
  { icon: '⌁', label: 'Ran pytest tests/auth', time: '4m ago' },
  { icon: '▤', label: 'Modified services/auth/', time: '8m ago' },
] as const;

const TASKS = [
  { title: 'Diagnose failing authentication tests', detail: 'Step 3 of 6  ·  Analyzing test failure', kind: 'running' as const },
  { title: 'Run full authentication test suite', detail: 'Queued  ·  Waiting for approval', kind: 'queued' as const },
  { title: 'Check dependency updates', detail: 'Queued  ·  Scheduled next', kind: 'queued' as const },
  { title: 'Analyze project structure', detail: 'Completed  ·  12m ago', kind: 'done' as const },
];

const TOOLS = [
  ['▤', 'Read File'],
  ['⌕', 'Search Code'],
  ['▶', 'Run Tests'],
  ['⌁', 'Run Command'],
  ['⌘', 'Git Status'],
  ['↗', 'Apply Patch'],
] as const;

export function ShowcaseTab({ onAnnounce, onViewChange }: { onAnnounce: (message: string) => void; onViewChange?: (view: PreviewView) => void }) {
  const [view, setView] = useState<PreviewView>('session');
  const pickView = (next: PreviewView) => { setView(next); onViewChange?.(next); };
  const [stageIndex, setStageIndex] = useState(2);
  const [paused, setPaused] = useState(false);
  const [muted, setMuted] = useState(false);
  const [stopped, setStopped] = useState(false);
  const stage = STAGES[stageIndex]!;
  const selectStage = (index: number) => {
    setStopped(false);
    setStageIndex(index);
    onAnnounce(`${STAGES[index]!.label} stage selected.`);
  };

  return (
    <div className="showcase-root" aria-label="Interactive product preview">
      <p className="showcase-banner">Sample session and agent data for exploration. Session and Agent tabs reflect your linked device.</p>
      <div className="showcase-switch" role="tablist" aria-label="Preview view">
        <button type="button" role="tab" aria-selected={view === 'session'} className={view === 'session' ? 'is-active' : ''} onClick={() => pickView('session')}>Session preview</button>
        <button type="button" role="tab" aria-selected={view === 'agent'} className={view === 'agent' ? 'is-active' : ''} onClick={() => pickView('agent')}>Agent preview</button>
      </div>
      <div className="showcase-body">
        {view === 'session' ? (
          <>
            <SessionPreview
              stage={stage}
              stageIndex={stageIndex}
              stopped={stopped}
              onSelectStage={selectStage}
              onAnnounce={onAnnounce}
            />
            <SessionControls
              paused={paused}
              muted={muted}
              stopped={stopped}
              onPause={() => { setPaused((v) => !v); setStopped(false); onAnnounce(paused ? 'Session resumed.' : 'Session paused.'); }}
              onMute={() => { setMuted((v) => !v); onAnnounce(muted ? 'FLOW audio unmuted.' : 'FLOW audio muted.'); }}
              onAsk={() => { pickView('agent'); onAnnounce('FLOW is ready for your direction.'); }}
              onDelegate={() => { pickView('agent'); onAnnounce('Delegation workspace opened.'); }}
              onStop={() => { setStopped(true); setPaused(true); onAnnounce('Session stopped.'); }}
            />
          </>
        ) : (
          <AgentPreview stage={stage} onAnnounce={onAnnounce} />
        )}
      </div>
    </div>
  );
}

function SessionPreview({
  stage,
  stageIndex,
  stopped,
  onSelectStage,
  onAnnounce,
}: {
  stage: Stage;
  stageIndex: number;
  stopped: boolean;
  onSelectStage: (index: number) => void;
  onAnnounce: (message: string) => void;
}) {
  const title = stopped ? 'Session stopped' : stageIndex === 2 ? 'Implementing' : stage.label;
  const detail = stopped ? 'Choose a stage to continue your session.' : stage.detail;

  return (
    <section className="session-workspace cockpit-overlay" aria-label="Session preview">
      <GoalPanel />
      <section className="glass-panel session-head-panel" aria-label="Current session stage">
        <div className="stage-title">
          <small>{`Stage ${stageIndex + 1} of ${STAGES.length}`}</small>
          <h1>{title}</h1>
          <p>{detail}</p>
        </div>
        <StageRail current={stageIndex} onSelect={onSelectStage} />
      </section>
      <InsightPanel stage={stage} onAnnounce={onAnnounce} />
      <Timeline />
      <ActivityPanel />
    </section>
  );
}

function GoalPanel() {
  return (
    <aside className="glass-panel goal-panel">
      <div className="eyebrow-row"><span>Current Goal</span><button type="button"><FlowIcon>✎</FlowIcon> Edit</button></div>
      <h2>Finish authentication<br />and get all tests passing</h2>
      <p className="session-started"><i aria-hidden="true" />Started 1h 24m ago</p>
      <div className="metric-stack">{SAMPLE_METRICS.map((metric) => <Metric key={metric.label} {...metric} />)}</div>
      <blockquote>“Consistent steps<br />create extraordinary results.”<small>— FLOW</small></blockquote>
    </aside>
  );
}

function Metric({ label, value, status, note, color }: (typeof SAMPLE_METRICS)[number]) {
  const display = value;
  const progress = value * 3.6;
  return (
    <div className="metric">
      <span className={`metric-ring ${color}`} style={{ '--progress': `${progress}deg` } as CSSProperties}><b>{display}</b></span>
      <span className="metric-copy"><strong>{label}</strong><em>{status}</em>{note && <small>{note}</small>}</span>
    </div>
  );
}

function StageRail({ current, onSelect }: { current: number; onSelect: (index: number) => void }) {
  return (
    <ol className="stage-rail" aria-label="Session stages">
      {STAGES.map((item, index) => (
        <li key={item.label} className={index === current ? 'is-current' : index < current ? 'is-complete' : ''}>
          <button type="button" onClick={() => onSelect(index)} aria-current={index === current ? 'step' : undefined} aria-label={`Select ${item.label} stage`}>
            <span>{index < current ? '✓' : item.symbol}</span>
            <small>{item.label}</small>
          </button>
        </li>
      ))}
    </ol>
  );
}

function InsightPanel({ stage, onAnnounce }: { stage: Stage; onAnnounce: (message: string) => void }) {
  const [accepted, setAccepted] = useState(false);
  const [alternative, setAlternative] = useState(false);
  const chooseAction = () => { setAccepted(true); setAlternative(false); onAnnounce('Full authentication test suite queued.'); };
  const body = alternative
    ? 'FLOW can verify the most recent changes first, then run the complete authentication suite.'
    : stage.insight;

  return (
    <aside className="glass-panel insight-panel">
      <header><span><FlowIcon>☼</FlowIcon> AI Insight</span><b>High Confidence</b></header>
      <p>{body}</p>
      <div className="panel-divider" /><small className="section-label">Evidence</small>
      <ul className="evidence-list"><li className="confirmed">Expiry test passed</li><li className="confirmed">Implementation changed</li><li>Full auth suite not yet run</li></ul>
      <div className="panel-divider" /><strong className="next-action-label">Recommended Next Action</strong>
      <div className="recommendation-card"><FlowIcon>⌁</FlowIcon><span>Run the full authentication<br />test suite<small>This will verify all tests are passing.</small></span></div>
      <button type="button" className="primary-action" onClick={chooseAction}>{accepted ? '✓  Queued' : '▶  Do it'}</button>
      <button type="button" className="secondary-action" onClick={() => { setAlternative(true); setAccepted(false); onAnnounce('Alternative verification plan shown.'); }}>Plan alternatives</button>
    </aside>
  );
}

function Timeline() {
  return (
    <section className="glass-panel timeline-panel" aria-label="Session timeline">
      <header><strong>Session Timeline</strong><span><i /> Focused <i className="blue" /> Mixed <i className="gray" /> Away <i className="violet" /> Agent</span></header>
      <div className="timeline-track" aria-hidden="true"><b className="away" /><b className="focused" /><b className="focused short" /><b className="mixed" /><b className="away small" /><b className="mixed long" /><b className="focused" /><b className="mixed long" /><b className="agent small" /><b className="away" /><b className="focused" /><b className="focused long" /><b className="mixed long" /><b className="mixed short" /><b className="agent" /><span /></div>
      <footer><span>10:00</span><span>11:00</span><span>12:00</span><span>1:00</span><span>2:00</span><strong>Now</strong></footer>
    </section>
  );
}

function ActivityPanel() {
  return (
    <section className="glass-panel activity-panel" aria-label="Live activity">
      <header><strong><i aria-hidden="true" />Live Activity</strong><button type="button">View all</button></header>
      {ACTIVITIES.map((activity) => (
        <div className="activity-row" key={activity.label}><FlowIcon>{activity.icon}</FlowIcon><span>{activity.label}</span><time>{activity.time}</time></div>
      ))}
    </section>
  );
}

function AgentPreview({ stage, onAnnounce }: { stage: Stage; onAnnounce: (message: string) => void }) {
  const [filter, setFilter] = useState<'all' | 'running' | 'queued' | 'done'>('all');
  const [selectedTask, setSelectedTask] = useState(0);
  const [detail, setDetail] = useState('');
  const [prompt, setPrompt] = useState('');
  const [approval, setApproval] = useState<ApprovalState>('pending');
  const displayedTasks = filter === 'all' ? TASKS : TASKS.filter((task) => task.kind === filter);
  const submitPrompt = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!prompt.trim()) return; onAnnounce(`FLOW received: ${prompt.trim()}`); setPrompt(''); };
  const agentLine = selectedTask === 0
    ? stage.insight
    : `${TASKS[selectedTask]!.title} is ready for review.`;

  return (
    <section className="agent-workspace cockpit-overlay" aria-label="Agent preview">
      <aside className="glass-panel task-panel">
        <header><h1>Agent Tasks</h1><button type="button" onClick={() => onAnnounce('New task form is ready.')}>＋ New Task</button></header>
        <div className="task-filters" role="tablist" aria-label="Task filters">
          {([['all', 'All', 4], ['running', 'Running', 1], ['queued', 'Queued', 2], ['done', 'Done', 1]] as const).map(([value, label, count]) => (
            <button key={value} type="button" role="tab" aria-selected={filter === value} className={filter === value ? 'is-active' : ''} onClick={() => setFilter(value)}>{label} <b>{count}</b></button>
          ))}
        </div>
        <div className="task-list">
          {displayedTasks.map((task) => {
            const index = TASKS.indexOf(task);
            return (
              <button type="button" key={task.title} className={`task-card ${index === selectedTask ? 'is-selected' : ''} ${task.kind}`} onClick={() => { setSelectedTask(index); onAnnounce(`${task.title} selected.`); }}>
                <i aria-hidden="true">{task.kind === 'done' ? '✓' : task.kind === 'running' ? '◔' : '◌'}</i>
                <span>{task.title}<small>{task.detail}</small></span>
                <b>{task.kind === 'running' ? '50%' : '›'}</b>
              </button>
            );
          })}
        </div>
        <blockquote>“Delegate the routine.<br />Focus on what matters.”<small>— FLOW</small></blockquote>
      </aside>
      <section className="agent-center agent-center-overlay">
        <div className="glass-panel agent-title-card"><h1>Your AI pair programmer and productivity partner</h1><p>Understand. Plan. Execute. Verify. Together.</p></div>
        <section className="agent-response glass-panel">
          <header><strong><FlowIcon>✦</FlowIcon> FLOW</strong><time>{new Date().toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</time></header>
          <p>{agentLine}</p>
          {(['Plan (6 steps)', 'Tool Calls (3)', 'Evidence'] as const).map((label) => (
            <div key={label}>
              <button type="button" aria-expanded={detail === label} onClick={() => setDetail(detail === label ? '' : label)}>
                <FlowIcon>{label === 'Plan (6 steps)' ? '▤' : label === 'Tool Calls (3)' ? '⌁' : '◉'}</FlowIcon>
                {label}
                <small>View {label === 'Plan (6 steps)' ? 'plan' : 'all'}</small>
                <b>›</b>
              </button>
              {detail === label && (
                <p className="detail-copy">
                  {label === 'Plan (6 steps)' ? 'Inspect the failure, confirm the timestamp contract, apply the smallest safe change, and run the full suite.' : label === 'Tool Calls (3)' ? 'Read token.py, searched for expiration mismatch, and ran the targeted test.' : 'The expiry test passed and the implementation changed.'}
                </p>
              )}
            </div>
          ))}
        </section>
        <form className="agent-composer glass-panel" onSubmit={submitPrompt}>
          <label className="sr-only" htmlFor="flow-showcase-prompt">Ask FLOW anything</label>
          <input id="flow-showcase-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask FLOW anything..." />
          <button type="submit" aria-label="Send prompt"><FlowIcon>➤</FlowIcon></button>
          <div>{['What’s the issue?', 'Show me the plan', 'Run the full test suite', 'Suggest a fix', 'Explain this error'].map((value) => (
            <button key={value} type="button" onClick={() => setPrompt(value)}>{value}</button>
          ))}</div>
        </form>
      </section>
      <aside className="agent-sidebar">
        <section className="glass-panel agent-status">
          <header><h2>Agent Status</h2><span><i />Working</span></header>
          <StatusRow icon="▤" label="Model" value="Qwen3-VL 4B" />
          <StatusRow icon="⌘" label="Tools" value="6 available" />
          <StatusRow icon="▱" label="Workspace" value="~/projects/auth" />
          <StatusRow icon="♢" label="Permissions" value="Safe Execute" />
        </section>
        <section className="glass-panel tools-panel"><header><h2>Available Tools</h2><button type="button" onClick={() => onAnnounce('All six safe-execute tools are shown.')}>View all</button></header><div>{TOOLS.map(([icon, label]) => <button type="button" key={label} onClick={() => onAnnounce(`${label} selected.`)}><FlowIcon>{icon}</FlowIcon>{label}</button>)}</div></section>
        <section className={`glass-panel approval-panel ${approval}`}>
          <header><h2>Pending Approval <b>{approval === 'pending' ? '1' : '0'}</b></h2><button type="button">Review all</button></header>
          {approval === 'pending' ? (
            <>
              <p>Modify services/auth/token.py</p>
              <pre aria-label="Proposed code change"><code><del>- expires_at = datetime.now()</del><ins>+ expires_at = datetime.now(timezone.utc)</ins></code></pre>
              <div>
                <button type="button" className="approval-yes" onClick={() => { setApproval('approved'); onAnnounce('Patch approved for safe execution.'); }}>✓ &nbsp; Approve</button>
                <button type="button" onClick={() => { setApproval('denied'); onAnnounce('Patch denied. No files were changed.'); }}>× &nbsp; Deny</button>
              </div>
            </>
          ) : <p className="approval-result">{approval === 'approved' ? '✓ Patch approved for safe execution.' : '× Patch denied. No files changed.'}</p>}
        </section>
        <section className="glass-panel recent-panel"><header><h2>Recent Activity</h2><button type="button">View all</button></header>{ACTIVITIES.map((activity) => <div className="activity-row" key={activity.label}><FlowIcon>{activity.icon}</FlowIcon><span>{activity.label.replace('Editing', 'Read')}</span><time>{activity.time}</time></div>)}</section>
      </aside>
    </section>
  );
}

function StatusRow({ icon, label, value }: { icon: string; label: string; value: string }) {
  return <p className="status-row"><FlowIcon>{icon}</FlowIcon><span>{label}</span><b>{value}</b></p>;
}

function SessionControls({
  paused,
  muted,
  stopped,
  onPause,
  onMute,
  onAsk,
  onDelegate,
  onStop,
}: {
  paused: boolean;
  muted: boolean;
  stopped: boolean;
  onPause: () => void;
  onMute: () => void;
  onAsk: () => void;
  onDelegate: () => void;
  onStop: () => void;
}) {
  return (
    <nav className="session-controls" aria-label="Session controls">
      <button type="button" onClick={onPause}><FlowIcon>{paused || stopped ? '▶' : 'Ⅱ'}</FlowIcon>{paused || stopped ? 'Resume' : 'Pause'}</button>
      <button type="button" onClick={onMute}><FlowIcon>◖</FlowIcon>{muted ? 'Unmute' : 'Mute'}</button>
      <button type="button" onClick={onAsk}><FlowIcon>⌁</FlowIcon>Ask FLOW</button>
      <button type="button" onClick={onDelegate}><FlowIcon>➤</FlowIcon>Delegate</button>
      <button type="button" className="stop" onClick={onStop}><FlowIcon>■</FlowIcon>Stop</button>
    </nav>
  );
}
