import type { FlowDevice } from './account';
import { ago, pairingState, type PresenceState } from './flowDeviceModel';

export type AccountUser = { id: string; email: string; name: string };

export function presenceTone(presence: PresenceState): 'online' | 'degraded' | 'offline' | 'connecting' {
  if (presence === 'online') return 'online';
  if (presence === 'connecting') return 'connecting';
  if (presence === 'degraded') return 'degraded';
  return 'offline';
}

export function deviceTooltip(
  device: FlowDevice | null | undefined,
  pairing: ReturnType<typeof pairingState>,
  presence: PresenceState,
) {
  if (pairing !== 'paired' || !device) return 'Link a device with flow login.';
  if (presence === 'online') return `Connected directly to ${device.name}. Heartbeat ${ago(device.presence.last_heartbeat_at)}.`;
  return `${device.name} is still linked. FLOW reconnects automatically when the daemon is available.`;
}
