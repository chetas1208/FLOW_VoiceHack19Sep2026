import { api, ApiError } from '../lib/api';
import { COMMAND_LABEL, newCommandId } from '../lib/format';
import type { CommandType, SessionCommand } from '../lib/types';
import { store } from './store';
import { toast } from './toasts';

export interface CommandTarget { sessionId?: string; deviceId?: string }

/** Issue a remote command. The returned command keeps updating in the store via viewer-socket `command` frames. */
export async function sendCommand(type: CommandType, payload: Record<string, unknown>, target: CommandTarget, opts: { quiet?: boolean } = {}): Promise<SessionCommand | null> {
  const command_id = newCommandId();
  const body = { command_id, type, payload, source: 'web' as const, ...(target.sessionId ? { session_id: target.sessionId } : {}), ...(target.deviceId ? { device_id: target.deviceId } : {}) };
  for (let attempt = 0; ; attempt++) {
    try {
      const cmd = await api.sendCommand(body); // same command_id on retry: the API returns the existing command
      store.dispatch({ type: 'command/local', command: { ...({ payload, source: 'web', created_at: new Date().toISOString(), device_id: target.deviceId ?? '', session_id: target.sessionId, type } as Partial<SessionCommand>), ...cmd } });
      return cmd;
    } catch (e) {
      const err = e as ApiError;
      if (err.code === 'network_error' && attempt < 2) { await new Promise((r) => setTimeout(r, 800 * (attempt + 1))); continue; }
      if (!opts.quiet) toast(commandError(type, err), 'error');
      return null;
    }
  }
}

export function commandError(type: CommandType, err: ApiError): string {
  const label = COMMAND_LABEL[type] ?? type;
  if (err.code === 'device_offline') return `${label} was not sent. The device is offline, and only Pause, Stop and Mute can be queued while it is away.`;
  if (err.code === 'rate_limited') return `${label} was not sent. Too many requests. Try again in ${err.retryAfter ?? 'a few'} seconds.`;
  if (err.code === 'command_expired') return `${label} expired before it could be delivered. Send it again.`;
  if (err.code === 'network_error') return `${label} was not sent. ${err.message}`;
  return `${label} failed. ${err.message}`;
}
