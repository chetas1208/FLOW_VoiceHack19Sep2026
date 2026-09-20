import { useEffect, useRef, useState } from 'react';
import type { AccountUser } from '../../../lib/flowWorkspaceUi';

function initials(name?: string, email?: string): string {
  const n = name?.trim();
  if (n) {
    const parts = n.split(/\s+/);
    if (parts.length >= 2) return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase();
    return n.slice(0, 2).toUpperCase();
  }
  return (email?.[0] ?? 'A').toUpperCase();
}

export function AccountMenu({ account }: { account?: AccountUser }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

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
        className="account-avatar"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Account menu"
        onClick={() => setOpen((v) => !v)}
      >
        {initials(account?.name, account?.email)}
      </button>
      {open && (
        <div className="header-popover glass-panel account-popover" role="menu">
          <p className="account-popover-id">
            <strong>{account?.name ?? 'Account'}</strong>
            {account?.email && <small>{account.email}</small>}
          </p>
          <button type="button" role="menuitem" onClick={() => { setOpen(false); window.location.href = '/auth'; }}>
            Account
          </button>
          <button type="button" role="menuitem" onClick={() => setOpen(false)}>
            Devices
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => void fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).finally(() => { window.location.href = '/auth'; })}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
