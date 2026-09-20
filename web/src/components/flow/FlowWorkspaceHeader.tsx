import { useEffect, useRef, useState } from 'react';
import type { FlowDevice } from '../../lib/account';
import { ago, daemonStatus, modelStatus, presenceLabel, pairingState, type PresenceState } from '../../lib/flowDeviceModel';
import { presenceTone, type AccountUser } from '../../lib/flowWorkspaceUi';
import { FlowIcon } from './FlowIcon';

export type WorkspaceTab = 'session' | 'agent' | 'docs' | 'showcase';

const NAV: { id: WorkspaceTab; icon: string; label: string; compact?: boolean }[] = [
  { id: 'session', icon: '◉', label: 'Session' },
  { id: 'agent', icon: '✦', label: 'Agent' },
  { id: 'docs', icon: '⌕', label: 'Docs' },
  { id: 'showcase', icon: '◇', label: 'Demo', compact: true },
];

function initials(name?: string, email?: string): string {
  const n = name?.trim();
  if (n) {
    const parts = n.split(/\s+/);
    if (parts.length >= 2) return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase();
    return n.slice(0, 2).toUpperCase();
  }
  return (email?.[0] ?? 'A').toUpperCase();
}

export function FlowWorkspaceHeader({
  tab,
  onTabChange,
  device,
  pairing,
  presence,
  account,
}: {
  tab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  device: FlowDevice | null;
  pairing: ReturnType<typeof pairingState>;
  presence: PresenceState;
  account?: AccountUser;
}) {
  const headerTone = pairing === 'paired' ? presenceTone(presence) : 'offline';
  const health = device?.presence.health ?? {};
  const [deviceOpen, setDeviceOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const deviceRef = useRef<HTMLDivElement>(null);
  const accountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      const t = e.target as Node;
      if (deviceRef.current && !deviceRef.current.contains(t)) setDeviceOpen(false);
      if (accountRef.current && !accountRef.current.contains(t)) setAccountOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const deviceName = device?.name ?? 'No device';
  const paired = pairing === 'paired';
  const lastBeat = device?.presence.last_heartbeat_at ?? device?.last_seen_at;

  return (
    <header className="flow-header">
      <div className="flow-brand" aria-label="FLOW">
        <strong>FLOW</strong>
        <span>FOCUS TODAY. A BETTER TOMORROW.</span>
      </div>
      <nav className="view-tabs" role="tablist" aria-label="FLOW workspace view">
        {NAV.map(({ id, icon, label, compact }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`${tab === id ? 'is-active' : ''}${compact ? ' tab-compact' : ''}`}
            onClick={() => onTabChange(id)}
          >
            <FlowIcon>{icon}</FlowIcon>
            {label}
          </button>
        ))}
      </nav>
      <div className="flow-header-actions">
        <div className="header-popover-anchor" ref={deviceRef}>
          <button
            type="button"
            className="device-chip"
            aria-expanded={deviceOpen}
            onClick={() => { setDeviceOpen((v) => !v); setAccountOpen(false); }}
          >
            <i className={`device-dot ${headerTone}`} aria-hidden="true" />
            {deviceName}
          </button>
          {deviceOpen && (
            <div className="header-popover glass-panel" role="dialog" aria-label="Device">
              <h3>Device</h3>
              <dl className="device-popover-list">
                <div><dt>Paired</dt><dd>{paired ? 'Yes' : 'No'}</dd></div>
                <div><dt>Connected</dt><dd>{paired ? presenceLabel(presence) : '—'}</dd></div>
                <div><dt>Daemon</dt><dd>{paired ? daemonStatus(health.daemon, presence) : '—'}</dd></div>
                <div><dt>Model</dt><dd>{paired ? modelStatus(health.model) : '—'}</dd></div>
                <div><dt>Last heartbeat</dt><dd>{paired ? ago(lastBeat ?? null) : '—'}</dd></div>
              </dl>
            </div>
          )}
        </div>
        <div className="header-popover-anchor" ref={accountRef}>
          <button
            type="button"
            className="account-avatar"
            aria-expanded={accountOpen}
            aria-label="Account menu"
            onClick={() => { setAccountOpen((v) => !v); setDeviceOpen(false); }}
          >
            {initials(account?.name, account?.email)}
          </button>
          {accountOpen && (
            <div className="header-popover glass-panel account-popover" role="menu">
              <p className="account-popover-id"><strong>{account?.name ?? 'Account'}</strong><small>{account?.email ?? ''}</small></p>
              <button type="button" role="menuitem" onClick={() => { setAccountOpen(false); window.location.href = '/auth'; }}>Account</button>
              <button type="button" role="menuitem" onClick={() => setAccountOpen(false)}>Devices</button>
              <button
                type="button"
                role="menuitem"
                onClick={() => void fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).finally(() => { window.location.href = '/auth'; })}
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
