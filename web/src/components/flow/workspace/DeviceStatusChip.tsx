import { useEffect, useRef, useState } from 'react';
import type { FlowDevice } from '../../../lib/account';
import { ago, daemonStatus, modelStatus, presenceLabel, pairingState, type PresenceState } from '../../../lib/flowDeviceModel';
import { presenceTone } from '../../../lib/flowWorkspaceUi';

export function DeviceStatusChip({
  device,
  pairing,
  presence,
}: {
  device: FlowDevice | null;
  pairing: ReturnType<typeof pairingState>;
  presence: PresenceState;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const headerTone = pairing === 'paired' ? presenceTone(presence) : 'offline';
  const health = device?.presence.health ?? {};
  const paired = pairing === 'paired';
  const lastBeat = device?.presence.last_heartbeat_at ?? device?.last_seen_at;
  const deviceName = device?.name ?? 'No device';

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  return (
    <div className="header-popover-anchor" ref={rootRef}>
      <button
        type="button"
        className="device-chip"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <i className={`device-dot ${headerTone}`} aria-hidden="true" />
        <span className="device-chip-label">{deviceName}</span>
      </button>
      {open && (
        <div className="header-popover glass-panel" role="dialog" aria-label="Device status">
          <h3>Device</h3>
          <dl className="device-popover-list">
            <div><dt>Paired</dt><dd>{paired ? 'Yes' : 'No'}</dd></div>
            <div><dt>Connected</dt><dd>{paired ? presenceLabel(presence) : '—'}</dd></div>
            <div><dt>Daemon</dt><dd>{paired ? daemonStatus(health.daemon, presence) : '—'}</dd></div>
            <div><dt>Model</dt><dd>{paired ? modelStatus(health.model) : '—'}</dd></div>
            <div><dt>Last heartbeat</dt><dd>{paired ? ago(lastBeat ?? null) : '—'}</dd></div>
          </dl>
        </div>
      )}
    </div>
  );
}
