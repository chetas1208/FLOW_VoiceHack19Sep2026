// One normalized store, keyed by session. Every mutation is idempotent and order independent:
//  - events are deduped by event_id and kept sorted by sequence (ties broken by event_id);
//  - derived "current" state only moves forward (per-field sequence guard) so replays and out-of-order
//    frames never roll the UI back;
//  - entities (tasks, approvals, recommendations, subtasks, chats) are guarded by revision, then sequence;
//  - command status only moves forward (queued < delivered < running < terminal).
import type {
  ActionApproval, ActionRecommendation, ChatMessage, CurrentActivity, DelegatedTask, Device, Entity, FlowEvent,
  GoalState, LiveView, Metrics, Presence, SessionCommand, SessionOut, Subtask,
} from '../lib/types';

export const MAX_EVENTS = 1500;
export const MAX_TREND = 240;

export type ConnStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'unauthorized';

export interface ToolEntry {
  key: string;
  seq: number;
  task_id: string;
  tool: string;
  args_summary?: string;
  state: 'running' | 'done' | 'failed';
  exit_code?: number | null;
  summary?: string;
  started_at?: string;
  ended_at?: string;
}

export interface TrendPoint { seq: number; ts: string; score: number }

export interface VoiceState { state: string; muted_until?: string | null }

export interface SessionSlice {
  id: string;
  session?: SessionOut;
  presence?: Presence;
  hydrated: boolean;
  conn: ConnStatus;
  events: FlowEvent[]; // sorted by (sequence, event_id)
  seen: Record<string, true>; // event_id
  seqs: Record<number, true>;
  contiguous: number; // highest N such that every sequence 1..N is present (or covered by a hydrated floor)
  highest: number;
  current: CurrentActivity;
  metrics: Metrics;
  efficiency: Record<string, unknown>;
  trend: TrendPoint[];
  voice: VoiceState;
  goal: { text: string; version: number; state: GoalState };
  subtasks: Record<string, Subtask>;
  tasks: Record<string, DelegatedTask>;
  approvals: Record<string, ActionApproval>;
  recommendations: Record<string, ActionRecommendation>;
  chats: Record<string, ChatMessage>;
  tools: Record<string, ToolEntry[]>; // by task id
  fieldSeq: Record<string, number>;
  entSeq: Record<string, number>;
}

export interface AppState {
  sessions: Record<string, SessionSlice>;
  sessionIndex: Record<string, SessionOut>; // summaries for history / start flow
  devices: Record<string, Device>;
  devicesLoaded: boolean;
  commands: Record<string, SessionCommand>;
  inbox: Record<string, ActionApproval>; // pending approvals, user wide
  inboxLoaded: boolean;
  userConn: ConnStatus;
}

export const initialState: AppState = {
  sessions: {}, sessionIndex: {}, devices: {}, devicesLoaded: false, commands: {}, inbox: {}, inboxLoaded: false,
  userConn: 'idle',
};

export type Action =
  | { type: 'store/reset' }
  | { type: 'session/hydrate'; live: LiveView }
  | { type: 'session/events'; sessionId: string; events: FlowEvent[]; floor?: number }
  | { type: 'session/presence'; sessionId: string; presence: Presence }
  | { type: 'session/conn'; sessionId: string; conn: ConnStatus }
  | { type: 'session/upsert'; session: SessionOut }
  | { type: 'session/entities'; sessionId: string; items: Entity[] }
  | { type: 'commands/upsert'; commands: SessionCommand[] }
  | { type: 'command/local'; command: SessionCommand }
  | { type: 'devices/set'; devices: Device[] }
  | { type: 'device/presence'; deviceId: string; presence: Presence }
  | { type: 'device/remove'; deviceId: string }
  | { type: 'approval/upsert'; approval: ActionApproval }
  | { type: 'approvals/set'; approvals: ActionApproval[] }
  | { type: 'user/conn'; conn: ConnStatus };

const emptySlice = (id: string): SessionSlice => ({
  id, hydrated: false, conn: 'idle', events: [], seen: {}, seqs: {}, contiguous: 0, highest: 0, current: {}, metrics: {},
  efficiency: {}, trend: [], voice: { state: 'ready' }, goal: { text: '', version: 0, state: 'not_started' },
  subtasks: {}, tasks: {}, approvals: {}, recommendations: {}, chats: {}, tools: {}, fieldSeq: {}, entSeq: {},
});

const cmpEvent = (a: FlowEvent, b: FlowEvent) => a.sequence - b.sequence || (a.event_id < b.event_id ? -1 : a.event_id > b.event_id ? 1 : 0);

const COMMAND_RANK: Record<string, number> = { queued: 0, delivered: 1, running: 2, succeeded: 3, failed: 3, denied: 3, expired: 3, cancelled: 3 };
export const isTerminalCommand = (s: string) => (COMMAND_RANK[s] ?? 0) >= 3;

export function mergeCommand(prev: SessionCommand | undefined, next: SessionCommand): SessionCommand {
  if (!prev) return next;
  const pr = COMMAND_RANK[prev.status] ?? 0;
  const nr = COMMAND_RANK[next.status] ?? 0;
  if (nr > pr) return { ...prev, ...next };
  // same or lower rank: keep status, but learn missing metadata/result
  if (nr === pr && !isTerminalCommand(prev.status) && next.result && !prev.result) return { ...prev, result: next.result };
  return prev;
}

// ---------------------------------------------------------------------------------------------
function acceptField(s: SessionSlice, name: string, seq: number): boolean {
  if ((s.fieldSeq[name] ?? -1) >= seq && seq > 0) return false;
  if (seq === 0 && name in s.fieldSeq) return false;
  return true;
}
function stamp(s: SessionSlice, name: string, seq: number) {
  s.fieldSeq = { ...s.fieldSeq, [name]: Math.max(seq, s.fieldSeq[name] ?? 0) };
}

function acceptEntity(s: SessionSlice, kind: string, id: string, existing: { revision?: number } | undefined, revision: number | undefined, seq: number): boolean {
  if (!existing) return true;
  const rev = revision ?? 0, prev = existing.revision ?? 0;
  if (rev > prev) return true;
  if (rev < prev) return false;
  return seq > (s.entSeq[`${kind}:${id}`] ?? 0);
}
function markEntity(s: SessionSlice, kind: string, id: string, seq: number) {
  s.entSeq = { ...s.entSeq, [`${kind}:${id}`]: Math.max(seq, s.entSeq[`${kind}:${id}`] ?? 0) };
}

function upsertTask(s: SessionSlice, task: DelegatedTask, seq: number) {
  if (!task?.id || !acceptEntity(s, 'task', task.id, s.tasks[task.id], task.revision, seq)) return;
  s.tasks = { ...s.tasks, [task.id]: task };
  markEntity(s, 'task', task.id, seq);
}
function upsertApproval(s: SessionSlice, approval: ActionApproval, seq: number) {
  if (!approval?.id || !acceptEntity(s, 'approval', approval.id, s.approvals[approval.id], approval.revision, seq)) return false;
  s.approvals = { ...s.approvals, [approval.id]: approval };
  markEntity(s, 'approval', approval.id, seq);
  return true;
}
function upsertRecommendation(s: SessionSlice, rec: ActionRecommendation, seq: number) {
  if (!rec?.id || !acceptEntity(s, 'rec', rec.id, s.recommendations[rec.id], rec.revision, seq)) return;
  s.recommendations = { ...s.recommendations, [rec.id]: rec };
  markEntity(s, 'rec', rec.id, seq);
}
function upsertSubtask(s: SessionSlice, sub: Subtask, seq: number) {
  if (!sub?.id || !acceptEntity(s, 'sub', sub.id, s.subtasks[sub.id], sub.revision, seq)) return;
  s.subtasks = { ...s.subtasks, [sub.id]: sub };
  markEntity(s, 'sub', sub.id, seq);
}
function upsertChat(s: SessionSlice, chat: ChatMessage, seq: number) {
  if (!chat?.id) return;
  const prev = s.chats[chat.id];
  if (prev && prev.answer && !chat.answer) return; // never lose an answer to a late question frame
  if (prev && seq <= (s.entSeq[`chat:${chat.id}`] ?? 0) && !(chat.answer && !prev.answer)) return;
  s.chats = { ...s.chats, [chat.id]: { ...prev, ...chat } };
  markEntity(s, 'chat', chat.id, seq);
}

function pushTool(s: SessionSlice, ev: FlowEvent) {
  const d = ev.data;
  const taskId = String(d.task_id ?? '');
  if (!taskId) return;
  const list = s.tools[taskId] ? [...s.tools[taskId]] : [];
  if (ev.type === 'task.tool_started') {
    const key = `${taskId}:${d.tool}:${ev.sequence}`;
    if (list.some((t) => t.key === key)) return;
    list.push({ key, seq: ev.sequence, task_id: taskId, tool: String(d.tool ?? 'tool'), args_summary: d.args_summary, state: 'running', started_at: ev.timestamp });
  } else {
    // completion pairs with the latest still-running entry of the same tool that started before it
    const idx = [...list].reverse().findIndex((t) => t.tool === d.tool && t.state === 'running' && t.seq < ev.sequence);
    if (idx >= 0) {
      const at = list.length - 1 - idx;
      list[at] = { ...list[at], state: d.exit_code ? 'failed' : 'done', exit_code: d.exit_code ?? null, summary: d.summary, ended_at: ev.timestamp };
    } else {
      const key = `${taskId}:${d.tool}:done:${ev.sequence}`;
      if (list.some((t) => t.key === key)) return;
      list.push({ key, seq: ev.sequence, task_id: taskId, tool: String(d.tool ?? 'tool'), args_summary: d.args_summary, state: d.exit_code ? 'failed' : 'done', exit_code: d.exit_code ?? null, summary: d.summary, ended_at: ev.timestamp });
    }
  }
  list.sort((a, b) => a.seq - b.seq);
  s.tools = { ...s.tools, [taskId]: list.slice(-40) };
}

function setStatus(s: SessionSlice, status: SessionOut['status'], ts: string, seq: number, ended = false) {
  if (!s.session || !acceptField(s, 'status', seq)) return;
  s.session = { ...s.session, status, ended_at: ended ? ts : status === 'completed' ? s.session.ended_at : null, runtime_state: s.session.runtime_state ? { ...s.session.runtime_state, status } : s.session.runtime_state };
  stamp(s, 'status', seq);
}

function derive(s: SessionSlice, ev: FlowEvent, inbox: Record<string, ActionApproval>): Record<string, ActionApproval> {
  const d = ev.data ?? {};
  const seq = ev.sequence;
  switch (ev.type) {
    case 'session.started': setStatus(s, 'active', ev.timestamp, seq); break;
    case 'session.paused': setStatus(s, 'paused', ev.timestamp, seq); break;
    case 'session.resumed': setStatus(s, 'active', ev.timestamp, seq); break;
    case 'session.completed': setStatus(s, 'completed', ev.timestamp, seq, true); break;
    case 'observation.created':
      if (acceptField(s, 'obs', seq)) {
        s.current = { ...s.current, activity: d.activity ?? d.activity_summary ?? s.current.activity, task_phase: d.task_phase ?? s.current.task_phase, category: d.category ?? s.current.category, alignment: d.goal_alignment ?? s.current.alignment };
        stamp(s, 'obs', seq);
      }
      break;
    case 'drift.changed': case 'drift.entered': case 'drift.cleared':
      if (acceptField(s, 'drift', seq)) { s.current = { ...s.current, drift: String(d.to ?? d.state ?? d.drift ?? (ev.type === 'drift.cleared' ? 'focused' : 'drifting')) }; stamp(s, 'drift', seq); }
      break;
    case 'blocker.changed':
      if (acceptField(s, 'blocker', seq)) { s.current = { ...s.current, blocker: (d.blocker ?? d.text ?? null) || null }; stamp(s, 'blocker', seq); }
      break;
    case 'metrics.updated':
      if (acceptField(s, 'metrics', seq)) { s.metrics = { ...s.metrics, ...(d as Metrics) }; stamp(s, 'metrics', seq); }
      if (typeof d.session_score === 'number' && !s.trend.some((p) => p.seq === seq)) {
        const trend = [...s.trend, { seq, ts: ev.timestamp, score: d.session_score }].sort((a, b) => a.seq - b.seq);
        s.trend = trend.slice(-MAX_TREND);
      }
      break;
    case 'efficiency.updated':
      if (acceptField(s, 'efficiency', seq)) { s.efficiency = d; stamp(s, 'efficiency', seq); }
      break;
    case 'voice.state':
      if (acceptField(s, 'voice', seq)) { s.voice = { state: d.state ?? 'ready', muted_until: d.muted_until ?? null }; stamp(s, 'voice', seq); }
      break;
    case 'goal.updated':
      if (acceptField(s, 'goal', seq)) {
        s.goal = { text: d.goal ?? s.goal.text, version: d.version ?? s.goal.version, state: (d.state as GoalState) ?? s.goal.state };
        if (s.session && d.goal) s.session = { ...s.session, goal: d.goal, goal_version: d.version ?? s.session.goal_version };
        stamp(s, 'goal', seq);
      }
      break;
    case 'subtask.updated': {
      const sub = (d.subtask ?? d) as Subtask;
      upsertSubtask(s, { ...({ session_id: s.id, evidence: [], position: 0, origin: 'observed', revision: 0 } as Partial<Subtask>), ...sub }, seq);
      break;
    }
    case 'task.created': case 'task.planning': case 'task.running': case 'task.completed': case 'task.failed': case 'task.cancelled':
      if (d.task) upsertTask(s, d.task as DelegatedTask, seq);
      break;
    case 'task.tool_started': case 'task.tool_completed': pushTool(s, ev); break;
    case 'task.approval_requested': case 'task.approval_resolved':
      if (d.approval) {
        const approval = d.approval as ActionApproval;
        if (upsertApproval(s, approval, seq)) {
          const nextInbox = { ...inbox };
          if (approval.status === 'pending') nextInbox[approval.id] = approval; else delete nextInbox[approval.id];
          inbox = nextInbox;
        }
      }
      break;
    case 'recommendation.created': case 'recommendation.updated':
      if (d.recommendation) upsertRecommendation(s, d.recommendation as ActionRecommendation, seq);
      break;
    case 'chat.message': upsertChat(s, { id: d.id, question: d.question, answer: d.answer, source: d.source, answered_at: d.answer ? ev.timestamp : null, asked_at: d.asked_at }, seq); break;
    default: break;
  }
  return inbox;
}

/** Insert events into a slice (mutates the working copy `s`; caller passes a shallow clone). */
function ingest(s: SessionSlice, incoming: FlowEvent[], floor: number | undefined, inbox: Record<string, ActionApproval>): Record<string, ActionApproval> {
  const fresh: FlowEvent[] = [];
  const batch = new Set<string>();
  for (const ev of incoming) {
    if (!ev || typeof ev.event_id !== 'string' || typeof ev.sequence !== 'number') continue;
    if (s.seen[ev.event_id] || batch.has(ev.event_id)) continue;
    batch.add(ev.event_id);
    fresh.push(ev);
  }
  if (floor && floor > s.contiguous) s.contiguous = floor;
  if (fresh.length === 0) { advance(s); return inbox; }
  const seen = { ...s.seen }, seqs = { ...s.seqs };
  for (const ev of fresh) { seen[ev.event_id] = true; seqs[ev.sequence] = true; }
  s.seen = seen; s.seqs = seqs;
  const merged = s.events.concat(fresh).sort(cmpEvent);
  s.events = merged.length > MAX_EVENTS ? merged.slice(merged.length - MAX_EVENTS) : merged;
  // derived state applies in sequence order so that same-batch replays converge with one-by-one delivery
  for (const ev of [...fresh].sort(cmpEvent)) {
    if (ev.sequence > s.highest) s.highest = ev.sequence;
    inbox = derive(s, ev, inbox);
  }
  advance(s);
  return inbox;
}

function advance(s: SessionSlice) {
  let c = s.contiguous;
  while (s.seqs[c + 1]) c++;
  s.contiguous = c;
}

function withSlice(state: AppState, id: string, fn: (s: SessionSlice) => void): AppState {
  const s = { ...(state.sessions[id] ?? { ...emptySlice(id), session: state.sessionIndex[id] }) };
  fn(s);
  return { ...state, sessions: { ...state.sessions, [id]: s } };
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'store/reset': return initialState;

    case 'session/hydrate': {
      const live = action.live;
      const seq = live.last_event_sequence ?? 0;
      let inbox = state.inbox;
      const next = withSlice(state, live.session.id, (s) => {
        s.session = mergeSession(s.session, live.session);
        s.presence = live.presence ?? s.presence;
        s.hydrated = true;
        if (acceptField(s, 'obs', seq)) { s.current = { ...s.current, ...live.current }; stamp(s, 'obs', seq); }
        if (acceptField(s, 'metrics', seq)) { s.metrics = live.metrics ?? {}; stamp(s, 'metrics', seq); }
        if (acceptField(s, 'efficiency', seq)) { s.efficiency = live.efficiency ?? {}; stamp(s, 'efficiency', seq); }
        if (acceptField(s, 'voice', seq)) { s.voice = { state: live.voice?.state ?? 'ready', muted_until: live.voice?.muted_until ?? null }; stamp(s, 'voice', seq); }
        if (acceptField(s, 'goal', seq)) { s.goal = { text: live.goal?.text ?? live.session.goal, version: live.goal?.version ?? 1, state: live.goal?.state ?? 'in_progress' }; stamp(s, 'goal', seq); }
        if (acceptField(s, 'status', seq)) stamp(s, 'status', seq);
        for (const sub of live.goal?.subtasks ?? []) upsertSubtask(s, sub, 0);
        for (const t of live.tasks ?? []) upsertTask(s, t, 0);
        for (const a of live.approvals ?? []) {
          if (upsertApproval(s, a, 0)) { inbox = { ...inbox }; if (a.status === 'pending') inbox[a.id] = a; else delete inbox[a.id]; }
        }
        if (live.recommendation) upsertRecommendation(s, live.recommendation, 0);
        if (seq > s.highest) s.highest = seq;
      });
      return { ...next, inbox, sessionIndex: { ...next.sessionIndex, [live.session.id]: mergeSession(next.sessionIndex[live.session.id], live.session) } };
    }

    case 'session/events': {
      let inbox = state.inbox;
      const next = withSlice(state, action.sessionId, (s) => { inbox = ingest(s, action.events, action.floor, inbox); });
      return inbox === state.inbox ? next : { ...next, inbox };
    }

    case 'session/presence':
      return withSlice(state, action.sessionId, (s) => { s.presence = action.presence; });

    case 'session/conn':
      return withSlice(state, action.sessionId, (s) => { s.conn = action.conn; });

    case 'session/upsert': {
      const sess = action.session;
      const merged = mergeSession(state.sessionIndex[sess.id], sess);
      const next: AppState = { ...state, sessionIndex: { ...state.sessionIndex, [sess.id]: merged } };
      if (state.sessions[sess.id]) return withSlice(next, sess.id, (s) => { s.session = mergeSession(s.session, sess); });
      return next;
    }

    case 'session/entities': {
      return withSlice(state, action.sessionId, (s) => {
        for (const item of action.items) {
          const data: any = item.data;
          if (item.kind === 'chat') upsertChat(s, { ...data, id: data?.id ?? item.id }, 0);
          else if (item.kind === 'task') upsertTask(s, { ...data, revision: data.revision ?? item.revision }, 0);
          else if (item.kind === 'recommendation') upsertRecommendation(s, { ...data, revision: data.revision ?? item.revision }, 0);
          else if (item.kind === 'subtask') upsertSubtask(s, { ...data, revision: data.revision ?? item.revision }, 0);
        }
      });
    }

    case 'commands/upsert': {
      const commands = { ...state.commands };
      for (const c of action.commands) commands[c.command_id] = mergeCommand(commands[c.command_id], c);
      return { ...state, commands };
    }
    case 'command/local':
      return { ...state, commands: { ...state.commands, [action.command.command_id]: mergeCommand(state.commands[action.command.command_id], action.command) } };

    case 'devices/set': {
      const devices: Record<string, Device> = {};
      for (const d of action.devices) devices[d.id] = d;
      return { ...state, devices, devicesLoaded: true };
    }
    case 'device/presence': {
      const d = state.devices[action.deviceId];
      if (!d) return state;
      return { ...state, devices: { ...state.devices, [d.id]: { ...d, presence: { ...d.presence, ...action.presence }, last_seen_at: action.presence.last_heartbeat_at ?? d.last_seen_at } } };
    }
    case 'device/remove': {
      const devices = { ...state.devices }; delete devices[action.deviceId];
      return { ...state, devices };
    }

    case 'approval/upsert': {
      const a = action.approval;
      let next = state;
      if (state.sessions[a.session_id]) next = withSlice(state, a.session_id, (s) => { upsertApproval(s, a, 0); });
      const known = state.inbox[a.id];
      if (known && (known.revision ?? 0) > (a.revision ?? 0)) return next;
      const inbox = { ...next.inbox };
      if (a.status === 'pending') inbox[a.id] = a; else delete inbox[a.id];
      return { ...next, inbox };
    }
    case 'approvals/set': {
      const inbox: Record<string, ActionApproval> = {};
      for (const a of action.approvals) if (a.status === 'pending') inbox[a.id] = a;
      return { ...state, inbox, inboxLoaded: true };
    }
    case 'user/conn': return { ...state, userConn: action.conn };
    default: return state;
  }
}

function mergeSession(prev: SessionOut | undefined, next: SessionOut): SessionOut {
  if (!prev) return next;
  const pu = prev.updated_at ?? '', nu = next.updated_at ?? '';
  if (pu && nu && nu < pu) return prev;
  return { ...prev, ...next };
}
