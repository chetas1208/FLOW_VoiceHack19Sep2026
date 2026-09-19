import { FormEvent, useMemo, useState } from 'react';
import { COMMAND_LABEL, LEVEL_LABEL } from '../../lib/format';
import type { CommandType, PermissionLevel, PresenceState, SessionCommand } from '../../lib/types';
import { isTerminalCommand, type SessionSlice } from '../../store/reducer';
import { sendCommand } from '../../store/actions';
import { toast } from '../../store/toasts';
import { Icon, type IconName } from '../Icon';
import { CommandChip, Dialog } from '../primitives';

const OFFLINE_OK = new Set<CommandType>(['PAUSE', 'STOP', 'MUTE_VOICE', 'UNMUTE_VOICE']);

export function CommandStrip({ commands }: { commands: SessionCommand[] }) {
  if (commands.length === 0) return null;
  return (
    <ul className="cmd-strip" aria-label="Recent commands">
      {commands.slice(0, 5).map((c) => (
        <li key={c.command_id} className={isTerminalCommand(c.status) ? '' : 'is-open'}>
          <span>{COMMAND_LABEL[c.type] ?? c.type}</span>
          <CommandChip status={c.status} title={c.result ? JSON.stringify(c.result) : undefined} />
        </li>
      ))}
    </ul>
  );
}

interface BtnProps { type: CommandType; icon: IconName; label: string; onClick: () => void; variant?: string; extra?: string; note?: string }

function CtrlButton({ type: _type, icon, label, onClick, variant = 'secondary', extra, note, why, busy, queues }: BtnProps & { why: string | null; busy: boolean; queues: boolean }) {
  return (
    <button type="button" className={`ctrl btn btn-${variant} ${busy ? 'is-inflight' : ''} ${extra ?? ''}`} disabled={!!why} title={why ?? note} aria-busy={busy || undefined} onClick={onClick}>
      <Icon name={icon} />
      <span>{label}</span>
      {queues && <small className="ctrl-queue">queues</small>}
    </button>
  );
}

interface Props { slice: SessionSlice; presence: PresenceState; commands: SessionCommand[] }

const SMALL_TASKS = ['Run the test suite and summarize failures', 'Summarize what I changed in the last hour', 'Find where this error is raised'];
const DELEGATE_LEVELS: PermissionLevel[] = ['read_only', 'safe_execute', 'write_project', 'external_network'];

export function ControlBar({ slice, presence, commands }: Props) {
  const s = slice.session;
  const sessionId = slice.id;
  const deviceId = s?.device_id;
  const ended = s?.status === 'completed' || s?.status === 'failed';
  const paused = s?.status === 'paused';
  const offline = presence === 'offline';
  const muted = slice.voice.state === 'muted' && (!slice.voice.muted_until || new Date(slice.voice.muted_until).getTime() > Date.now());
  const [more, setMore] = useState(false);
  const [dialog, setDialog] = useState<null | 'stop' | 'goal' | 'compose'>(null);
  const [mode, setMode] = useState<'ask' | 'delegate'>('ask');

  const inflight = useMemo(() => {
    const set = new Set<string>();
    for (const c of commands) if (!isTerminalCommand(c.status)) set.add(c.type);
    return set;
  }, [commands]);

  const reason = (type: CommandType): string | null => {
    if (ended) return 'This session has ended.';
    if (offline && !OFFLINE_OK.has(type)) return 'The device is offline. Reconnect it to use this control.';
    return null;
  };
  const fire = async (type: CommandType, payload: Record<string, unknown> = {}) => {
    const c = await sendCommand(type, payload, { sessionId, deviceId });
    if (c) toast(c.status === 'queued' && offline ? `${COMMAND_LABEL[type]} queued. It runs when the device reconnects.` : `${COMMAND_LABEL[type]} sent.`, 'ok', 3500);
    return c;
  };

  const btn = (p: BtnProps) => (
    <CtrlButton key={`${p.type}-${p.label}`} {...p} why={reason(p.type)} busy={inflight.has(p.type)} queues={offline && OFFLINE_OK.has(p.type) && !ended} />
  );

  return (
    <div className={`dock ${more ? 'is-more' : ''}`}>
      <CommandStrip commands={commands} />
      <div className="dock-bar" role="toolbar" aria-label="Remote controls">
        <div className="ctrl-primary">
          {paused
            ? btn({ type: 'RESUME', icon: 'play', label: 'Resume', variant: 'primary', onClick: () => fire('RESUME') })
            : btn({ type: 'PAUSE', icon: 'pause', label: 'Pause', onClick: () => fire('PAUSE') })}
          {muted
            ? btn({ type: 'UNMUTE_VOICE', icon: 'volume', label: 'Unmute', onClick: () => fire('UNMUTE_VOICE') })
            : btn({ type: 'MUTE_VOICE', icon: 'mute', label: 'Mute', onClick: () => fire('MUTE_VOICE', {}) })}
          {btn({ type: 'ADD_TASK', icon: 'agent', label: 'Delegate task', variant: 'delegate', extra: 'ctrl-delegate', note: "FLOW's agent acts on your Mac", onClick: () => { setMode('delegate'); setDialog('compose'); } })}
          {btn({ type: 'STOP', icon: 'stop', label: 'Stop', variant: 'danger-ghost', onClick: () => setDialog('stop') })}
          <button type="button" className="ctrl btn btn-ghost ctrl-more-toggle" aria-expanded={more} onClick={() => setMore((m) => !m)}><Icon name="chevron" style={{ transform: more ? 'rotate(180deg)' : undefined }} /><span>More</span></button>
        </div>
        <div className="ctrl-secondary">
          {btn({ type: 'ASK', icon: 'chat', label: 'Ask FLOW', variant: 'ask', extra: 'ctrl-ask', note: 'A question. Changes nothing', onClick: () => { setMode('ask'); setDialog('compose'); } })}
          {btn({ type: 'MUTE_VOICE', icon: 'moon', label: 'Quiet 15m', onClick: () => fire('MUTE_VOICE', { minutes: 15 }) })}
          {btn({ type: 'MUTE_VOICE', icon: 'moon', label: 'Quiet 30m', onClick: () => fire('MUTE_VOICE', { minutes: 30 }) })}
          {btn({ type: 'UPDATE_GOAL', icon: 'target', label: 'Change goal', onClick: () => setDialog('goal') })}
        </div>
      </div>

      <StopDialog open={dialog === 'stop'} onClose={() => setDialog(null)} onConfirm={async () => { await fire('STOP'); setDialog(null); }} offline={offline} />
      <GoalDialog open={dialog === 'goal'} onClose={() => setDialog(null)} current={slice.goal.text || s?.goal || ''} onSubmit={async (goal) => { const c = await fire('UPDATE_GOAL', { goal }); if (c) setDialog(null); }} />
      <Composer open={dialog === 'compose'} mode={mode} setMode={setMode} onClose={() => setDialog(null)} blocked={reason(mode === 'ask' ? 'ASK' : 'ADD_TASK')}
        onAsk={async (q) => { const c = await fire('ASK', { question: q }); if (c) setDialog(null); }}
        onDelegate={async (instruction, permission_level) => { const c = await fire('ADD_TASK', { instruction, permission_level }); if (c) setDialog(null); }} />
    </div>
  );
}

function StopDialog({ open, onClose, onConfirm, offline }: { open: boolean; onClose: () => void; onConfirm: () => Promise<void>; offline: boolean }) {
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} title="Stop this session?" tone="danger">
      <p>The session ends and FLOW builds your final report. Any task the agent is running is cancelled.</p>
      {offline && <p className="hint hint-warn">The device is offline. Stop is queued and takes effect when it reconnects.</p>}
      <div className="row-actions">
        <button type="button" className="btn btn-danger" disabled={busy} onClick={async () => { setBusy(true); await onConfirm(); setBusy(false); }}>{busy ? 'Stopping' : 'Stop session'}</button>
        <button type="button" className="btn btn-secondary" onClick={onClose}>Keep going</button>
      </div>
    </Dialog>
  );
}

function GoalDialog({ open, onClose, current, onSubmit }: { open: boolean; onClose: () => void; current: string; onSubmit: (g: string) => Promise<void> }) {
  const [goal, setGoal] = useState(current);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} title="Change goal">
      <form className="form" onSubmit={async (e: FormEvent) => { e.preventDefault(); setBusy(true); await onSubmit(goal.trim()); setBusy(false); }}>
        <p className="muted">FLOW will judge your focus against the new goal from now on. The old goal stays in the report history.</p>
        <label className="field"><span>New goal</span><textarea required rows={3} maxLength={500} value={goal} onChange={(e) => setGoal(e.target.value)} /></label>
        <div className="row-actions">
          <button className="btn btn-primary" disabled={busy || !goal.trim() || goal.trim() === current}>{busy ? 'Sending' : 'Change goal'}</button>
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Dialog>
  );
}

interface ComposerProps {
  open: boolean; mode: 'ask' | 'delegate'; setMode: (m: 'ask' | 'delegate') => void; onClose: () => void; blocked: string | null;
  onAsk: (q: string) => Promise<void>; onDelegate: (i: string, l: PermissionLevel) => Promise<void>;
}

/** Ask and Delegate are deliberately different: different color, icon, copy, fields and verb. */
function Composer({ open, mode, setMode, onClose, blocked, onAsk, onDelegate }: ComposerProps) {
  const [text, setText] = useState('');
  const [level, setLevel] = useState<PermissionLevel>('safe_execute');
  const [busy, setBusy] = useState(false);
  const ask = mode === 'ask';
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (ask) await onAsk(text.trim()); else await onDelegate(text.trim(), level);
      setText('');
    } finally { setBusy(false); }
  }
  return (
    <Dialog open={open} onClose={onClose} title="Talk to FLOW">
      <div className="mode-pick" role="radiogroup" aria-label="What do you want to do?">
        <button type="button" role="radio" aria-checked={ask} className={`mode mode-ask ${ask ? 'is-on' : ''}`} onClick={() => setMode('ask')}>
          <Icon name="chat" size={20} /><strong>Ask FLOW</strong><span>A question. It answers, and changes nothing.</span>
        </button>
        <button type="button" role="radio" aria-checked={!ask} className={`mode mode-delegate ${!ask ? 'is-on' : ''}`} onClick={() => setMode('delegate')}>
          <Icon name="agent" size={20} /><strong>Delegate task</strong><span>A job. The agent acts on your Mac.</span>
        </button>
      </div>
      <form className="form" onSubmit={submit}>
        {ask ? (
          <>
            <label className="field"><span>Your question</span>
              <textarea required rows={3} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} placeholder="What was I working on before that meeting?" />
            </label>
            <p className="hint"><Icon name="eye" size={14} /> Read only. FLOW answers from what it has seen this session and writes it in the voice transcript.</p>
          </>
        ) : (
          <>
            <label className="field"><span>What should the agent do?</span>
              <textarea required minLength={8} rows={3} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} placeholder="Run the tests and tell me which ones fail" />
            </label>
            <div className="chips-row" aria-label="Suggested small tasks">
              {SMALL_TASKS.map((t) => <button type="button" key={t} className="chip chip-button" onClick={() => setText(t)}>{t}</button>)}
            </div>
            <label className="field"><span>How much may it do?</span>
              <select value={level} onChange={(e) => setLevel(e.target.value as PermissionLevel)}>
                {DELEGATE_LEVELS.map((l) => <option key={l} value={l}>{LEVEL_LABEL[l]}</option>)}
              </select>
            </label>
            <p className="hint hint-caution"><Icon name="shield" size={14} /> The agent runs on your computer. Anything beyond this level pauses and asks you first.</p>
          </>
        )}
        {blocked && <p className="hint hint-warn">{blocked}</p>}
        <div className="row-actions">
          <button className={`btn btn-lg ${ask ? 'btn-ask-solid' : 'btn-primary'}`} disabled={busy || !!blocked || text.trim().length < (ask ? 2 : 8)}>{busy ? 'Sending' : ask ? 'Ask FLOW' : 'Delegate task'}</button>
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Dialog>
  );
}
