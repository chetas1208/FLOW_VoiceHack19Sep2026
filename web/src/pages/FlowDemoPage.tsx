import { useState, type CSSProperties, type FormEvent } from 'react';
import sessionScene from '../assets/flow-session-scene.png';
import agentScene from '../assets/flow-agent-scene.png';

type Tab = 'session' | 'agent';
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

const METRICS = [
  { label: 'Session Efficiency', value: 86, status: '↗ 12%', note: 'Good Progress', color: 'mint' },
  { label: 'Goal Alignment', value: 91, status: 'On track', note: '', color: 'mint' },
  { label: 'Focus', value: 84, status: 'Strong', note: '', color: 'blue' },
  { label: 'Progress', value: 72, status: 'Building', note: '', color: 'gold' },
] as const;

const ACTIVITIES = [
  { icon: '⌘', label: 'Editing token.py', time: '2m ago' },
  { icon: '⌁', label: 'Ran pytest tests/auth', time: '4m ago' },
  { icon: '▤', label: 'Modified services/auth/', time: '8m ago' },
] as const;

const TASKS = [
  { title: 'Diagnose failing authentication tests', detail: 'Step 3 of 6  ·  Analyzing test failure', kind: 'running' },
  { title: 'Run full authentication test suite', detail: 'Queued  ·  Waiting for approval', kind: 'queued' },
  { title: 'Check dependency updates', detail: 'Queued  ·  Scheduled next', kind: 'queued' },
  { title: 'Analyze project structure', detail: 'Completed  ·  12m ago', kind: 'done' },
] as const;

const TOOLS = [
  ['▤', 'Read File'],
  ['⌕', 'Search Code'],
  ['▶', 'Run Tests'],
  ['⌁', 'Run Command'],
  ['⌘', 'Git Status'],
  ['↗', 'Apply Patch'],
] as const;

function Icon({ children, className = '' }: { children: string; className?: string }) {
  return <span aria-hidden="true" className={`flow-icon ${className}`}>{children}</span>;
}

export default function FlowDemoPage() {
  const [tab, setTab] = useState<Tab>('session');
  const [stageIndex, setStageIndex] = useState(2);
  const [paused, setPaused] = useState(false);
  const [muted, setMuted] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [notice, setNotice] = useState('');

  const stage = STAGES[stageIndex]!;
  const selectStage = (index: number) => {
    setStopped(false);
    setStageIndex(index);
    setNotice(`${STAGES[index]!.label} stage selected.`);
  };

  return (
    <main className="flow-demo" aria-label="FLOW session intelligence workspace">
      <div className="flow-atmosphere" aria-hidden="true" />
      <div className={`flow-shell ${tab === 'agent' ? 'is-agent-view' : ''}`}>
        <Header activeTab={tab} onTabChange={setTab} />
        {tab === 'session' ? (
          <SessionView stage={stage} stageIndex={stageIndex} stopped={stopped} onSelectStage={selectStage} onNotice={setNotice} />
        ) : (
          <AgentView stage={stage} onNotice={setNotice} />
        )}
        {tab === 'session' && <SessionControls
          paused={paused}
          muted={muted}
          stopped={stopped}
          onPause={() => { setPaused((value) => !value); setStopped(false); setNotice(paused ? 'Session resumed.' : 'Session paused.'); }}
          onMute={() => { setMuted((value) => !value); setNotice(muted ? 'FLOW audio unmuted.' : 'FLOW audio muted.'); }}
          onAsk={() => { setTab('agent'); setNotice('FLOW is ready for your direction.'); }}
          onDelegate={() => { setTab('agent'); setNotice('Delegation workspace opened.'); }}
          onStop={() => { setStopped(true); setPaused(true); setNotice('Session stopped.'); }}
        />}
        <p className="flow-announcement" role="status" aria-live="polite">{notice}</p>
        <Footer stopped={stopped} />
      </div>
    </main>
  );
}

function Header({ activeTab, onTabChange }: { activeTab: Tab; onTabChange: (tab: Tab) => void }) {
  return <header className="flow-header">
    <div className="flow-brand" aria-label="FLOW"><strong>FLOW</strong><span>FOCUS TODAY. A BETTER TOMORROW.</span></div>
    <div className="view-tabs" role="tablist" aria-label="FLOW workspace view">
      <button type="button" role="tab" aria-selected={activeTab === 'session'} className={activeTab === 'session' ? 'is-active' : ''} onClick={() => onTabChange('session')}><Icon>◉</Icon>Session</button>
      <button type="button" role="tab" aria-selected={activeTab === 'agent'} className={activeTab === 'agent' ? 'is-active' : ''} onClick={() => onTabChange('agent')}><Icon>✦</Icon>Agent</button>
    </div>
    <div className="device-status"><i aria-hidden="true" /><span>MacBook Pro<small>Connected</small></span><b aria-hidden="true">⌄</b><button type="button" aria-label="Open device settings"><Icon>⚙</Icon></button></div>
    <time dateTime="2026-09-22T14:14">Mon, Sep 22<br /><strong>2:14 PM</strong></time>
  </header>;
}

function SessionView({ stage, stageIndex, stopped, onSelectStage, onNotice }: {
  stage: Stage;
  stageIndex: number;
  stopped: boolean;
  onSelectStage: (index: number) => void;
  onNotice: (message: string) => void;
}) {
  return <section className="session-workspace" aria-label="Session view">
    <GoalPanel />
    <section className="session-center" aria-label="Current session stage">
      <div className="stage-title"><small>Stage {stageIndex + 1} of {STAGES.length}</small><h1>{stopped ? 'Session stopped' : stageIndex === 2 ? 'Implementing' : stage.label}</h1><p>{stopped ? 'Choose a stage to continue your session.' : stage.detail}</p></div>
      <StageRail current={stageIndex} onSelect={onSelectStage} />
      <Scene image={sessionScene} type="session" stage={stage} />
    </section>
    <InsightPanel stage={stage} onNotice={onNotice} />
    <Timeline />
    <ActivityPanel />
  </section>;
}

function GoalPanel() {
  return <aside className="glass-panel goal-panel">
    <div className="eyebrow-row"><span>Current Goal</span><button type="button"><Icon>✎</Icon> Edit</button></div>
    <h2>Finish authentication<br />and get all tests passing</h2>
    <p className="session-started"><i aria-hidden="true" />Started 1h 24m ago</p>
    <div className="metric-stack">{METRICS.map((metric) => <Metric key={metric.label} {...metric} />)}</div>
    <blockquote>“Consistent steps<br />create extraordinary results.”<small>— FLOW</small></blockquote>
  </aside>;
}

function Metric({ label, value, status, note, color }: (typeof METRICS)[number]) {
  return <div className="metric">
    <span className={`metric-ring ${color}`} style={{ '--progress': `${value * 3.6}deg` } as CSSProperties}><b>{value}</b></span>
    <span className="metric-copy"><strong>{label}</strong><em>{status}</em>{note && <small>{note}</small>}</span>
  </div>;
}

function StageRail({ current, onSelect }: { current: number; onSelect: (index: number) => void }) {
  return <ol className="stage-rail" aria-label="Session stages">{STAGES.map((item, index) => <li key={item.label} className={index === current ? 'is-current' : index < current ? 'is-complete' : ''}>
    <button type="button" onClick={() => onSelect(index)} aria-current={index === current ? 'step' : undefined} aria-label={`Select ${item.label} stage`}><span>{index < current ? '✓' : item.symbol}</span><small>{item.label}</small></button>
  </li>)}</ol>;
}

function Scene({ image, type, stage }: { image: string; type: 'session' | 'agent'; stage: Stage }) {
  const isSession = type === 'session';
  return <figure className={`flow-scene ${type}-scene`} aria-label={isSession ? 'A developer working at a multi-monitor desk' : 'A helpful FLOW agent at a workspace'}>
    <img src={image} alt="" /><div className="scene-vignette" aria-hidden="true" />
    {isSession ? <>
      <div className="scene-card editor-card"><Icon>⌘</Icon><span>Visual Studio Code<small>Active · 42m</small></span></div>
      <div className="scene-card test-card"><Icon>⚠</Icon><span>Running Tests<small>3 failing</small></span></div>
      <div className="monitor-copy" aria-hidden="true"><small>pytest</small><b>3 failed, 18 passed</b><em>in 12.4s</em></div><figcaption>GOOD THINGS TAKE FOCUS</figcaption>
    </> : <>
      <div className="agent-float-card agent-analysis"><strong><Icon>✦</Icon> Analyzing...</strong><span>✓ &nbsp; Reading test output</span><span>✓ &nbsp; Inspecting code</span><span>○ &nbsp; Identifying root cause</span><span>○ &nbsp; Proposing fix</span><span>○ &nbsp; Ready for review</span><span>○ &nbsp; Verify and complete</span></div>
      <div className="agent-float-card agent-files"><small>▱ Services/auth/</small><span>↳ token.py</span><span>↳ middleware.py</span><span>↳ test_auth.py</span><span>↳ utils.py</span></div>
    </>}
    <span className="scene-state" aria-hidden="true">{stage.activity}</span>
  </figure>;
}

function InsightPanel({ stage, onNotice }: { stage: Stage; onNotice: (message: string) => void }) {
  const [accepted, setAccepted] = useState(false);
  const [alternative, setAlternative] = useState(false);
  const chooseAction = () => { setAccepted(true); setAlternative(false); onNotice('Full authentication test suite queued.'); };
  return <aside className="glass-panel insight-panel">
    <header><span><Icon>☼</Icon> AI Insight</span><b>High Confidence</b></header>
    <p>{alternative ? 'FLOW can verify the most recent changes first, then run the complete authentication suite.' : stage.insight}</p>
    <div className="panel-divider" /><small className="section-label">Evidence</small>
    <ul className="evidence-list"><li className="confirmed">Expiry test passed</li><li className="confirmed">Implementation changed</li><li>Full auth suite not yet run</li></ul>
    <div className="panel-divider" /><strong className="next-action-label">Recommended Next Action</strong>
    <div className="recommendation-card"><Icon>⌁</Icon><span>Run the full authentication<br />test suite<small>This will verify all tests are passing.</small></span></div>
    <button type="button" className="primary-action" onClick={chooseAction}>{accepted ? '✓  Queued' : '▶  Do it'}</button>
    <button type="button" className="secondary-action" onClick={() => { setAlternative(true); setAccepted(false); onNotice('Alternative verification plan shown.'); }}>Plan alternatives</button>
  </aside>;
}

function Timeline() {
  return <section className="glass-panel timeline-panel" aria-label="Session timeline">
    <header><strong>Session Timeline</strong><span><i /> Focused <i className="blue" /> Mixed <i className="gray" /> Away <i className="violet" /> Agent</span></header>
    <div className="timeline-track" aria-hidden="true"><b className="away" /><b className="focused" /><b className="focused short" /><b className="mixed" /><b className="away small" /><b className="mixed long" /><b className="focused" /><b className="mixed long" /><b className="agent small" /><b className="away" /><b className="focused" /><b className="focused long" /><b className="mixed long" /><b className="mixed short" /><b className="agent" /><span /></div>
    <footer><span>10:00</span><span>11:00</span><span>12:00</span><span>1:00</span><span>2:00</span><strong>Now</strong></footer>
  </section>;
}

function ActivityPanel() {
  return <section className="glass-panel activity-panel" aria-label="Live activity">
    <header><strong><i aria-hidden="true" />Live Activity</strong><button type="button">View all</button></header>
    {ACTIVITIES.map((activity) => <div className="activity-row" key={activity.label}><Icon>{activity.icon}</Icon><span>{activity.label}</span><time>{activity.time}</time></div>)}
  </section>;
}

function AgentView({ stage, onNotice }: { stage: Stage; onNotice: (message: string) => void }) {
  const [filter, setFilter] = useState<'all' | 'running' | 'queued' | 'done'>('all');
  const [selectedTask, setSelectedTask] = useState(0);
  const [detail, setDetail] = useState('');
  const [prompt, setPrompt] = useState('');
  const [approval, setApproval] = useState<ApprovalState>('pending');
  const displayedTasks = filter === 'all' ? TASKS : TASKS.filter((task) => task.kind === filter);
  const submitPrompt = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!prompt.trim()) return; onNotice(`FLOW received: ${prompt.trim()}`); setPrompt(''); };
  return <section className="agent-workspace" aria-label="Agent view">
    <aside className="glass-panel task-panel">
      <header><h1>Agent Tasks</h1><button type="button" onClick={() => onNotice('New task form is ready.')}>＋ New Task</button></header>
      <div className="task-filters" role="tablist" aria-label="Task filters">{([['all', 'All', 4], ['running', 'Running', 1], ['queued', 'Queued', 2], ['done', 'Done', 1]] as const).map(([value, label, count]) => <button key={value} type="button" role="tab" aria-selected={filter === value} className={filter === value ? 'is-active' : ''} onClick={() => setFilter(value)}>{label} <b>{count}</b></button>)}</div>
      <div className="task-list">{displayedTasks.map((task) => { const index = TASKS.indexOf(task); return <button type="button" key={task.title} className={`task-card ${index === selectedTask ? 'is-selected' : ''} ${task.kind}`} onClick={() => { setSelectedTask(index); onNotice(`${task.title} selected.`); }}><i aria-hidden="true">{task.kind === 'done' ? '✓' : task.kind === 'running' ? '◔' : '◌'}</i><span>{task.title}<small>{task.detail}</small></span><b>{task.kind === 'running' ? '50%' : '›'}</b></button>; })}</div>
      <blockquote>“Delegate the routine.<br />Focus on what matters.”<small>— FLOW</small></blockquote>
    </aside>
    <section className="agent-center">
      <div className="agent-title"><h1>Your AI pair programmer and productivity partner</h1><p>Understand. Plan. Execute. Verify. Together.</p></div>
      <Scene image={agentScene} type="agent" stage={stage} />
      <section className="agent-response glass-panel">
        <header><strong><Icon>✦</Icon> FLOW</strong><time>2:11 PM</time></header>
        <p>{selectedTask === 0 ? 'I found 3 failing tests in the authentication suite. The error appears to be an expiration timestamp mismatch. Let me inspect the relevant code.' : `${TASKS[selectedTask]!.title} is ready for review.`}</p>
        {(['Plan (6 steps)', 'Tool Calls (3)', 'Evidence'] as const).map((label) => <div key={label}><button type="button" aria-expanded={detail === label} onClick={() => setDetail(detail === label ? '' : label)}><Icon>{label === 'Plan (6 steps)' ? '▤' : label === 'Tool Calls (3)' ? '⌁' : '◉'}</Icon>{label}<small>View {label === 'Plan (6 steps)' ? 'plan' : 'all'}</small><b>›</b></button>{detail === label && <p className="detail-copy">{label === 'Plan (6 steps)' ? 'Inspect the failure, confirm the timestamp contract, apply the smallest safe change, and run the full suite.' : label === 'Tool Calls (3)' ? 'Read token.py, searched for expiration mismatch, and ran the targeted test.' : 'The expiry test passed and the implementation changed.'}</p>}</div>)}
      </section>
      <form className="agent-composer glass-panel" onSubmit={submitPrompt}><label className="sr-only" htmlFor="flow-prompt">Ask FLOW anything</label><input id="flow-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask FLOW anything..." /><button type="submit" aria-label="Send prompt"><Icon>➤</Icon></button><div>{['What’s the issue?', 'Show me the plan', 'Run the full test suite', 'Suggest a fix', 'Explain this error'].map((value) => <button key={value} type="button" onClick={() => setPrompt(value)}>{value}</button>)}</div></form>
    </section>
    <aside className="agent-sidebar">
      <section className="glass-panel agent-status"><header><h2>Agent Status</h2><span><i />Working</span></header><StatusRow icon="▤" label="Model" value="Qwen3-VL 4B" /><StatusRow icon="⌘" label="Tools" value="6 available" /><StatusRow icon="▱" label="Workspace" value="~/projects/auth" /><StatusRow icon="♢" label="Permissions" value="Safe Execute" /></section>
      <section className="glass-panel tools-panel"><header><h2>Available Tools</h2><button type="button" onClick={() => onNotice('All six safe-execute tools are shown.')}>View all</button></header><div>{TOOLS.map(([icon, label]) => <button type="button" key={label} onClick={() => onNotice(`${label} selected.`)}><Icon>{icon}</Icon>{label}</button>)}</div></section>
      <section className={`glass-panel approval-panel ${approval}`}><header><h2>Pending Approval <b>{approval === 'pending' ? '1' : '0'}</b></h2><button type="button">Review all</button></header>{approval === 'pending' ? <><p>Modify services/auth/token.py</p><pre aria-label="Proposed code change"><code><del>- expires_at = datetime.now()</del><ins>+ expires_at = datetime.now(timezone.utc)</ins></code></pre><div><button type="button" className="approval-yes" onClick={() => { setApproval('approved'); onNotice('Patch approved for safe execution.'); }}>✓ &nbsp; Approve</button><button type="button" onClick={() => { setApproval('denied'); onNotice('Patch denied. No files were changed.'); }}>× &nbsp; Deny</button></div></> : <p className="approval-result">{approval === 'approved' ? '✓ Patch approved for safe execution.' : '× Patch denied. No files changed.'}</p>}</section>
      <section className="glass-panel recent-panel"><header><h2>Recent Activity</h2><button type="button">View all</button></header>{ACTIVITIES.map((activity) => <div className="activity-row" key={activity.label}><Icon>{activity.icon}</Icon><span>{activity.label.replace('Editing', 'Read')}</span><time>{activity.time}</time></div>)}</section>
    </aside>
  </section>;
}

function StatusRow({ icon, label, value }: { icon: string; label: string; value: string }) { return <p className="status-row"><Icon>{icon}</Icon><span>{label}</span><b>{value}</b></p>; }

function SessionControls({ paused, muted, stopped, onPause, onMute, onAsk, onDelegate, onStop }: { paused: boolean; muted: boolean; stopped: boolean; onPause: () => void; onMute: () => void; onAsk: () => void; onDelegate: () => void; onStop: () => void; }) {
  return <nav className="session-controls" aria-label="Session controls">
    <button type="button" onClick={onPause}><Icon>{paused || stopped ? '▶' : 'Ⅱ'}</Icon>{paused || stopped ? 'Resume' : 'Pause'}</button><button type="button" onClick={onMute}><Icon>◖</Icon>{muted ? 'Unmute' : 'Mute'}</button><button type="button" onClick={onAsk}><Icon>⌁</Icon>Ask FLOW</button><button type="button" onClick={onDelegate}><Icon>➤</Icon>Delegate</button><button type="button" className="stop" onClick={onStop}><Icon>■</Icon>Stop</button>
  </nav>;
}

function Footer({ stopped }: { stopped: boolean }) { return <footer className="flow-footer"><span><i aria-hidden="true" className={stopped ? 'is-stopped' : ''} />{stopped ? 'Session paused locally' : 'Local AI Models Ready'}</span><b>Qwen3-VL 4B</b><b>Kokoro TTS</b><small><Icon>♙</Icon>All data stays on your machine. Always.</small></footer>; }
