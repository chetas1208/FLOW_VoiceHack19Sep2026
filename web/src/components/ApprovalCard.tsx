import { useState } from 'react';
import { LEVEL_LABEL, untilLabel } from '../lib/format';
import { useNow } from '../lib/hooks';
import type { ActionApproval } from '../lib/types';
import { sendCommand } from '../store/actions';
import { Chip } from './primitives';
import { Icon } from './Icon';

const riskTone = (risk: string) => (/high|critical/i.test(risk) ? 'bad' : /med/i.test(risk) ? 'warn' : 'ok');

export function ApprovalCard({ approval, deviceId, disabledReason, sessionLabel }: { approval: ActionApproval; deviceId?: string; disabledReason?: string | null; sessionLabel?: string }) {
  const now = useNow(1000);
  const [busy, setBusy] = useState<null | 'approve' | 'deny'>(null);
  const [ack, setAck] = useState(false);
  const risky = /high|critical/i.test(approval.risk) || approval.permission_level === 'destructive';
  const left = untilLabel(approval.expires_at, now);
  const expired = approval.expires_at ? new Date(approval.expires_at).getTime() <= now : false;
  const locked = Boolean(disabledReason) || expired || approval.status !== 'pending';
  const summary = approval.action?.summary ?? approval.action?.command ?? 'Action needs approval';

  async function decide(kind: 'approve' | 'deny') {
    setBusy(kind);
    const cmd = await sendCommand(kind === 'approve' ? 'APPROVE_ACTION' : 'DENY_ACTION', { approval_id: approval.id }, { sessionId: approval.session_id, deviceId });
    if (!cmd) setBusy(null);
  }

  return (
    <article className={`approval risk-${riskTone(approval.risk)}`} aria-label="Approval request">
      <header className="approval-head">
        <Chip tone="warn">Needs approval</Chip>
        <Chip tone={riskTone(approval.risk) as 'ok'}>{approval.risk} risk</Chip>
        {left && <span className="approval-clock"><Icon name="clock" size={14} /> {left} left</span>}
        {expired && <Chip tone="bad">Expired</Chip>}
      </header>
      {sessionLabel && <p className="approval-session">{sessionLabel}</p>}
      <dl className="approval-facts">
        <div><dt>What</dt><dd><code className="mono-inline">{summary}</code></dd></div>
        {approval.why && <div><dt>Why</dt><dd>{approval.why}</dd></div>}
        <div><dt>Access</dt><dd>{LEVEL_LABEL[approval.permission_level] ?? approval.permission_level}</dd></div>
        {approval.scope && <div><dt>Scope</dt><dd>{approval.scope}</dd></div>}
      </dl>
      {risky && !locked && (
        <label className="check">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>I have read the scope and understand this may not be reversible.</span>
        </label>
      )}
      <div className="approval-actions">
        <button type="button" className="btn btn-ok" disabled={locked || busy !== null || (risky && !ack)} onClick={() => decide('approve')}>
          <Icon name="check" /> {busy === 'approve' ? 'Sending' : 'Approve'}
        </button>
        <button type="button" className="btn btn-danger-ghost" disabled={locked || busy !== null} onClick={() => decide('deny')}>
          <Icon name="x" /> {busy === 'deny' ? 'Sending' : 'Deny'}
        </button>
      </div>
      {disabledReason && <p className="hint hint-warn">{disabledReason}</p>}
    </article>
  );
}
