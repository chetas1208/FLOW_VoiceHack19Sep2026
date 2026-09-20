export type FlowDevice = {
  id: string;
  name: string;
  os: string;
  architecture: string;
  flow_version: string;
  created_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
  presence: {
    state: 'online' | 'degraded' | 'offline';
    last_heartbeat_at: string | null;
    health: Record<string, string>;
    active_sessions?: string[];
  };
};

export class AccountApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

async function accountRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: 'same-origin',
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new AccountApiError(response.status, body.message || 'FLOW could not complete that request.');
  return body as T;
}

export const accountApi = {
  devices: () => accountRequest<{ items: FlowDevice[] }>('/api/account/devices'),
  cliRequest: (id: string) => accountRequest<CliRequest>(`/api/account/cli-requests/${encodeURIComponent(id)}`),
  approveCliRequest: (id: string, state: string) => accountRequest<{ status: string }>(`/api/account/cli-requests/${encodeURIComponent(id)}/approve`, { method: 'POST', body: JSON.stringify({ state }) }),
  denyCliRequest: (id: string) => accountRequest<{ status: string }>(`/api/account/cli-requests/${encodeURIComponent(id)}/deny`, { method: 'POST', body: JSON.stringify({}) }),
};

export type CliRequest = {
  request_id: string;
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'consumed';
  device: { name: string; os: string; architecture: string; flow_version: string };
  expires_at: string;
};
