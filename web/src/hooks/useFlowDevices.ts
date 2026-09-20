import { useCallback, useEffect, useRef, useState } from 'react';
import { accountApi, type FlowDevice } from '../lib/account';
import { pickPrimaryDevice, type PresenceState } from '../lib/flowDeviceModel';
import { readPreferredDeviceId, writePreferredDeviceId } from '../lib/pairedDeviceStore';

const ONLINE_POLL_MS = 15_000;
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15_000];

function jitter(ms: number) {
  return ms + Math.floor(Math.random() * 400);
}

export function useFlowDevices() {
  const [devices, setDevices] = useState<FlowDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [connecting, setConnecting] = useState(false);
  const attemptRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await accountApi.devices();
      setDevices(result.items);
      setError('');
      const primary = pickPrimaryDevice(result.items, readPreferredDeviceId());
      if (primary && !primary.revoked_at) writePreferredDeviceId(primary.id);
      const online = primary?.presence.state === 'online';
      if (online) {
        attemptRef.current = 0;
        setConnecting(false);
      }
      return result.items;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'FLOW could not load connected devices.');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;

    const schedule = (delay: number) => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => { if (active) void tick(); }, jitter(delay));
    };

    const tick = async () => {
      const items = await load();
      if (!active || !items) {
        schedule(RECONNECT_DELAYS[Math.min(attemptRef.current, RECONNECT_DELAYS.length - 1)]);
        return;
      }
      const primary = pickPrimaryDevice(items, readPreferredDeviceId());
      const paired = primary && !primary.revoked_at;
      const online = primary?.presence.state === 'online';
      if (paired && !online) {
        setConnecting(true);
        attemptRef.current = Math.min(attemptRef.current + 1, RECONNECT_DELAYS.length - 1);
        schedule(RECONNECT_DELAYS[attemptRef.current]);
        return;
      }
      setConnecting(false);
      schedule(online ? ONLINE_POLL_MS : RECONNECT_DELAYS[0]);
    };

    void tick();
    const onOnline = () => { attemptRef.current = 0; void tick(); };
    const onVisible = () => { if (document.visibilityState === 'visible') onOnline(); };
    window.addEventListener('online', onOnline);
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      active = false;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      window.removeEventListener('online', onOnline);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  const preferredId = readPreferredDeviceId();
  const device = pickPrimaryDevice(devices, preferredId);
  const presence: PresenceState = connecting && device && !device.revoked_at && device.presence.state !== 'online'
    ? 'connecting'
    : device?.presence.state === 'degraded'
      ? 'degraded'
      : device?.presence.state === 'online'
        ? 'online'
        : 'offline';

  return { devices, device, loading, error, presence, reload: load };
}
