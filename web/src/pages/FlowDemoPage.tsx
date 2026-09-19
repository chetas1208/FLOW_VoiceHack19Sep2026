import { useEffect, useMemo, useState } from 'react';

type Tab = 'session' | 'agent';
type Stage = { id: string; label: string; detail: string; insight: string; activity: string };

const STAGES: Stage[] = [
  { id: 'understand', label: 'Understand', detail: 'Reading the goal and project context', insight: 'FLOW has enough context to turn the goal into a small, verifiable sequence.', activity: 'Mapped the authentication goal' },
  { id: 'plan', label: 'Plan', detail: 'Breaking the work into focused steps', insight: 'The plan keeps the next change small and leaves a clear verification point.', activity: 'Created a focused implementation plan' },
  { id: 'implement', label: 'Implement', detail: 'Writing code and making changes', insight: 'The targeted expiry test now passes, but the full suite still needs to run.', activity: 'Editing services/auth/token.py' },
  { id: 'validate', label: 'Validate', detail: 'Running tests and checking evidence', insight: 'Validation is the next confidence jump: run the full authentication test suite.', activity: 'Ran pytest tests/auth' },
  { id: 'complete', label: 'Complete', detail: 'Goal completed with evidence', insight: 'The goal is ready to close once the final evidence is reviewed.', activity: 'Collected final session evidence' },
];

const ACTIVITIES = [
  ['Editing token.py', '2m ago', '⌘'],
  ['Ran pytest tests/auth', '4m ago', '▣'],
  ['Modified services/auth/', '8m ago', '▤'],
] as const;

function stageIndex(elapsed: number) { return Math.min(STAGES.length - 1, Math.floor(elapsed / 18)); }

export default function FlowDemoPage() {
  const [tab, setTab] = useState<Tab>('session');
  const [playing, setPlaying] = useState(true);
  const [elapsed, setElapsed] = useState(38);
  const [muted, setMuted] = useState(false);
  const [stopped, setStopped] = useState(false);
  const current = stageIndex(elapsed);
  const stage = STAGES[current]!;
  const progress = Math.min(100, Math.round((elapsed / 90) * 100));
  const metrics = useMemo(() => ({ efficiency: Math.min(99, 74 + current * 3), alignment: Math.min(99, 78 + current * 4), focus: Math.min(99, 71 + current * 5), progress: Math.min(99, 58 + current * 9) }), [current]);

  useEffect(() => {
    if (!playing || stopped) return;
    const timer = window.setInterval(() => setElapsed((value) => value >= 89 ? 0 : value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [playing, stopped]);

  function reset() { setElapsed(0); setPlaying(true); setStopped(false); }

  return (
    <main className="flow-demo" aria-label="FLOW session workspace">
      <header className="demo-header">
        <div className="demo-brand"><span>FLOW</span><small>FOCUS TODAY. A BETTER TOMORROW.</small></div>
        <div className="demo-tabs" role="tablist" aria-label="FLOW views">
          {(['session', 'agent'] as const).map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>{item === 'session' ? '◉  Session' : '✦  Agent'}</button>)}
        </div>
        <div className="demo-device"><i /> <span>MacBook Pro<small>Connected</small></span><b>⌄</b><button type="button" aria-label="Device settings">⚙</button></div>
        <time className="demo-date">Mon, Sep 22<br /><b>2:14 PM</b></time>
      </header>

      {tab === 'session' ? <SessionView stage={stage} current={current} progress={progress} metrics={metrics} elapsed={elapsed} /> : <AgentView stage={stage} />}

      <div className="demo-controls" role="toolbar" aria-label="Session controls">
        <button type="button" onClick={() => setPlaying((value) => !value)}>{playing && !stopped ? 'Ⅱ' : '▶'} <span>{playing && !stopped ? 'Pause' : 'Play'}</span></button>
        <button type="button" onClick={() => setMuted((value) => !value)}>{muted ? '🔇' : '◖'} <span>{muted ? 'Unmute' : 'Mute'}</span></button>
        <button type="button" onClick={() => window.alert('Ask FLOW is available from the live session.')}>⌁ <span>Ask FLOW</span></button>
        <button type="button" onClick={() => setTab('agent')}>➤ <span>Delegate</span></button>
        <button type="button" className="stop" onClick={() => { setStopped(true); setPlaying(false); }}>■ <span>Stop</span></button>
        <button type="button" className="reset" onClick={reset}>Reset</button>
      </div>
      <footer className="demo-footer"><span><i /> Local AI Models Ready</span><b>Qwen3-VL 4B</b><b>Kokoro TTS</b><small>▣ &nbsp; All data stays on your machine. Always.</small></footer>
    </main>
  );
}

function SessionView({ stage, current, progress, metrics, elapsed }: { stage: Stage; current: number; progress: number; metrics: Record<string, number>; elapsed: number }) {
  return <div className="demo-grid session-view">
    <aside className="demo-panel goal-panel"><div className="panel-title"><span>Current Goal</span><button type="button">✎ Edit</button></div><h1>Finish authentication<br />and get all tests passing</h1><p className="started"><i /> Started 1h 24m ago</p><MetricRing label="Session Efficiency" value={metrics.efficiency} delta="↗ 12%" tone="green" /><MetricRing label="Goal Alignment" value={metrics.alignment} delta="On track" tone="green" /><MetricRing label="Focus" value={metrics.focus} delta="Strong" tone="blue" /><MetricRing label="Progress" value={metrics.progress} delta="Building" tone="gold" /><blockquote>“Consistent steps<br />create extraordinary results.”<br /><small>— FLOW</small></blockquote></aside>
    <section className="demo-center"><div className="stage-heading"><small>Stage {current + 1} of {STAGES.length}</small><h2>{stage.label}</h2><p>{stage.detail}</p></div><StageRail current={current} /><Diorama current={current} /><div className="stage-scrub"><input aria-label="Session progress" type="range" min="0" max="90" value={progress * .9} onChange={(e) => { /* visual demo keeps one source of truth */ void e; }} /><span>{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</span></div><Timeline progress={progress} /></section>
    <aside className="demo-right"><Insight stage={stage} /><Activity /></aside>
  </div>;
}

function MetricRing({ label, value, delta, tone }: { label: string; value: number; delta: string; tone: string }) { return <div className="metric-ring"><span className={`ring ring-${tone}`} style={{ '--value': `${value * 3.6}deg` } as React.CSSProperties}><b>{value}</b></span><span><strong>{label}</strong><em>{delta}</em></span></div>; }
function StageRail({ current }: { current: number }) { return <ol className="stage-rail">{STAGES.map((item, index) => <li className={index === current ? 'current' : index < current ? 'done' : ''} key={item.id}><span>{index < current ? '✓' : index === current ? '</>' : index + 1}</span><small>{item.label}</small></li>)}</ol>; }
function Diorama({ current }: { current: number }) { return <div className={`diorama scene-${current}`} aria-label="Stage-aware FLOW workstation simulation"><div className="glow" /><div className="desk"><div className="screen screen-left" /><div className="screen screen-main" /><div className="screen screen-right" /><div className="person" /><div className="keyboard" /><i className="plant" /><i className="mug">FLOW</i></div><div className="badge badge-left">▣ &nbsp; Visual Studio Code<br /><small>Active · 42m</small></div><div className="badge badge-right">⚠ &nbsp; Running Tests<br /><small>3 failing</small></div></div>; }
function Timeline({ progress }: { progress: number }) { return <section className="demo-timeline"><header><strong>Session Timeline</strong><span>● Focused　 <i>●</i> Mixed　 <b>●</b> Away　 <em>●</em> Agent</span></header><div className="timeline-bar"><i style={{ width: `${progress}%` }} /></div><footer><span>10:00</span><span>11:00</span><span>12:00</span><span>1:00</span><span>2:00</span><b>Now</b></footer></section>; }
function Insight({ stage }: { stage: Stage }) { return <section className="demo-panel insight"><header>♧　 AI Insight <span>High Confidence</span></header><p>{stage.insight}</p><hr /><small>Evidence</small><ul><li>✓ Expiry test passed</li><li>✓ Implementation changed</li><li>○ Full auth suite not yet run</li></ul><hr /><strong>Recommended Next Action</strong><div className="recommendation">▣ <span>Run the full authentication test suite<small>This will verify all tests are passing.</small></span><button type="button">▶　Do it</button><button type="button">Plan alternatives</button></div></section>; }
function Activity() { return <section className="demo-panel activity"><header><strong><i /> Live Activity</strong><span>View all</span></header>{ACTIVITIES.map(([message, time, icon]) => <div key={message}><b>{icon}</b><span>{message}</span><small>{time}</small></div>)}</section>; }
function AgentView({ stage }: { stage: Stage }) { return <div className="demo-grid agent-view"><aside className="demo-panel task-panel"><header><h2>Agent Tasks</h2><button type="button">＋ New Task</button></header>{['Diagnose failing authentication tests', 'Run full authentication test suite', 'Check dependency updates', 'Analyze project structure'].map((task, index) => <article className={index === 0 ? 'selected' : ''} key={task}><i>{index === 3 ? '✓' : `${index + 1}`}</i><span>{task}<small>{index === 0 ? 'Step 3 of 6 · Analyzing test failure' : index === 3 ? 'Completed · 12m ago' : 'Queued · Waiting for approval'}</small></span><b>{index === 0 ? '50%' : '›'}</b></article>)}<blockquote>“Delegate the routine.<br />Focus on what matters.”<br /><small>— FLOW</small></blockquote></aside><section className="agent-stage"><h2>Your AI pair programmer and productivity partner</h2><p>Understand. Plan. Execute. Verify. Together. · {stage.label}</p><Diorama current={2} /><div className="agent-message"><b>✦　 FLOW <small>2:11 PM</small></b><p>I found 3 failing tests in the authentication suite. The error appears to be an expiration timestamp mismatch.</p><button type="button">▣　Plan (6 steps)　›</button><button type="button">▤　Tool Calls (3)　›</button><button type="button">◉　Evidence　›</button></div></section><aside className="demo-right"><section className="demo-panel status-panel"><header>Agent Status <span>● Working</span></header><p>▤　 Model <b>Qwen3-VL 4B</b></p><p>⌘　 Tools <b>6 available</b></p><p>□　 Workspace <b>~/projects/auth</b></p><p>♢　 Permissions <b>Safe Execute</b></p></section><Activity /></aside></div>; }
