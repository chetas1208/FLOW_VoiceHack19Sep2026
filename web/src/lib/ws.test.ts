import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveSocket, type LiveSocketOptions, type SocketStatus, type WebSocketLike } from './ws';
import { initialState, reducer, type AppState } from '../store/reducer';

class FakeSocket implements WebSocketLike {
  static all: FakeSocket[] = [];
  onopen: WebSocketLike['onopen'] = null;
  onmessage: WebSocketLike['onmessage'] = null;
  onclose: WebSocketLike['onclose'] = null;
  onerror: WebSocketLike['onerror'] = null;
  sent: any[] = [];
  closed = false;
  constructor(public url: string) { FakeSocket.all.push(this); }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.closed = true; }
  open() { this.onopen?.(); }
  message(frame: unknown) { this.onmessage?.({ data: JSON.stringify(frame) }); }
  drop(code = 1006) { this.onclose?.({ code }); }
}
const last = () => FakeSocket.all[FakeSocket.all.length - 1]!;

function make(overrides: Partial<LiveSocketOptions> = {}) {
  const statuses: SocketStatus[] = [];
  const frames: any[] = [];
  let seq = 0;
  let token: string | null = 'tok-1';
  const refreshToken = vi.fn(async () => { token = 'tok-2'; return token; });
  const sock = new LiveSocket({
    url: () => 'ws://api.test/v1/ws/sessions/ses_1?last_sequence=' + seq,
    getToken: () => token,
    refreshToken,
    authExtras: () => ({ last_sequence: seq }),
    onFrame: (f) => frames.push(f),
    onStatus: (s) => statuses.push(s),
    createSocket: (u) => new FakeSocket(u),
    random: () => 0.5,
    ...overrides,
  });
  return { sock, statuses, frames, refreshToken, setSeq: (n: number) => { seq = n; }, setToken: (t: string | null) => { token = t; } };
}

beforeEach(() => { FakeSocket.all = []; vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe('LiveSocket', () => {
  it('authenticates with the first frame and never puts the token in the URL', () => {
    const { sock, setSeq } = make();
    setSeq(41);
    sock.start();
    const ws = last();
    expect(ws.url).not.toContain('tok-1');
    ws.open();
    expect(ws.sent[0]).toEqual({ type: 'auth', token: 'tok-1', last_sequence: 41 });
  });

  it('becomes live on ready and forwards frames', () => {
    const { sock, statuses, frames } = make();
    sock.start();
    last().open();
    last().message({ type: 'ready', session_id: 'ses_1', last_sequence: 0 });
    last().message({ type: 'ping' });
    expect(sock.state).toBe('live');
    expect(statuses).toEqual(['connecting', 'live']);
    expect(frames.map((f) => f.type)).toEqual(['ready', 'ping']);
  });

  it('reconnects with exponential backoff, resuming from the latest sequence', () => {
    const { sock, setSeq } = make();
    sock.start();
    last().open();
    last().message({ type: 'ready' });
    setSeq(17);
    last().drop(1006);
    expect(sock.state).toBe('reconnecting');
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(999); expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(1); expect(FakeSocket.all).toHaveLength(2);
    expect(last().url).toContain('last_sequence=17');
    // never became ready: delays keep doubling 2s, 4s, 8s
    last().drop(1006); vi.advanceTimersByTime(1999); expect(FakeSocket.all).toHaveLength(2); vi.advanceTimersByTime(1); expect(FakeSocket.all).toHaveLength(3);
    last().drop(1006); vi.advanceTimersByTime(4000); expect(FakeSocket.all).toHaveLength(4);
    last().drop(1006); vi.advanceTimersByTime(8000); expect(FakeSocket.all).toHaveLength(5);
  });

  it('caps the delay at 30s and resets the backoff once ready', () => {
    const { sock } = make();
    sock.start();
    for (let i = 0; i < 8; i++) { last().drop(1006); vi.advanceTimersByTime(30_000); }
    const n = FakeSocket.all.length;
    last().drop(1006);
    vi.advanceTimersByTime(29_999); expect(FakeSocket.all).toHaveLength(n);
    vi.advanceTimersByTime(1); expect(FakeSocket.all).toHaveLength(n + 1);
    last().open(); last().message({ type: 'ready' });
    expect(sock.reconnectAttempts).toBe(0);
    last().drop(1006);
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.all).toHaveLength(n + 2);
  });

  it('refreshes the token on close 4401 and reconnects immediately with it', async () => {
    const { sock, refreshToken } = make();
    sock.start();
    last().open(); last().message({ type: 'ready' });
    last().drop(4401);
    await vi.advanceTimersByTimeAsync(0);
    expect(refreshToken).toHaveBeenCalledTimes(1);
    expect(FakeSocket.all).toHaveLength(2);
    last().open();
    expect(last().sent[0].token).toBe('tok-2');
  });

  it('gives up as unauthorized when the token cannot be refreshed', async () => {
    const { sock } = make({ refreshToken: async () => null });
    sock.start();
    last().open(); last().message({ type: 'ready' });
    last().drop(4401);
    await vi.advanceTimersByTimeAsync(0);
    expect(sock.state).toBe('unauthorized');
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.all).toHaveLength(1);
  });

  it('does not loop forever on repeated 4401s', async () => {
    const { sock } = make();
    sock.start();
    for (let i = 0; i < 5; i++) { last().drop(4401); await vi.advanceTimersByTimeAsync(0); }
    expect(sock.state).toBe('unauthorized');
  });

  it('reconnects when the connection goes silent (idle watchdog)', () => {
    const { sock } = make({ idleTimeoutMs: 5000 });
    sock.start();
    last().open(); last().message({ type: 'ready' });
    vi.advanceTimersByTime(4000); last().message({ type: 'ping' });
    vi.advanceTimersByTime(4000);
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(1500);
    expect(sock.state).toBe('reconnecting');
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it('retries when the server never answers the auth frame', () => {
    const { sock } = make({ authTimeoutMs: 3000 });
    sock.start();
    last().open();
    vi.advanceTimersByTime(3000);
    expect(sock.state).toBe('reconnecting');
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it('stop() closes and never reconnects; nudge() skips the wait', () => {
    const { sock } = make();
    sock.start();
    last().drop(1006);
    sock.nudge();
    expect(FakeSocket.all).toHaveLength(2);
    sock.stop();
    expect(last().closed).toBe(true);
    vi.advanceTimersByTime(120_000);
    expect(FakeSocket.all).toHaveLength(2);
    expect(sock.state).toBe('idle');
  });
});

describe('replay through the store', () => {
  it('a reconnect that replays overlapping and duplicated events yields the same state as a clean run', () => {
    const mk = (n: number) => ({ event_id: `e${n}`, sequence: n, type: 'observation.created', timestamp: new Date(1e12 + n * 1000).toISOString(), data: { activity: `a${n}` } });
    const fresh = [1, 2, 3, 4, 5, 6].map(mk);
    let clean: AppState = reducer(initialState, { type: 'session/events', sessionId: 's', events: fresh });
    let live: AppState = reducer(initialState, { type: 'session/events', sessionId: 's', events: [mk(1), mk(2), mk(4)] });
    const resumeFrom = live.sessions['s']!.contiguous; // what the client would send as last_sequence
    expect(resumeFrom).toBe(2);
    const replay = fresh.filter((e) => e.sequence > resumeFrom); // server replays > N, includes duplicate 4
    live = reducer(live, { type: 'session/events', sessionId: 's', events: [mk(6), ...replay] });
    expect(live.sessions['s']!.events).toEqual(clean.sessions['s']!.events);
    expect(live.sessions['s']!.contiguous).toBe(6);
    clean = live;
  });
});
