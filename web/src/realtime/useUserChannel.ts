import { useEffect } from 'react';
import { auth } from '../auth/auth';
import { config } from '../config';
import { api } from '../lib/api';
import { LiveSocket, toWsUrl } from '../lib/ws';
import { store } from '../store/store';

/** Devices, approvals inbox and session summaries: one socket, refreshed by REST only on (re)connect. */
export function useUserChannel(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let readyCount = 0;
    const load = async () => {
      const [devs, apr] = await Promise.allSettled([api.devices(), api.approvals()]);
      if (cancelled) return;
      if (devs.status === 'fulfilled') store.dispatch({ type: 'devices/set', devices: devs.value.items });
      if (apr.status === 'fulfilled') store.dispatch({ type: 'approvals/set', approvals: apr.value.items });
    };
    const socket = new LiveSocket({
      url: () => toWsUrl(config.apiUrl, '/v1/ws/user'),
      getToken: () => auth.getToken(),
      refreshToken: () => auth.refresh(),
      onStatus: (conn) => store.dispatch({ type: 'user/conn', conn }),
      onFrame: (f) => {
        if (f.type === 'ready') { if (++readyCount > 1) void load(); } // resync after every reconnect; frames in between were missed
        else if (f.type === 'presence' && f.device_id) store.dispatch({ type: 'device/presence', deviceId: f.device_id, presence: f.presence });
        else if (f.type === 'approval' && f.approval) store.dispatch({ type: 'approval/upsert', approval: f.approval });
        else if (f.type === 'session' && f.session) store.dispatch({ type: 'session/upsert', session: f.session });
      },
    });
    void load();
    socket.start();
    const nudge = () => { if (document.visibilityState === 'visible') socket.nudge(); };
    window.addEventListener('online', nudge);
    document.addEventListener('visibilitychange', nudge);
    return () => {
      cancelled = true;
      socket.stop();
      window.removeEventListener('online', nudge);
      document.removeEventListener('visibilitychange', nudge);
    };
  }, [enabled]);
}
