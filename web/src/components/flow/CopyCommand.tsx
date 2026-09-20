import { useCallback, useState } from 'react';

export async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    try {
      const ta = document.createElement('textarea');
      ta.value = value;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

export function CopyCommand({
  command,
  label,
  hint,
  status,
  onCopied,
}: {
  command: string;
  label?: string;
  hint?: string;
  status?: React.ReactNode;
  onCopied?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const runCopy = useCallback(async () => {
    const ok = await copyText(command);
    if (ok) {
      setCopied(true);
      onCopied?.();
      window.setTimeout(() => setCopied(false), 1800);
    }
  }, [command, onCopied]);

  return (
    <div className="copy-command">
      {label && <div className="copy-command-label">{label}</div>}
      <div className="copy-command-row">
        <code>{command}</code>
        <button type="button" onClick={() => void runCopy()}>{copied ? 'Copied ✓' : 'Copy'}</button>
      </div>
      {hint && <p className="copy-command-hint">{hint}</p>}
      {status && <div className="copy-command-status">{status}</div>}
    </div>
  );
}

export function CopyCodeBlock({
  lines,
  title,
  onCopied,
}: {
  lines: string[];
  title?: string;
  onCopied?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const text = lines.join('\n');

  const runCopy = useCallback(async () => {
    const ok = await copyText(text);
    if (ok) {
      setCopied(true);
      onCopied?.();
      window.setTimeout(() => setCopied(false), 1800);
    }
  }, [text, onCopied]);

  return (
    <div className="copy-code-block">
      {title && <div className="copy-code-block-head"><span>{title}</span><button type="button" onClick={() => void runCopy()}>{copied ? 'Copied ✓' : 'Copy all'}</button></div>}
      <pre>{lines.join('\n')}</pre>
      {!title && <button type="button" className="copy-code-block-solo" onClick={() => void runCopy()}>{copied ? 'Copied ✓' : 'Copy'}</button>}
    </div>
  );
}
