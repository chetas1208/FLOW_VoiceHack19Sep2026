// Framework-free WebSocket client for the viewer channels (/v1/ws/sessions/{id}, /v1/ws/user).
//  - the token is never put in the URL: auth is the first frame `{type:"auth", token, last_sequence}`;
//  - exponential reconnect (1s..30s, jittered) that re-reads last_sequence and the freshest token every attempt;
//  - close code 4401 => refresh the token and reconnect immediately;
//  - idle watchdog: any frame (including the server's `ping`) proves liveness; silence reconnects.

export type SocketStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'unauthorized';

export interface WebSocketLike {
  onopen: ((ev?: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason?: string }) => void) | null;
  onerror: ((ev?: unknown) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

export interface LiveSocketOptions {
  url: () => string;
  getToken: () => string | null;
  /** Obtain a fresh token (dev re-login, OIDC refresh). Resolve null when the user must sign in again. */
  refreshToken: () => Promise<string | null>;
  /** Extra fields for the auth frame, evaluated on every connect (e.g. last_sequence). */
  authExtras?: () => Record<string, unknown>;
  onFrame: (frame: Record<string, any>) => void;
  onStatus?: (status: SocketStatus) => void;
  createSocket?: (url: string) => WebSocketLike;
  minDelayMs?: number;
  maxDelayMs?: number;
  idleTimeoutMs?: number;
  authTimeoutMs?: number;
  maxAuthRetries?: number;
  random?: () => number;
}

export const CLOSE_TOKEN_EXPIRED = 4401;
const FATAL_CODES = new Set([4403, 4404, 1008]);

export class LiveSocket {
  private ws: WebSocketLike | null = null;
  private status: SocketStatus = 'idle';
  private attempt = 0;
  private authRetries = 0;
  private stopped = true;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private authTimer: ReturnType<typeof setTimeout> | null = null;
  private generation = 0;
  private readonly o: Required<Pick<LiveSocketOptions, 'minDelayMs' | 'maxDelayMs' | 'idleTimeoutMs' | 'authTimeoutMs' | 'maxAuthRetries'>> & LiveSocketOptions;

  constructor(options: LiveSocketOptions) {
    this.o = { minDelayMs: 1000, maxDelayMs: 30_000, idleTimeoutMs: 75_000, authTimeoutMs: 10_000, maxAuthRetries: 2, ...options };
  }

  get state(): SocketStatus { return this.status; }
  get reconnectAttempts(): number { return this.attempt; }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.attempt = 0;
    this.authRetries = 0;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.generation++;
    this.clearTimers();
    const ws = this.ws;
    this.ws = null;
    if (ws) { detach(ws); try { ws.close(1000, 'client stop'); } catch { /* already closed */ } }
    this.setStatus('idle');
  }

  /** Called on `online` / tab-visible: skip the backoff wait if we are currently between attempts. */
  nudge(): void {
    if (this.stopped || this.status !== 'reconnecting' || !this.retryTimer) return;
    clearTimeout(this.retryTimer);
    this.retryTimer = null;
    void this.connect();
  }

  private setStatus(s: SocketStatus) {
    if (this.status === s) return;
    this.status = s;
    this.o.onStatus?.(s);
  }

  private clearTimers() {
    for (const t of [this.retryTimer, this.idleTimer, this.authTimer]) if (t) clearTimeout(t);
    this.retryTimer = this.idleTimer = this.authTimer = null;
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    const gen = ++this.generation;
    this.setStatus(this.attempt === 0 && this.status !== 'reconnecting' ? 'connecting' : 'reconnecting');
    let token = this.o.getToken();
    if (!token) {
      token = await this.o.refreshToken().catch(() => null);
      if (gen !== this.generation || this.stopped) return;
      if (!token) return this.giveUp();
    }
    let ws: WebSocketLike;
    try {
      ws = (this.o.createSocket ?? ((u) => new WebSocket(u) as unknown as WebSocketLike))(this.o.url());
    } catch {
      return this.scheduleRetry();
    }
    this.ws = ws;
    const sending = token;
    ws.onopen = () => {
      if (gen !== this.generation) return;
      try {
        ws.send(JSON.stringify({ type: 'auth', token: sending, ...(this.o.authExtras?.() ?? {}) }));
      } catch { /* close handler will retry */ }
      this.authTimer = setTimeout(() => { if (gen === this.generation) this.dropAndRetry(ws); }, this.o.authTimeoutMs);
      this.armIdle(ws, gen);
    };
    ws.onmessage = (ev) => {
      if (gen !== this.generation) return;
      this.armIdle(ws, gen);
      let frame: Record<string, any>;
      try { frame = JSON.parse(String(ev.data)); } catch { return; }
      if (!frame || typeof frame !== 'object') return;
      if (frame.type === 'ready') {
        if (this.authTimer) { clearTimeout(this.authTimer); this.authTimer = null; }
        this.attempt = 0;
        this.authRetries = 0;
        this.setStatus('live');
      }
      this.o.onFrame(frame);
    };
    ws.onerror = () => { /* onclose always follows */ };
    ws.onclose = (ev) => {
      if (gen !== this.generation) return;
      this.ws = null;
      this.clearTimers();
      if (this.stopped) return;
      void this.handleClose(ev.code);
    };
  }

  private armIdle(ws: WebSocketLike, gen: number) {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => { if (gen === this.generation) this.dropAndRetry(ws); }, this.o.idleTimeoutMs);
  }

  private dropAndRetry(ws: WebSocketLike) {
    detach(ws);
    try { ws.close(4000, 'idle'); } catch { /* ignore */ }
    this.ws = null;
    this.generation++;
    this.clearTimers();
    if (!this.stopped) this.scheduleRetry();
  }

  private async handleClose(code: number): Promise<void> {
    if (FATAL_CODES.has(code)) return this.giveUp();
    if (code === CLOSE_TOKEN_EXPIRED) {
      if (this.authRetries >= this.o.maxAuthRetries) return this.giveUp();
      this.authRetries++;
      const gen = this.generation;
      const token = await this.o.refreshToken().catch(() => null);
      if (this.stopped || gen !== this.generation) return;
      if (!token) return this.giveUp();
      this.setStatus('reconnecting');
      void this.connect(); // immediate: a fresh token needs no backoff
      return;
    }
    this.scheduleRetry();
  }

  private giveUp() {
    this.stopped = true;
    this.clearTimers();
    this.setStatus('unauthorized');
  }

  private scheduleRetry() {
    if (this.stopped) return;
    this.setStatus('reconnecting');
    const base = Math.min(this.o.maxDelayMs, this.o.minDelayMs * 2 ** this.attempt);
    const jitter = 1 + ((this.o.random ?? Math.random)() - 0.5) * 0.4;
    this.attempt++;
    this.retryTimer = setTimeout(() => { this.retryTimer = null; void this.connect(); }, Math.round(base * jitter));
  }
}

function detach(ws: WebSocketLike) {
  ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
}

export function toWsUrl(apiUrl: string, path: string): string {
  const base = apiUrl.replace(/\/+$/, '');
  return base.replace(/^http/i, 'ws') + path;
}
