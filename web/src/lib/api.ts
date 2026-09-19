import { auth } from '../auth/auth';
import { config } from '../config';
import type {
  ActionApproval, CliAuthRequest, Device, Entity, FlowEvent, LiveView, Page, SessionCommand, SessionOut, SessionReport,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string, public retryAfter?: number) {
    super(message);
  }
}

interface Options { method?: string; body?: unknown; query?: Record<string, string | number | undefined | null>; signal?: AbortSignal; retryAuth?: boolean }

const TIMEOUT_MS = 20_000;

export async function request<T>(path: string, opts: Options = {}): Promise<T> {
  const url = new URL(`${config.apiUrl}/v1${path}`);
  for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  const token = auth.getToken() ?? (await auth.refresh());
  if (!token) { auth.signOut('Your session expired. Sign in again.'); throw new ApiError(401, 'unauthorized', 'You are signed out.'); }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  opts.signal?.addEventListener('abort', () => ctl.abort(), { once: true });
  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? 'GET', signal: ctl.signal, credentials: 'omit',
      headers: { Authorization: `Bearer ${token}`, ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    if (opts.signal?.aborted) throw e;
    throw new ApiError(0, 'network_error', 'Cannot reach FLOW. Check your connection and try again.');
  } finally { clearTimeout(timer); }

  if (res.status === 401 && opts.retryAuth !== false) {
    const fresh = await auth.refresh();
    if (fresh) return request<T>(path, { ...opts, retryAuth: false });
    auth.signOut('Your session expired. Sign in again.');
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let json: any = undefined;
  try { json = text ? JSON.parse(text) : undefined; } catch { /* non-JSON error page */ }
  if (!res.ok) {
    throw new ApiError(res.status, json?.error ?? `http_${res.status}`, json?.message ?? `Request failed (${res.status}).`, json?.request_id,
      Number(res.headers.get('Retry-After')) || undefined);
  }
  return json as T;
}

export const api = {
  me: () => request<{ id: string; email: string; principal: string }>('/me'),
  devices: () => request<{ items: Device[] }>('/devices'),
  revokeDevice: (id: string) => request<void>(`/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  sessions: (q: { status?: string; device_id?: string; limit?: number; cursor?: string | null }) => request<Page<SessionOut>>('/sessions', { query: q }),
  live: (id: string) => request<LiveView>(`/sessions/${encodeURIComponent(id)}/live`),
  events: (id: string, after: number, limit = 300) => request<Page<FlowEvent> | { items: FlowEvent[] }>(`/sessions/${encodeURIComponent(id)}/events`, { query: { after, limit } }),
  entities: (id: string, kind: string, limit = 50) => request<{ items: Entity[] }>(`/sessions/${encodeURIComponent(id)}/entities`, { query: { kind, limit } }),
  report: (id: string) => request<SessionReport>(`/sessions/${encodeURIComponent(id)}/report`),
  sessionCommands: (id: string, limit = 30) => request<{ items: SessionCommand[] }>(`/sessions/${encodeURIComponent(id)}/commands`, { query: { limit } }),
  command: (id: string) => request<SessionCommand>(`/commands/${encodeURIComponent(id)}`),
  approvals: () => request<{ items: ActionApproval[] }>('/approvals', { query: { status: 'pending' } }),
  sendCommand: (body: { command_id: string; type: string; session_id?: string; device_id?: string; payload: Record<string, unknown>; source: 'web' }) =>
    request<SessionCommand & { session_id?: string }>('/commands', { method: 'POST', body }),
  cliRequest: (id: string) => request<CliAuthRequest>(`/cli/auth/requests/${encodeURIComponent(id)}`),
  cliApprove: (id: string) => request<{ status: string }>(`/cli/auth/requests/${encodeURIComponent(id)}/approve`, { method: 'POST', body: {} }),
  cliDeny: (id: string) => request<{ status: string }>(`/cli/auth/requests/${encodeURIComponent(id)}/deny`, { method: 'POST', body: {} }),
};

export async function devLogin(email: string): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${config.apiUrl}/v1/dev/login`, { method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) });
  } catch { throw new ApiError(0, 'network_error', `Cannot reach the FLOW API at ${config.apiUrl}.`); }
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, json.error ?? 'error', json.message ?? 'Sign-in failed.');
  return json.access_token as string;
}
