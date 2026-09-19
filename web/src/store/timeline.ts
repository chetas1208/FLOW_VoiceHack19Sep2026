import type { FlowEvent } from '../lib/types';

export type Lane = 'human' | 'agent' | 'system';
export type Tone = 'core' | 'support' | 'neutral' | 'distraction' | 'info' | 'ok' | 'warn' | 'bad';

export interface TimelineItem {
  id: string;
  lane: Lane;
  seq: number;
  ts: string;
  tone: Tone;
  kind: string;
  title: string;
  detail?: string;
  count: number;
}

const CATEGORY_TONE: Record<string, Tone> = {
  core_task: 'core', supporting_task: 'support', neutral: 'neutral', distraction: 'distraction', unknown: 'neutral',
};

export const CATEGORY_LABEL: Record<string, string> = {
  core_task: 'On goal', supporting_task: 'Supporting', neutral: 'Neutral', distraction: 'Off goal', unknown: 'Unclear',
};

/** Which lane an event belongs to. Agent = anything FLOW's agent or voice did; human = what the person did. */
export function laneOf(ev: FlowEvent): Lane | null {
  const t = ev.type;
  if (t === 'observation.created') {
    const d = ev.data ?? {};
    const actor = String(d.actor ?? d.source ?? '');
    return /agent/i.test(actor) || /agent/i.test(String(d.activity_type ?? '')) ? 'agent' : 'human';
  }
  if (t.startsWith('task.') || t.startsWith('recommendation.') || t === 'chat.message' || t.startsWith('intervention.')) return 'agent';
  if (t === 'subtask.updated' || t === 'blocker.changed') return 'human';
  if (t.startsWith('session.') || t.startsWith('drift.') || t === 'goal.updated' || t === 'voice.state') return 'system';
  return null;
}

function toItem(ev: FlowEvent): TimelineItem | null {
  const lane = laneOf(ev);
  if (!lane) return null;
  const d = ev.data ?? {};
  const base = { id: ev.event_id, lane, seq: ev.sequence, ts: ev.timestamp, count: 1, kind: ev.type };
  switch (ev.type) {
    case 'observation.created': {
      const category = String(d.category ?? 'unknown');
      return { ...base, tone: CATEGORY_TONE[category] ?? 'neutral', title: String(d.activity ?? d.activity_summary ?? 'Activity'), detail: [d.application, d.task_phase].filter(Boolean).join(' / ') || undefined };
    }
    case 'blocker.changed':
      return d.blocker || d.text ? { ...base, tone: 'warn', title: 'Blocked', detail: String(d.blocker ?? d.text) } : { ...base, tone: 'ok', title: 'Blocker cleared' };
    case 'subtask.updated': {
      const sub = d.subtask ?? d;
      if (sub.status !== 'done') return null;
      return { ...base, tone: 'ok', title: 'Finished a subtask', detail: sub.title };
    }
    case 'session.started': return { ...base, tone: 'info', title: 'Session started' };
    case 'session.paused': return { ...base, tone: 'warn', title: 'Session paused' };
    case 'session.resumed': return { ...base, tone: 'info', title: 'Session resumed' };
    case 'session.completed': return { ...base, tone: 'ok', title: 'Session completed' };
    case 'drift.entered': return { ...base, tone: 'distraction', title: 'Drifting from goal' };
    case 'drift.cleared': return { ...base, tone: 'ok', title: 'Back on goal' };
    case 'goal.updated': return { ...base, tone: 'info', title: `Goal changed (v${d.version ?? '?'})`, detail: d.goal };
    case 'voice.state': return { ...base, tone: 'neutral', title: d.state === 'muted' ? 'Voice muted' : d.state === 'unavailable' ? 'Voice unavailable' : 'Voice ready' };
    case 'intervention.delivered': return { ...base, tone: 'info', title: 'FLOW said', detail: d.message };
    case 'intervention.proposed': return null;
    case 'recommendation.created': return { ...base, tone: 'info', title: 'Recommends', detail: d.recommendation?.title };
    case 'recommendation.updated': {
      const st = d.recommendation?.status;
      if (st === 'accepted' || st === 'dismissed') return { ...base, tone: 'neutral', title: st === 'accepted' ? 'Recommendation accepted' : 'Recommendation dismissed', detail: d.recommendation?.title };
      return null;
    }
    case 'chat.message': return { ...base, tone: 'info', title: 'Answered you', detail: d.question };
    case 'task.created': return { ...base, tone: 'info', title: 'Task queued', detail: d.task?.instruction };
    case 'task.planning': return { ...base, tone: 'info', title: 'Planning', detail: d.task?.instruction };
    case 'task.running': return { ...base, tone: 'info', title: 'Task running', detail: d.task?.instruction };
    case 'task.tool_started': return { ...base, tone: 'neutral', title: `Running ${d.tool ?? 'tool'}`, detail: d.args_summary };
    case 'task.tool_completed': return { ...base, tone: d.exit_code ? 'bad' : 'ok', title: `${d.tool ?? 'Tool'} ${d.exit_code ? 'failed' : 'finished'}`, detail: d.summary };
    case 'task.approval_requested': return { ...base, tone: 'warn', title: 'Needs your approval', detail: d.approval?.action?.summary };
    case 'task.approval_resolved': return { ...base, tone: d.approval?.status === 'approved' ? 'ok' : 'bad', title: d.approval?.status === 'approved' ? 'Approved' : 'Denied', detail: d.approval?.action?.summary };
    case 'task.completed': return { ...base, tone: 'ok', title: 'Task completed', detail: d.task?.result?.summary ?? d.task?.instruction };
    case 'task.failed': return { ...base, tone: 'bad', title: 'Task failed', detail: d.task?.error ?? d.task?.instruction };
    case 'task.cancelled': return { ...base, tone: 'neutral', title: 'Task cancelled', detail: d.task?.instruction };
    default: return null;
  }
}

const cache = new WeakMap<FlowEvent[], TimelineItem[]>();

/** Chronological (sequence) timeline. Consecutive identical human activity is collapsed into one row with a count. */
export function buildTimeline(events: FlowEvent[]): TimelineItem[] {
  const hit = cache.get(events);
  if (hit) return hit;
  const out: TimelineItem[] = [];
  for (const ev of events) {
    const item = toItem(ev);
    if (!item) continue;
    const prev = out[out.length - 1];
    if (prev && item.kind === 'observation.created' && prev.kind === 'observation.created' && prev.lane === item.lane && prev.title === item.title && prev.tone === item.tone) {
      out[out.length - 1] = { ...prev, count: prev.count + 1, ts: item.ts, seq: item.seq };
      continue;
    }
    out.push(item);
  }
  cache.set(events, out);
  return out;
}
