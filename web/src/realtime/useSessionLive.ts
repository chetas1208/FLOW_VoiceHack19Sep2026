import { useCallback, useEffect, useState } from 'react';
import { auth } from '../auth/auth';
import { config } from '../config';
import { api, ApiError } from '../lib/api';
import { LiveSocket, toWsUrl } from '../lib/ws';
import { store } from '../store/store';
import type { FlowEvent } from '../lib/types';

const HISTORY_WINDOW = 300;

export interface LiveLoad { loading: boolean; error: ApiError | Error | null; reload: () => void }

/** Loads the snapshot + recent history, then attaches the viewer socket (replay from the last contiguous sequence). */
export function useSessionLive(id: string): LiveLoad {
  const [state, setState] = useState<{ loading: boolean; error: Error | null }>({ loading: true, error: null });
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    let socket: LiveSocket | null = null;
    let buffer: FlowEvent[] = [];
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      flushTimer = null;
      if (buffer.length) { const events = buffer; buffer = []; store.dispatch({ type: 'session/events', sessionId: id, events }); }
    };
    const queue = (ev: FlowEvent) => { buffer.push(ev); flushTimer ??= setTimeout(flush, 40); };
    const nudge = () => { if (document.visibilityState === 'visible') socket?.nudge(); };

    setState({ loading: !store.getState().sessions[id]?.hydrated, error: null });
    (async () => {
      try {
        const live = await api.live(id);
        if (cancelled) return;
        store.dispatch({ type: 'session/hydrate', live });
        const last = live.last_event_sequence ?? 0;
        let after = Math.max(0, last - HISTORY_WINDOW);
        const floor = after;
        for (let page = 0; page < 6; page++) {
          const res = await api.events(id, after);
          if (cancelled) return;
          const items = res.items ?? [];
          if (!items.length) break;
          store.dispatch({ type: 'session/events', sessionId: id, events: items, floor: page === 0 ? floor : undefined });
          const top = Math.max(...items.map((e) => e.sequence));
          if (top <= after || top >= last) break;
          after = top;
        }
        setState({ loading: false, error: null });
        const [chats, cmds] = await Promise.allSettled([api.entities(id, 'chat', 30), api.sessionCommands(id, 30)]);
        if (cancelled) return;
        if (chats.status === 'fulfilled') store.dispatch({ type: 'session/entities', sessionId: id, items: chats.value.items });
        if (cmds.status === 'fulfilled') store.dispatch({ type: 'commands/upsert', commands: cmds.value.items });

        socket = new LiveSocket({
          url: () => toWsUrl(config.apiUrl, `/v1/ws/sessions/${encodeURIComponent(id)}?last_sequence=${store.getState().sessions[id]?.contiguous ?? 0}`),
          authExtras: () => ({ last_sequence: store.getState().sessions[id]?.contiguous ?? 0 }),
          getToken: () => auth.getToken(),
          refreshToken: () => auth.refresh(),
          onStatus: (conn) => store.dispatch({ type: 'session/conn', sessionId: id, conn }),
          onFrame: (f) => {
            if (f.type === 'event' && f.event) queue(f.event as FlowEvent);
            else if (f.type === 'command' && f.command) store.dispatch({ type: 'commands/upsert', commands: [f.command] });
            else if (f.type === 'presence' && f.presence) {
              store.dispatch({ type: 'session/presence', sessionId: id, presence: f.presence });
              const dev = store.getState().sessions[id]?.session?.device_id;
              if (dev) store.dispatch({ type: 'device/presence', deviceId: dev, presence: f.presence });
            }
          },
        });
        socket.start();
        window.addEventListener('online', nudge);
        document.addEventListener('visibilitychange', nudge);
      } catch (e) {
        if (!cancelled) setState({ loading: false, error: e as Error });
      }
    })();

    return () => {
      cancelled = true;
      if (flushTimer) clearTimeout(flushTimer);
      flush();
      socket?.stop();
      window.removeEventListener('online', nudge);
      document.removeEventListener('visibilitychange', nudge);
      store.dispatch({ type: 'session/conn', sessionId: id, conn: 'idle' });
    };
  }, [id, nonce]);

  return { ...state, reload };
}
