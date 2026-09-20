import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import agentScene from '../assets/flow-agent-scene.png';
import sessionScene from '../assets/flow-session-scene.png';
import { DocsTabPanel } from '../components/flow/DocsTabPanel';
import { SystemStatusItem } from '../components/flow/SystemStatusItem';
import { useFlowDevices } from '../hooks/useFlowDevices';
import type { FlowDevice } from '../lib/account';
import {
  ago,
  daemonStatus,
  modelStatus,
  pairingState,
  presenceLabel,
  type PresenceState,
} from '../lib/flowDeviceModel';

type Tab = 'session' | 'agent' | 'docs';

function Icon({ children }: { children: string }) {
  return <span aria-hidden="true" className="flow-icon">{children}</span>;
}

function presenceTone(presence: PresenceState): 'online' | 'degraded' | 'offline' | 'connecting' {
  if (presence === 'online') return 'online';
  if (presence === 'connecting') return 'connecting';
  if (presence === 'degraded') return 'degraded';
  return 'offline';
}

export default function FlowDemoPage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get('tab');
  const tab: Tab = tabParam === 'agent' || tabParam === 'docs' ? tabParam : 'session';
  const { device, loading, error, presence } = useFlowDevices();
  const pairing = pairingState(device);
  const [privacyOpen, setPrivacyOpen] = useState(false);

  const setTab = useCallback((next: Tab) => {
    if (next === 'session') setParams({});
    else setParams({ tab: next });
  }, [setParams]);

  useEffect(() => {
    if (window.location.pathname.startsWith('/docs')) setParams({ tab: 'docs' }, { replace: true });
  }, [setParams]);

  const headerPresence = pairing === 'paired' ? presenceLabel(presence) : pairing === 'revoked' ? 'Revoked' : 'Not linked';
  const headerTone = pairing === 'paired' ? presenceTone(presence) : 'offline';

  return (
    <main className="flow-demo" aria-label="FLOW workspace">
      <div className="flow-atmosphere" aria-hidden="true" />
      <div className={`flow-shell app-shell ${tab === 'agent' ? 'is-agent-view' : ''} ${tab === 'docs' ? 'is-docs-view' : ''}`}>
        <header className="flow-header">
          <div className="flow-brand" aria-label="FLOW"><strong>FLOW</strong></div>
          <nav className="view-tabs" role="tablist" aria-label="FLOW workspace view">
            {(['session', 'agent', 'docs'] as const).map((name) => (
              <button key={name} type="button" role="tab" aria-selected={tab === name} className={tab === name ? 'is-active' : ''} onClick={() => setTab(name)}>
                <Icon>{name === 'session' ? '◉' : name === 'agent' ? '✦' : '⌕'}</Icon>
                {name.charAt(0).toUpperCase() + name.slice(1)}
              </button>
            ))}
          </nav>
          <div className="flow-header-actions">
            <div className="device-status" title={deviceTooltip(device, pairing, presence)}>
              <i className={`device-dot ${headerTone}`} aria-hidden="true" />
              <span>{device?.name ?? 'No device'}<small>{headerPresence}</small></span>
            </div>
            <Link to="/devices" className="flow-account-link">Account</Link>
          </div>
        </header>

        <div className="flow-main">
          {tab === 'session' && <SessionTab device={device} pairing={pairing} presence={presence} loading={loading} error={error} onDocs={() => setTab('docs')} />}
          {tab === 'agent' && <AgentTab device={device} pairing={pairing} presence={presence} onDocs={() => setTab('docs')} />}
          {tab === 'docs' && <DocsTabPanel />}
        </div>

        <footer className="flow-footer">
          <button type="button" className="privacy-chip" onClick={() => setPrivacyOpen((v) => !v)}>🔒 Work data stays on your device</button>
          {privacyOpen && <p className="privacy-pop">Session content, code, and observations remain on your linked machine. The account stores identity and device metadata only.</p>}
        </footer>
      </div>
    </main>
  );
}

function deviceTooltip(device: FlowDevice | null | undefined, pairing: ReturnType<typeof pairingState>, presence: PresenceState) {
  if (pairing !== 'paired' || !device) return 'Link a device with flow login.';
  if (presence === 'online') return `Connected directly to ${device.name}. Heartbeat ${ago(device.presence.last_heartbeat_at)}.`;
  return `${device.name} is still linked. FLOW reconnects automatically when the daemon is available.`;
}

function SessionTab({ device, pairing, presence, loading, error, onDocs }: {
  device: FlowDevice | null; pairing: ReturnType<typeof pairingState>; presence: PresenceState; loading: boolean; error: string; onDocs: () => void;
}) {
  const health = device?.presence.health ?? {};
  const unpaired = pairing === 'unpaired' || pairing === 'revoked';

  if (unpaired) {
    return (
      <section className="session-compact" aria-label="Connect device">
        <div className="session-compact-card glass-panel">
          <h1>Device not linked</h1>
          <p>Install the CLI, then run <code>flow login</code> and approve this computer in the browser.</p>
          <button type="button" className="primary-action" onClick={onDocs}>Open Docs</button>
        </div>
      </section>
    );
  }

  const pairedOffline = presence !== 'online';
  if (pairedOffline) {
    return (
      <section className="session-layout session-offline" aria-label="Device offline">
        <aside className="glass-panel session-side">
          <h2>{device!.name}</h2>
          <p className="presence-line"><span className={`device-dot ${presenceTone(presence)}`} /> {presenceLabel(presence)}</p>
          <p className="muted">Still linked to your FLOW account</p>
          <p className="muted">Last seen {ago(device!.last_seen_at ?? device!.presence.last_heartbeat_at)}</p>
          <SystemStatusItem label="Account" value="Connected" tone="ok" />
          <SystemStatusItem label="Device" value="Linked" tone="ok" />
          <SystemStatusItem label="Daemon" value={daemonStatus(health.daemon, presence)} tone="idle" />
          <SystemStatusItem label="Model" value={modelStatus(health.model)} tone="warn" />
        </aside>
        <section className="session-center-compact glass-panel">
          <h1>FLOW will reconnect automatically</h1>
          <p>When the local daemon is running, this page resumes live session data without pairing again.</p>
          <div className="docs-command"><code>flow daemon start</code></div>
          <button type="button" className="secondary-action" onClick={onDocs}>Troubleshoot in Docs</button>
        </section>
      </section>
    );
  }

  return (
    <section className="session-layout session-ready" aria-label="Session workspace">
      <aside className="glass-panel session-side">
        <SystemStatusItem label="Account" value="Connected" tone="ok" />
        <SystemStatusItem label="Device" value="Linked" tone="ok" />
        <SystemStatusItem label="Daemon" value={daemonStatus(health.daemon, presence)} tone={health.daemon === 'running' ? 'ok' : 'idle'} />
        <SystemStatusItem label="Model" value={modelStatus(health.model)} tone="warn" />
        <SystemStatusItem label="Voice" value="Ready on demand" tone="warn" />
      </aside>
      <section className="session-center-compact">
        <h1>Ready when you are.</h1>
        <p className="muted">{loading ? 'Checking device…' : 'Start from the CLI or use the button when local start is wired.'}</p>
        <label className="goal-field"><span className="sr-only">Session goal</span><input type="text" placeholder="Finish authentication and pass all tests" readOnly /></label>
        <button type="button" className="primary-action" disabled>Start Session</button>
        <p className="cli-hint"><code>flow start &quot;your goal&quot;</code></p>
        {error && <p className="live-error">{error}</p>}
        <figure className="flow-scene session-scene compact-scene" aria-hidden="true"><img src={sessionScene} alt="" /><div className="scene-vignette" /></figure>
      </section>
      <aside className="glass-panel session-side">
        <h2>Device</h2>
        <p><strong>{device!.name}</strong></p>
        <p className="muted">{device!.os} · FLOW {device!.flow_version}</p>
        <p className="presence-line"><span className="device-dot online" /> Connected</p>
        <p className="section-label">Next step</p>
        <p>Run <code>flow start</code> with a goal on your computer.</p>
      </aside>
    </section>
  );
}

function AgentTab({ device, pairing, presence, onDocs }: {
  device: FlowDevice | null; pairing: ReturnType<typeof pairingState>; presence: PresenceState; onDocs: () => void;
}) {
  const health = device?.presence.health ?? {};
  const unpaired = pairing === 'unpaired' || pairing === 'revoked';

  return (
    <section className="agent-layout" aria-label="Agent workspace">
      <aside className="glass-panel agent-queue">
        <header><h1>Task queue</h1></header>
        {unpaired ? <p className="muted">Link a device to run local agent tasks.</p> : (
          <div className="task-list">
            <div className="task-card is-selected"><i>1</i><span>Device linked<small>Pairing persists across offline periods</small></span><b>✓</b></div>
            <div className="task-card queued"><i>2</i><span>Start a session<small><code>flow start &quot;goal&quot;</code></small></span><b>›</b></div>
          </div>
        )}
      </aside>
      <section className="agent-center agent-center-compact">
        <h1>Local agent</h1>
        <p className="muted">Synchronous execution on your machine — no cloud worker.</p>
        <figure className="flow-scene agent-scene compact-scene"><img src={agentScene} alt="" /><div className="scene-vignette" /></figure>
        <div className="glass-panel agent-response compact">
          <p>{unpaired ? 'Connect a device first.' : presence === 'online' ? 'Agent controls appear when a local session is active.' : `${device?.name ?? 'Device'} is offline but still linked.`}</p>
          <button type="button" onClick={onDocs}>Docs</button>
        </div>
      </section>
      <aside className="agent-sidebar compact">
        <SystemStatusItem label="Device" value={device?.name ?? 'Not linked'} tone={pairing === 'paired' ? 'ok' : 'idle'} />
        <SystemStatusItem label="Presence" value={presenceLabel(presence)} tone={presence === 'online' ? 'ok' : 'idle'} />
        <SystemStatusItem label="Daemon" value={daemonStatus(health.daemon, presence)} tone="idle" />
        <SystemStatusItem label="Agent" value={health.agent ?? 'idle'} tone="neutral" />
        <SystemStatusItem label="Model" value={modelStatus(health.model)} tone="warn" />
      </aside>
    </section>
  );
}
