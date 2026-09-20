import { useEffect, type ReactNode } from 'react';

export function FlowDrawer({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="flow-drawer-root" role="presentation">
      <button type="button" className="flow-drawer-scrim" aria-label="Close panel" onClick={onClose} />
      <aside className="flow-drawer glass-panel" aria-label={title}>
        <header className="flow-drawer-head">
          <strong>{title}</strong>
          <button type="button" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="flow-drawer-body">{children}</div>
      </aside>
    </div>
  );
}
