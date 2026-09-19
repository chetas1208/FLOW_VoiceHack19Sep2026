import { useMemo, useState } from 'react';
import { LEVEL_LABEL, pct, untilLabel, clockOrEmpty } from './util';
import { useNow } from '../../lib/hooks';
import type { ActionRecommendation, DelegatedTask, Subtask } from '../../lib/types';
import type { SessionSlice, ToolEntry } from '../../store/reducer';
import { sendCommand } from '../../store/actions';
import { transcript } from '../../store/selectors';
import { Chip, Meter } from '../primitives';
import { Icon } from '../Icon';

interface Ctx { sessionId: string; deviceId?: string; blocked: string | null }

/* ------------------------------------------------------------------ recommendation */
export function RecommendationCard({ rec, ctx }: { rec: ActionRecommendation; ctx: Ctx }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [fb, setFb] = useState<'up' | 'down' | null>(rec.feedback === 'helpful' ? 'up' : rec.feedback === 'not_helpful' ? 'down' : null);
  const conf = pct(rec.confidence);
  const run = async (key: string, type: 'EXECUTE_RECOMMENDATION' | 'DISMISS_RECOMMENDATION') => {
    setBusy(key);
    await sendCommand(type, { recommendation_id: rec.id }, { sessionId: ctx.sessionId, deviceId: ctx.deviceId });
    setBusy(null);
  };
  const feedback = async (helpful: boolean) => {
    setFb(helpful ? 'up' : 'down');
    const c = await sendCommand('FEEDBACK_RECOMMENDATION', { recommendation_id: rec.id, helpful }, { sessionId: ctx.sessionId, deviceId: ctx.deviceId });
    if (!c) setFb(null);
  };
  const urgent = rec.level === 'urgent' || rec.level === 'recommend';
  return (
    <article className={`rec rec-${rec.level}`} aria-label="Next action">
      <header className="rec-head">
        <Chip tone={urgent ? 'violet' : 'neutral'}>{rec.level === 'urgent' ? 'Do this now' : 'Next action'}</Chip>
        {conf !== null && <span className="small muted">{conf}% confident</span>}
        <Chip tone="neutral" title="Estimated impact">{rec.impact_estimate} impact</Chip>
      </header>
      <h3>{rec.title}</h3>
      <p>{rec.description}</p>
      {rec.can_delegate && rec.proposed_task && (
        <p className="rec-delegate"><Icon name="agent" size={16} /><span>If you choose Do it, FLOW's agent will run: <q>{rec.proposed_task}</q></span></p>
      )}
      <div className="rec-actions">
        <button type="button" className="btn btn-primary" disabled={!!ctx.blocked || busy !== null} onClick={() => run('do', 'EXECUTE_RECOMMENDATION')}><Icon name="bolt" />{busy === 'do' ? 'Sending' : 'Do it'}</button>
        <button type="button" className="btn btn-secondary" disabled={!!ctx.blocked || busy !== null} onClick={() => run('dismiss', 'DISMISS_RECOMMENDATION')}>{busy === 'dismiss' ? 'Sending' : 'Dismiss'}</button>
        <span className="rec-fb" role="group" aria-label="Rate this recommendation">
          <button type="button" className={`icon-btn ${fb === 'up' ? 'is-on' : ''}`} aria-pressed={fb === 'up'} disabled={!!ctx.blocked || fb !== null} onClick={() => feedback(true)} title="Helpful"><Icon name="up" size={17} /><span className="sr-only">Helpful</span></button>
          <button type="button" className={`icon-btn ${fb === 'down' ? 'is-on' : ''}`} aria-pressed={fb === 'down'} disabled={!!ctx.blocked || fb !== null} onClick={() => feedback(false)} title="Not helpful"><Icon name="down" size={17} /><span className="sr-only">Not helpful</span></button>
        </span>
      </div>
      {ctx.blocked && <p className="hint hint-warn">{ctx.blocked}</p>}
      <details className="why">
        <summary>Why this recommendation?</summary>
        <p>{rec.reason}</p>
        {rec.evidence.length > 0 && <ul className="evidence">{rec.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>}
        {conf !== null && <div className="why-conf"><span className="small muted">Confidence</span><Meter value={conf} tone="violet" label="Confidence" /></div>}
      </details>
    </article>
  );
}

/* ------------------------------------------------------------------ delegated task */
const TASK_TONE: Record<string, 'info' | 'ok' | 'bad' | 'warn' | 'neutral' | 'violet'> = {
  queued: 'neutral', planning: 'violet', waiting_for_approval: 'warn', running: 'violet', completed: 'ok', failed: 'bad', cancelled: 'neutral',
};
const TASK_LABEL: Record<string, string> = { queued: 'Queued', planning: 'Planning', waiting_for_approval: 'Waiting for approval', running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled' };

function ToolLine({ t }: { t: ToolEntry }) {
  return (
    <li className={`tool tool-${t.state}`}>
      <i aria-hidden="true" />
      <div>
        <p><code>{t.tool}</code>{t.args_summary && <span className="tool-args"> {t.args_summary}</span>}</p>
        {t.summary && <p className="small muted">{t.summary}</p>}
      </div>
      <span className="small muted">{t.state === 'running' ? 'running' : t.state === 'failed' ? `failed (${t.exit_code})` : 'done'}</span>
    </li>
  );
}

export function TaskPanel({ task, tools, ctx }: { task: DelegatedTask | null; tools: ToolEntry[]; ctx: Ctx }) {
  const [busy, setBusy] = useState(false);
  if (!task) {
    return (
      <section className="card task-empty">
        <h3>Delegated task</h3>
        <p className="muted">Nothing is running. Use Delegate task to hand FLOW's agent a small job. It shows its plan here and asks before anything risky.</p>
      </section>
    );
  }
  const active = ['queued', 'planning', 'waiting_for_approval', 'running'].includes(task.status);
  const plan = task.plan ?? [];
  const done = plan.filter((p) => /done|complete/i.test(String(p.status))).length;
  return (
    <section className="card task" aria-label="Delegated task">
      <header className="card-head">
        <h3>Delegated task</h3>
        <Chip tone={TASK_TONE[task.status] ?? 'neutral'}>{TASK_LABEL[task.status] ?? task.status}</Chip>
      </header>
      <p className="task-instruction">{task.instruction}</p>
      <p className="small muted">{LEVEL_LABEL[task.permission_level] ?? task.permission_level}, started from {task.created_from}</p>
      {plan.length > 0 && (
        <>
          <div className="task-progress"><Meter value={Math.round((done / plan.length) * 100)} tone="violet" label="Plan progress" /><span className="small muted">{done} of {plan.length} steps</span></div>
          <ol className="plan">
            {plan.map((p, i) => {
              const st = String(p.status ?? 'todo');
              const state = /done|complete/i.test(st) ? 'done' : /run|progress|active/i.test(st) ? 'now' : 'todo';
              return <li key={i} className={`plan-${state}`}><i aria-hidden="true">{state === 'done' ? <Icon name="check" size={12} /> : null}</i><span>{String(p.title ?? p.step ?? `Step ${i + 1}`)}</span></li>;
            })}
          </ol>
        </>
      )}
      {tools.length > 0 && (
        <div className="tools">
          <h4>Tool activity</h4>
          <ul>{tools.slice(-6).map((t) => <ToolLine key={t.key} t={t} />)}</ul>
        </div>
      )}
      {task.status === 'completed' && task.result?.summary && <div className="result"><h4>Result</h4><p>{task.result.summary}</p></div>}
      {task.status === 'failed' && task.error && <div className="result result-bad"><h4>What went wrong</h4><p>{task.error}</p></div>}
      {task.evidence?.length > 0 && !active && (
        <details className="why"><summary>Evidence</summary><ul className="evidence">{task.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul></details>
      )}
      {active && (
        <button type="button" className="btn btn-ghost btn-sm" disabled={!!ctx.blocked || busy} onClick={async () => { setBusy(true); await sendCommand('CANCEL_TASK', { task_id: task.id }, { sessionId: ctx.sessionId, deviceId: ctx.deviceId }); setBusy(false); }}>Cancel task</button>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ goal + subtasks */
const SUB_LABEL: Record<string, string> = { todo: 'To do', in_progress: 'In progress', done: 'Done' };
const GOAL_LABEL: Record<string, string> = { not_started: 'Not started', in_progress: 'In progress', partially_complete: 'Partly done', likely_complete: 'Likely done', confirmed_complete: 'Done' };

export function GoalPanel({ slice }: { slice: SessionSlice }) {
  const subs = useMemo(() => Object.values(slice.subtasks).sort((a: Subtask, b: Subtask) => a.position - b.position), [slice.subtasks]);
  const done = subs.filter((s) => s.status === 'done').length;
  return (
    <section className="card goal" aria-label="Goal and subtasks">
      <header className="card-head">
        <h3>Goal</h3>
        <Chip tone={slice.goal.state === 'confirmed_complete' || slice.goal.state === 'likely_complete' ? 'ok' : 'neutral'}>{GOAL_LABEL[slice.goal.state] ?? slice.goal.state}</Chip>
      </header>
      <p className="goal-text">{slice.goal.text || slice.session?.goal}</p>
      {slice.goal.version > 1 && <p className="small muted">Version {slice.goal.version}</p>}
      {subs.length > 0 ? (
        <>
          <p className="small muted">{done} of {subs.length} subtasks done</p>
          <ul className="subtasks">
            {subs.map((s) => (
              <li key={s.id} className={`sub sub-${s.status}`}>
                <i aria-hidden="true">{s.status === 'done' && <Icon name="check" size={12} />}</i>
                <span>{s.title}</span>
                <span className="sr-only">{SUB_LABEL[s.status]}</span>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="muted small">No subtasks yet. FLOW adds them as it learns what the goal involves.</p>}
    </section>
  );
}

/* ------------------------------------------------------------------ voice */
export function VoicePanel({ slice }: { slice: SessionSlice }) {
  const now = useNow(5000);
  const cards = useMemo(() => transcript(slice).slice(-8), [slice.events, slice.chats]); // eslint-disable-line react-hooks/exhaustive-deps
  const left = slice.voice.state === 'muted' ? untilLabel(slice.voice.muted_until, now) : null;
  const state = slice.voice.state === 'unavailable' ? ['Unavailable', 'bad'] : slice.voice.state === 'muted' ? [left ? `Quiet for ${left}` : 'Muted', 'warn'] : ['Ready', 'ok'];
  return (
    <section className="card voice" aria-label="Voice and transcript">
      <header className="card-head">
        <h3>Voice</h3>
        <Chip tone={state[1] as 'ok'}>{state[0]}</Chip>
      </header>
      {cards.length === 0 ? <p className="muted small">When FLOW speaks up, or answers a question you ask, it is written here.</p> : (
        <ul className="transcript">
          {cards.map((c) => (
            <li key={c.id} className={`say say-${c.kind}`}>
              {c.kind === 'ask' ? (
                <>
                  <p className="say-q"><Icon name="chat" size={14} />{c.question}</p>
                  {c.answer ? <p className="say-a">{c.answer}</p> : <p className="say-a muted">FLOW is answering</p>}
                </>
              ) : <p className="say-a"><Icon name="volume" size={14} />{c.text}</p>}
              <time className="small muted" dateTime={c.ts}>{clockOrEmpty(c.ts)}</time>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
