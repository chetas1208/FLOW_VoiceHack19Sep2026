import { useEffect, useRef, type ReactNode } from 'react';
import type { CommandStatus, PresenceState } from '../lib/types';
import { Icon } from './Icon';

export function PresenceDot({ state, label = true }: { state: PresenceState; label?: boolean }) {
  const text = state === 'online' ? 'Online' : state === 'degraded' ? 'Degraded' : 'Offline';
  return (
    <span className={`presence presence-${state}`}>
      <i className="dot" aria-hidden="true" />
      {label ? <span>{text}</span> : <span className="sr-only">{text}</span>}
    </span>
  );
}

const CMD_LABEL: Record<CommandStatus, string> = {
  queued: 'Queued', delivered: 'Delivered', running: 'Running', succeeded: 'Succeeded', failed: 'Failed', expired: 'Expired', cancelled: 'Cancelled', denied: 'Denied',
};
const CMD_TONE: Record<CommandStatus, string> = {
  queued: 'neutral', delivered: 'info', running: 'info', succeeded: 'ok', failed: 'bad', expired: 'warn', cancelled: 'neutral', denied: 'bad',
};

export function CommandChip({ status, title }: { status: CommandStatus; title?: string }) {
  return <span className={`chip chip-${CMD_TONE[status]} ${status === 'running' ? 'chip-live' : ''}`} title={title}>{CMD_LABEL[status]}</span>;
}

export function Chip({ tone = 'neutral', children, title }: { tone?: 'neutral' | 'info' | 'ok' | 'warn' | 'bad' | 'violet' | 'cyan'; children: ReactNode; title?: string }) {
  return <span className={`chip chip-${tone}`} title={title}>{children}</span>;
}

export function Meter({ value, tone = 'cyan', label }: { value: number | null; tone?: 'cyan' | 'violet' | 'ok'; label: string }) {
  const v = value === null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div className="meter" role="img" aria-label={`${label}: ${value === null ? 'no data yet' : value + ' percent'}`}>
      <span className={`meter-fill meter-${tone}`} style={{ width: `${v}%` }} />
    </div>
  );
}

/** Accessible modal built on <dialog>. Focus is trapped and restored by the browser; Escape closes. */
export function Dialog({ open, onClose, title, children, tone }: { open: boolean; onClose: () => void; title: string; children: ReactNode; tone?: 'danger' | 'default' }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className={`dialog ${tone === 'danger' ? 'dialog-danger' : ''}`} onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }} aria-labelledby="dlg-title">
      {open && (
        <div className="dialog-body">
          <header className="dialog-head">
            <h2 id="dlg-title">{title}</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
          </header>
          {children}
        </div>
      )}
    </dialog>
  );
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return <span className="spinner" role="status" aria-label={label} />;
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
