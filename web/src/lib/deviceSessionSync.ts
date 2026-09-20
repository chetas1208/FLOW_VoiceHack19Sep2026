import type { FlowDevice } from './account';
import type { PresenceState } from './flowDeviceModel';

export type SyncedSession = {
  id: string | null;
  goal: string | null;
  status: string | null;
  live: boolean;
};

export function syncedSessionFromDevice(device: FlowDevice | null, presence: PresenceState): SyncedSession {
  const health = device?.presence.health ?? {};
  const ids = device?.presence.active_sessions ?? [];
  const id = (typeof health.session_id === 'string' && health.session_id) || ids[0] || null;
  const goal = typeof health.session_goal === 'string' && health.session_goal.trim() ? health.session_goal.trim() : null;
  const status = typeof health.session_status === 'string' ? health.session_status : null;
  const daemonUp = health.daemon === 'running';
  const live = presence === 'online' && daemonUp && (!!id || status === 'active' || status === 'paused');
  return { id, goal, status, live };
}
