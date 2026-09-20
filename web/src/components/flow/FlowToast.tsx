import { useEffect } from 'react';

export function FlowToast({ message, onClear }: { message: string; onClear: () => void }) {
  useEffect(() => {
    if (!message) return;
    const t = window.setTimeout(onClear, 4200);
    return () => window.clearTimeout(t);
  }, [message, onClear]);

  if (!message) return null;
  return (
    <p className="flow-toast" role="status" aria-live="polite">
      {message}
    </p>
  );
}
