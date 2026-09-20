type Tone = 'ok' | 'warn' | 'idle' | 'neutral';

const DOT: Record<Tone, string> = { ok: '●', warn: '◐', idle: '○', neutral: '◌' };

export function SystemStatusItem({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="system-status-item">
      <span className={`system-dot tone-${tone}`} aria-hidden="true">{DOT[tone]}</span>
      <span className="system-label">{label}</span>
      <span className="system-value">{value}</span>
    </div>
  );
}
