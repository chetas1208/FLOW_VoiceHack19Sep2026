import type { FlowDevice } from './account';

export type PairingState = 'unpaired' | 'pairing' | 'paired' | 'revoked';
export type PresenceState = 'online' | 'connecting' | 'offline' | 'degraded';

export type DeviceView = {
  device: FlowDevice | null;
  pairing: PairingState;
  presence: PresenceState;
  presenceLabel: string;
  pairingLabel: string;
  lastSeen: string | null;
};

export function pairingState(device: FlowDevice | null | undefined): PairingState {
  if (!device) return 'unpaired';
  if (device.revoked_at) return 'revoked';
  return 'paired';
}

export function mapPresence(device: FlowDevice | null | undefined, connectingHint = false): PresenceState {
  if (!device || device.revoked_at) return 'offline';
  if (connectingHint) return 'connecting';
  const raw = device.presence.state;
  if (raw === 'online') return 'online';
  if (raw === 'degraded') return 'degraded';
  return 'offline';
}

export function presenceLabel(state: PresenceState): string {
  switch (state) {
    case 'online': return 'Connected';
    case 'connecting': return 'Reconnecting';
    case 'degraded': return 'Degraded';
    default: return 'Offline';
  }
}

export function pickPrimaryDevice(items: FlowDevice[], preferredId: string | null): FlowDevice | null {
  const paired = items.filter((d) => !d.revoked_at);
  if (!paired.length) return items[0] ?? null;
  if (preferredId) {
    const match = paired.find((d) => d.id === preferredId);
    if (match) return match;
  }
  return paired.sort((a, b) => {
    const ta = new Date(b.last_seen_at ?? b.created_at).getTime();
    const tb = new Date(a.last_seen_at ?? a.created_at).getTime();
    return ta - tb;
  })[0];
}

export function ago(value: string | null): string {
  if (!value) return 'Not seen yet';
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export function modelStatus(raw: string | undefined): string {
  if (!raw || raw === 'not_loaded' || raw === 'unloaded') return 'Ready on demand';
  if (raw === 'not_installed') return 'Not installed';
  if (raw === 'loading') return 'Loading';
  if (raw === 'ready' || raw === 'loaded') return 'Loaded';
  if (raw === 'error') return 'Error';
  return raw.replace(/_/g, ' ');
}

export function daemonStatus(raw: string | undefined, presence: PresenceState): string {
  if (raw === 'running') return 'Running';
  if (presence === 'connecting') return 'Starting';
  return 'Stopped';
}
