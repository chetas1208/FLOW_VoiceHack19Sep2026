import { useState, type FormEvent } from 'react';
import type { FlowDevice } from '../../lib/account';
import { daemonStatus, modelStatus, pairingState, presenceLabel, type PresenceState } from '../../lib/flowDeviceModel';
import { AgentHeroScene } from './CockpitScenes';
import { FlowIcon } from './FlowIcon';

const TOOLS = [
  ['▤', 'Read File'],
  ['⌕', 'Search Code'],
  ['▶', 'Run Tests'],
  ['⌁', 'Run Command'],
  ['⌘', 'Git Status'],
  ['↗', 'Apply Patch'],
] as const;

function StatusRow({ icon, label, value }: { icon: string; label: string; value: string }) {
  return <p className="status-row"><FlowIcon>{icon}</FlowIcon><span>{label}</span><b>{value}</b></p>;
}

export function AgentWorkspace({
  device,
  pairing,
  presence,
  onDocs,
}: {
  device: FlowDevice | null;
  pairing: ReturnType<typeof pairingState>;
  presence: PresenceState;
  onDocs: () => void;
}) {
  const health = device?.presence.health ?? {};
  const unpaired = pairing === 'unpaired' || pairing === 'revoked';
  const online = pairing === 'paired' && presence === 'online';
  const [prompt, setPrompt] = useState('');

  const agentLine = unpaired
    ? 'Connect a device with flow login to run the local agent.'
    : !online
      ? `${device?.name ?? 'Your device'} is still linked. Start the daemon to resume agent work.`
      : 'Delegate from an active session or ask FLOW — execution stays on your machine.';

  const submitPrompt = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPrompt('');
  };

  return (
    <section className="agent-workspace" aria-label="Agent workspace">
      <aside className="glass-panel task-panel">
        <header><h1>Agent Tasks</h1><button type="button" disabled={unpaired}>＋ New Task</button></header>
        {unpaired ? (
          <p className="connect-banner" style={{ marginTop: 12 }}>Link a device to queue local tasks. <button type="button" className="secondary-action" style={{ marginTop: 8 }} onClick={onDocs}>Docs</button></p>
        ) : (
          <div className="task-list" style={{ marginTop: 16 }}>
            <div className="task-card queued"><i aria-hidden="true">◌</i><span>Start a session<small><code>flow start &quot;goal&quot;</code></small></span><b>›</b></div>
            <div className="task-card done"><i aria-hidden="true">✓</i><span>Device linked<small>Pairing persists across offline periods</small></span><b>✓</b></div>
          </div>
        )}
        <blockquote>“Delegate the routine.<br />Focus on what matters.”<small>— FLOW</small></blockquote>
      </aside>

      <section className="agent-center">
        <div className="agent-title">
          <h1>Your AI pair programmer and productivity partner</h1>
          <p>Understand. Plan. Execute. Verify. Together.</p>
        </div>
        <AgentHeroScene activity={online ? 'Ready on device' : 'Standby'} />
        <section className="agent-response glass-panel">
          <header><strong><FlowIcon>✦</FlowIcon> FLOW</strong><time>{new Date().toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</time></header>
          <p>{agentLine}</p>
        </section>
        <form className="agent-composer glass-panel" onSubmit={submitPrompt}>
          <label className="sr-only" htmlFor="flow-agent-prompt">Ask FLOW anything</label>
          <input id="flow-agent-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ask FLOW anything..." disabled={!online} />
          <button type="submit" aria-label="Send prompt" disabled={!online}><FlowIcon>➤</FlowIcon></button>
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
          <header><h2>Available Tools</h2></header>
          <div>{TOOLS.map(([icon, label]) => (
            <button type="button" key={label} disabled={!online}><FlowIcon>{icon}</FlowIcon>{label}</button>
          ))}</div>
        </section>
        <section className="glass-panel approval-panel">
          <header><h2>Pending Approval <b>0</b></h2></header>
          <p className="panel-empty">Approvals for file changes appear here during agent work.</p>
        </section>
        <section className="glass-panel recent-panel">
          <header><h2>Recent Activity</h2></header>
          <p className="panel-empty">Recent agent actions stream from your device.</p>
        </section>
      </aside>
    </section>
  );
}
