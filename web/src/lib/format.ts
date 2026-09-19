export const pct = (v: number | null | undefined) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v * 100) : null);

export function duration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, '0'), ss = String(sec).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

export function humanDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60), r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never';
  const diff = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (diff < 10) return 'just now';
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / 86400)} d ago`;
}

export const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
export const dateTime = (iso: string) => new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

export function untilLabel(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null;
  const left = (new Date(iso).getTime() - now) / 1000;
  if (left <= 0) return null;
  return left < 90 ? `${Math.ceil(left)}s` : `${Math.ceil(left / 60)} min`;
}

export const STATUS_LABEL: Record<string, string> = {
  starting: 'Starting', active: 'Active', paused: 'Paused', waiting_for_user: 'Waiting for you',
  executing_delegated_task: 'Agent working', recovering: 'Recovering', completed: 'Completed', failed: 'Failed', offline: 'Offline',
};

export const COMMAND_LABEL: Record<string, string> = {
  START: 'Start session', PAUSE: 'Pause', RESUME: 'Resume', STOP: 'Stop', UPDATE_GOAL: 'Change goal', REQUEST_STATUS: 'Status check',
  MUTE_VOICE: 'Mute voice', UNMUTE_VOICE: 'Unmute voice', REQUEST_SUMMARY: 'Summary', ADD_TASK: 'Delegate task', CANCEL_TASK: 'Cancel task',
  APPROVE_ACTION: 'Approve', DENY_ACTION: 'Deny', EXECUTE_RECOMMENDATION: 'Do recommendation', ASK: 'Ask FLOW',
  DISMISS_RECOMMENDATION: 'Dismiss', FEEDBACK_RECOMMENDATION: 'Feedback', SET_PERMISSION_POLICY: 'Permission policy', UPDATE_SUBTASKS: 'Update subtasks',
};

export const POLICY_LABEL: Record<string, { name: string; hint: string }> = {
  manual: { name: 'Ask me every time', hint: 'The agent pauses for your approval before any action that changes something.' },
  safe_auto: { name: 'Safe actions automatic', hint: 'Reading and safe commands run on their own. Writes, network and destructive steps still ask.' },
  read_only: { name: 'Read only', hint: 'The agent can look around and report back, but cannot change anything.' },
};

export const LEVEL_LABEL: Record<string, string> = {
  read_only: 'Read only', safe_execute: 'Safe commands', write_project: 'Edits project files', external_network: 'Uses the network', destructive: 'Destructive',
};

export function newCommandId(): string {
  const b = crypto.getRandomValues(new Uint8Array(12));
  return 'cmd_' + Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
}
