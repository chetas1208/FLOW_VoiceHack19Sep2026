import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import agentScene from '../assets/flow-agent-scene.png';
import sessionScene from '../assets/flow-session-scene.png';
import { accountApi, type FlowDevice } from '../lib/account';

type Tab = 'session' | 'agent';

function ago(value: string | null) {
  if (!value) return 'Not seen yet';
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function deviceState(device: FlowDevice | undefined) {
  if (!device) return { label: 'Not linked', detail: 'Install the CLI to link a device.', tone: 'offline' };
  if (device.revoked_at) return { label: 'Revoked', detail: 'Run flow login on this computer to reconnect.', tone: 'offline' };
  if (device.presence.state === 'online') return { label: 'Connected', detail: `Heartbeat ${ago(device.presence.last_heartbeat_at)}`, tone: 'online' };
  if (device.presence.state === 'degraded') return { label: 'Needs attention', detail: `Last contact ${ago(device.last_seen_at)}`, tone: 'degraded' };
  return { label: 'Linked offline', detail: `Last contact ${ago(device.last_seen_at)}`, tone: 'offline' };
}

function Icon({ children }: { children: string }) { return <span aria-hidden="true" className="flow-icon">{children}</span>; }

export default function FlowDemoPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('session');
  const [devices, setDevices] = useState<FlowDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await accountApi.devices();
        if (active) { setDevices(result.items); setError(''); }
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : 'FLOW could not load connected devices.'); }
      finally { if (active) setLoading(false); }
    };
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const device = devices.find((item) => !item.revoked_at && item.presence.state !== 'offline') ?? devices.find((item) => !item.revoked_at) ?? devices[0];
  const state = deviceState(device);
  const health = device?.presence.health ?? {};
  const liveValues = useMemo(() => ({
    account: 100,
    device: device && !device.revoked_at ? 100 : 0,
    daemon: health.daemon === 'running' || state.tone === 'online' ? 100 : 0,
    model: health.model === 'ready' ? 100 : 0,
  }), [device, health.daemon, health.model, state.tone]);

  return <main className="flow-demo" aria-label="FLOW live workspace">
    <div className="flow-atmosphere" aria-hidden="true" />
    <div className={`flow-shell ${tab === 'agent' ? 'is-agent-view' : ''}`}>
      <header className="flow-header">
        <div className="flow-brand" aria-label="FLOW"><strong>FLOW</strong><span>FOCUS TODAY. A BETTER TOMORROW.</span></div>
        <div className="view-tabs" role="tablist" aria-label="FLOW workspace view">
          <button type="button" role="tab" aria-selected={tab === 'session'} className={tab === 'session' ? 'is-active' : ''} onClick={() => setTab('session')}><Icon>◉</Icon>Session</button>
          <button type="button" role="tab" aria-selected={tab === 'agent'} className={tab === 'agent' ? 'is-active' : ''} onClick={() => setTab('agent')}><Icon>✦</Icon>Agent</button>
        </div>
        <div className="device-status"><i className={`device-dot ${state.tone}`} aria-hidden="true" /><span>{device?.name ?? 'No FLOW device'}<small>{state.label}</small></span><button type="button" aria-label="Open FLOW setup docs" onClick={() => navigate('/docs')}><Icon>⚙</Icon></button></div>
        <time dateTime={new Date().toISOString()}>{new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date())}<br /><strong>{new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date())}</strong></time>
      </header>
      {tab === 'session' ? <SessionWorkspace device={device} state={state} values={liveValues} loading={loading} error={error} onDocs={() => navigate('/docs')} /> : <AgentWorkspace device={device} state={state} onDocs={() => navigate('/docs')} />}
      <footer className="flow-footer"><span><i className={state.tone === 'online' ? '' : 'is-stopped'} />{state.label}</span><b>Model budget ≤500 MB</b><b>Synchronous local agents</b><small>♙ Work-session data stays on your machine.</small></footer>
    </div>
  </main>;
}

function SessionWorkspace({ device, state, values, loading, error, onDocs }: { device?: FlowDevice; state: ReturnType<typeof deviceState>; values: Record<string, number>; loading: boolean; error: string; onDocs: () => void }) {
  const metrics = [
    { label: 'Account', value: values.account, status: 'Secure session', color: 'mint' },
    { label: 'Device link', value: values.device, status: state.label, color: 'mint' },
    { label: 'Local daemon', value: values.daemon, status: device?.presence.health.daemon ?? 'Not running', color: 'blue' },
    { label: 'Local model', value: values.model, status: device?.presence.health.model ?? 'Not loaded', color: 'gold' },
  ];
  const stages = ['Install CLI', 'Link account', 'Start local session'];
  const complete = device && !device.revoked_at ? 2 : 1;
  return <section className="session-workspace" aria-label="Live session view">
    <aside className="glass-panel goal-panel"><div className="eyebrow-row"><span>FLOW is live</span><button type="button" onClick={onDocs}><Icon>⌕</Icon> Docs</button></div>
      <h2>{device ? <>Your FLOW device is<br />{state.label.toLowerCase()}</> : <>Connect your local<br />FLOW CLI</>}</h2><p className="session-started"><i aria-hidden="true" />{loading ? 'Checking account devices…' : state.detail}</p>
      <div className="metric-stack">{metrics.map((metric) => <div className="metric" key={metric.label}><span className={`metric-ring ${metric.color}`} style={{ '--progress': `${metric.value * 3.6}deg` } as CSSProperties}><b>{metric.value}</b></span><span className="metric-copy"><strong>{metric.label}</strong><em>{metric.status}</em></span></div>)}</div>
      <blockquote>“Keep the work local.<br />Keep the control clear.”<small>— FLOW</small></blockquote>
    </aside>
    <section className="session-center" aria-label="FLOW connection status"><div className="stage-title"><small>SETUP STATUS</small><h1>{device ? 'Local device linked' : 'Connect your workspace'}</h1><p>{device ? 'FLOW is showing the device state reported by your local CLI.' : 'Install the CLI, sign in from your terminal, then approve the one-time request here.'}</p></div>
      <ol className="stage-rail" aria-label="Connection stages">{stages.map((label, index) => <li key={label} className={index < complete ? 'is-complete' : index === complete - 1 ? 'is-current' : ''}><span><span>{index < complete ? '✓' : index + 1}</span><small>{label}</small></span></li>)}</ol>
      <figure className="flow-scene session-scene" aria-label="FLOW local-first workspace"><img src={sessionScene} alt="" /><div className="scene-vignette" aria-hidden="true" /><div className="scene-card editor-card"><Icon>⌘</Icon><span>{device?.name ?? 'Your computer'}<small>{device ? `${device.os} · FLOW ${device.flow_version}` : 'Waiting for CLI authorization'}</small></span></div><div className="scene-card test-card"><Icon>◉</Icon><span>{state.label}<small>{state.detail}</small></span></div><div className="monitor-copy"><small>LOCAL-FIRST</small><b>No session data is in the cloud</b><em>Models start unloaded</em></div><figcaption>YOUR DEVICE. YOUR DATA.</figcaption></figure>
    </section>
    <aside className="glass-panel insight-panel"><header><span><Icon>☼</Icon> FLOW Insight</span><b>{device ? 'LIVE DEVICE STATE' : 'SETUP REQUIRED'}</b></header><p>{device ? 'This dashboard reads account and device-control metadata live. FLOW does not fabricate an active agent, source edit, test run, or session timeline.' : 'No device is linked yet. Install the CLI to authorize a local device without moving your work data into Neon.'}</p><div className="panel-divider" /><small className="section-label">Privacy boundary</small><ul className="evidence-list"><li className="confirmed">Account and device metadata only</li><li className="confirmed">Browser and cloud models are disabled</li><li>Sessions, prompts, code, and logs stay local</li></ul><div className="panel-divider" /><strong className="next-action-label">Recommended next action</strong><div className="recommendation-card"><Icon>⌁</Icon><span>{device ? 'Open the local CLI and start a session' : 'Install and link the FLOW CLI'}<small>{device ? 'Use flow start with a goal on your computer.' : 'A browser approval protects the device connection.'}</small></span></div><button type="button" className="primary-action" onClick={onDocs}>Open setup docs</button></aside>
    <section className="glass-panel timeline-panel" aria-label="Local session timeline"><header><strong>Session Timeline</strong><span><i /> Local only</span></header><div className="empty-live-panel">A timeline appears only when your paired local daemon shares it directly with this browser. FLOW does not copy it into the account database.</div><footer><span>Local daemon</span><strong>{device ? state.label : 'Not linked'}</strong></footer></section>
    <section className="glass-panel activity-panel" aria-label="Live account activity"><header><strong><i aria-hidden="true" />Live Device Activity</strong><button type="button" onClick={onDocs}>Docs</button></header>{error ? <p className="live-error">{error}</p> : device ? <><div className="activity-row"><Icon>⌘</Icon><span>Device authorization active</span><time>{ago(device.created_at)}</time></div><div className="activity-row"><Icon>◉</Icon><span>{state.detail}</span><time>{ago(device.last_seen_at)}</time></div><div className="activity-row"><Icon>▤</Icon><span>Model status: {device.presence.health.model ?? 'not loaded'}</span><time>Local</time></div></> : <div className="empty-live-panel">No linked devices. Open setup docs to install and connect the CLI.</div>}</section>
    <div className="session-controls"><button type="button" onClick={onDocs}><Icon>⌕</Icon>Setup docs</button><button type="button" onClick={onDocs}><Icon>⌘</Icon>Install CLI</button><button type="button" onClick={onDocs}><Icon>➤</Icon>Connect device</button><button type="button" className="stop" onClick={onDocs}><Icon>■</Icon>Local-only</button></div>
  </section>;
}

function AgentWorkspace({ device, state, onDocs }: { device?: FlowDevice; state: ReturnType<typeof deviceState>; onDocs: () => void }) {
  const agent = device?.presence.health.agent ?? 'idle';
  const daemon = device?.presence.health.daemon ?? 'not running';
  return <section className="agent-workspace" aria-label="Synchronous local agent view">
    <aside className="glass-panel task-panel"><header><h1>Local Agent</h1><button type="button" onClick={onDocs}>Setup</button></header><div className="task-list"><div className="task-card is-selected queued"><i>1</i><span>Link a FLOW device<small>{device ? 'Linked — ready for local session controls' : 'Required before any local task can start'}</small></span><b>{device ? '✓' : '›'}</b></div><div className="task-card queued"><i>2</i><span>Start a local session<small>Run flow start with your goal in the terminal.</small></span><b>›</b></div><div className="task-card queued"><i>3</i><span>Run a synchronous task<small>Tasks execute locally with explicit permission.</small></span><b>›</b></div></div><blockquote>“The agent acts where<br />your work lives.”<small>— FLOW</small></blockquote></aside>
    <section className="agent-center"><div className="agent-title"><h1>Synchronous, local-first assistance</h1><p>No cloud worker, browser model, or fabricated activity.</p></div><figure className="flow-scene agent-scene" aria-label="FLOW local agent"><img src={agentScene} alt="" /><div className="scene-vignette" /><div className="agent-float-card agent-analysis"><strong><Icon>✦</Icon> Local agent status</strong><span>◉ Device: {state.label}</span><span>◉ Daemon: {daemon}</span><span>◉ Agent: {agent}</span><span>○ Model: {device?.presence.health.model ?? 'not loaded'}</span></div><div className="agent-float-card agent-files"><small>Local privacy boundary</small><span>↳ session data stays local</span><span>↳ no remote prompt relay</span><span>↳ explicit local approvals</span></div></figure><section className="agent-response glass-panel"><header><strong><Icon>✦</Icon> FLOW</strong><time>Live</time></header><p>{device ? 'Your linked device controls synchronous execution locally. Start a session in the terminal, then use the local FLOW command to create a bounded task with its permission policy.' : 'Connect a local FLOW device first. The web app will not start an agent on a remote server or pretend that one is running.'}</p><div><button type="button" onClick={onDocs}><Icon>▤</Icon>CLI install and connect<small>Open docs</small><b>›</b></button></div><div><button type="button" onClick={onDocs}><Icon>⌁</Icon>Local execution policy<small>Model-off by default</small><b>›</b></button></div></section></section>
    <aside className="agent-sidebar"><section className="glass-panel agent-status"><header><h2>Agent Status</h2><span><i className={state.tone === 'online' ? '' : 'is-stopped'} />{state.label}</span></header><Status label="Mode" value="Synchronous local" icon="◉" /><Status label="Device" value={device?.name ?? 'Not linked'} icon="▱" /><Status label="Daemon" value={daemon} icon="⌁" /><Status label="Model" value={device?.presence.health.model ?? 'Not loaded (0 MB)'} icon="▤" /><Status label="Limit" value="500 MB maximum" icon="♢" /></section><section className="glass-panel tools-panel"><header><h2>Safe local tools</h2><button type="button" onClick={onDocs}>Docs</button></header><div>{[['▤', 'Read File'], ['⌕', 'Search Code'], ['▶', 'Run Tests'], ['⌁', 'Run Command'], ['⌘', 'Git Status'], ['↗', 'Apply Patch']].map(([icon, label]) => <button type="button" key={label} onClick={onDocs}><Icon>{icon}</Icon>{label}</button>)}</div></section><section className="glass-panel approval-panel"><header><h2>Approvals</h2><button type="button" onClick={onDocs}>How it works</button></header><p className="approval-result">No remote approval queue. Local execution remains explicit and is recorded by your local daemon.</p></section><section className="glass-panel recent-panel"><header><h2>Account activity</h2><button type="button" onClick={onDocs}>Docs</button></header><p className="approval-result">{device ? `Device linked ${ago(device.created_at)}.` : 'No device has been linked.'}</p></section></aside>
  </section>;
}

function Status({ icon, label, value }: { icon: string; label: string; value: string }) { return <p className="status-row"><Icon>{icon}</Icon><span>{label}</span><b>{value}</b></p>; }
