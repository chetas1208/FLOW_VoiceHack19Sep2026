import type { FlowDevice } from '../../lib/account';
import { presenceLabel, pairingState, type PresenceState } from '../../lib/flowDeviceModel';
import { deviceTooltip, presenceTone, type AccountUser } from '../../lib/flowWorkspaceUi';
import { FlowIcon } from './FlowIcon';

export type WorkspaceTab = 'session' | 'agent' | 'docs' | 'showcase';

const NAV: { id: WorkspaceTab; icon: string; label: string; compact?: boolean }[] = [
  { id: 'session', icon: '◉', label: 'Session' },
  { id: 'agent', icon: '✦', label: 'Agent' },
  { id: 'docs', icon: '⌕', label: 'Docs' },
  { id: 'showcase', icon: '◇', label: 'Demo', compact: true },
];

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
  const headerPresence = pairing === 'paired' ? presenceLabel(presence) : pairing === 'revoked' ? 'Revoked' : 'Not linked';
  const headerTone = pairing === 'paired' ? presenceTone(presence) : 'offline';
  const now = new Date();

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
        <div className="device-status" title={deviceTooltip(device, pairing, presence)}>
          <i className={`device-dot ${headerTone}`} aria-hidden="true" />
          <span>{device?.name ?? 'No device'}<small>{headerPresence}</small></span>
        </div>
        <div className="flow-account-chip" title={account?.email}>
          <span>{account?.name?.split(' ')[0] ?? 'Account'}</span>
          <button
            type="button"
            onClick={() => void fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).finally(() => { window.location.href = '/auth'; })}
          >
            Sign out
          </button>
        </div>
        <time dateTime={now.toISOString()}>
          {now.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}
          <br />
          <strong>{now.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</strong>
        </time>
      </div>
    </header>
  );
}
