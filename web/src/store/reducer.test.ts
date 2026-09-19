import { describe, expect, it } from 'vitest';
import { initialState, reducer, type AppState } from './reducer';
import { buildTimeline } from './timeline';
import { currentRecommendation, pendingApprovals } from './selectors';
import type { ActionApproval, DelegatedTask, FlowEvent, LiveView, SessionCommand } from '../lib/types';

const SID = 'ses_test_0001';
const ev = (sequence: number, type: string, data: Record<string, any> = {}): FlowEvent => ({
  event_id: `evt_${SID}_${sequence}`, sequence, type, timestamp: new Date(1_700_000_000_000 + sequence * 1000).toISOString(), data,
});
const apply = (state: AppState, events: FlowEvent[], floor?: number) => reducer(state, { type: 'session/events', sessionId: SID, events, floor });
const slice = (s: AppState) => s.sessions[SID]!;

const metrics = (seq: number, score: number) => ev(seq, 'metrics.updated', { session_score: score, goal_alignment: score });
const task = (revision: number, status: DelegatedTask['status']): DelegatedTask => ({
  id: 'tsk_1', session_id: SID, instruction: 'Run the tests', status, created_from: 'web', created_at: '2026-09-19T10:00:00Z',
  permission_level: 'safe_execute', plan: [], evidence: [], revision,
});
const approval = (revision: number, status: ActionApproval['status']): ActionApproval => ({
  id: 'apr_1', session_id: SID, task_id: 'tsk_1', action: { summary: 'Run pytest' }, risk: 'low', requested_at: '2026-09-19T10:00:00Z',
  status, permission_level: 'safe_execute', revision,
});

describe('event ingestion', () => {
  it('dedupes by event_id, including within one batch and across frames', () => {
    let s = apply(initialState, [ev(1, 'observation.created', { activity: 'Coding' }), ev(1, 'observation.created', { activity: 'Coding' })]);
    s = apply(s, [ev(1, 'observation.created', { activity: 'Coding' })]);
    expect(slice(s).events).toHaveLength(1);
  });

  it('keeps events sorted by sequence when they arrive out of order', () => {
    const s = apply(initialState, [ev(3, 'observation.created'), ev(1, 'observation.created'), ev(2, 'observation.created')]);
    expect(slice(s).events.map((e) => e.sequence)).toEqual([1, 2, 3]);
    const s2 = apply(apply(initialState, [ev(5, 'observation.created')]), [ev(4, 'observation.created')]);
    expect(slice(s2).events.map((e) => e.sequence)).toEqual([4, 5]);
  });

  it('tracks the contiguous sequence so reconnects replay gaps, and fills it when the gap arrives', () => {
    let s = apply(initialState, [ev(1, 'observation.created'), ev(2, 'observation.created'), ev(4, 'observation.created')]);
    expect(slice(s).contiguous).toBe(2);
    expect(slice(s).highest).toBe(4);
    s = apply(s, [ev(3, 'observation.created')]);
    expect(slice(s).contiguous).toBe(4);
  });

  it('honours a hydrated floor', () => {
    const s = apply(initialState, [ev(101, 'observation.created'), ev(102, 'observation.created')], 100);
    expect(slice(s).contiguous).toBe(102);
  });

  it('converges to the same state for any delivery order', () => {
    const events = [
      ev(1, 'session.started'), ev(2, 'observation.created', { activity: 'A', category: 'core_task' }), metrics(3, 0.4),
      ev(4, 'task.created', { task: task(1, 'queued') }), ev(5, 'observation.created', { activity: 'B', category: 'distraction' }),
      metrics(6, 0.7), ev(7, 'task.running', { task: task(2, 'running') }), ev(8, 'voice.state', { state: 'muted', muted_until: '2026-09-19T11:00:00Z' }),
      ev(9, 'session.paused'), ev(10, 'goal.updated', { version: 2, goal: 'New goal', source: 'web' }),
    ];
    const forward = apply(initialState, events);
    const shuffled = [...events].sort((a, b) => ((a.sequence * 7) % 11) - ((b.sequence * 7) % 11));
    const backward = apply(initialState, [...events].reverse());
    let oneByOne = initialState;
    for (const e of shuffled) oneByOne = apply(oneByOne, [e, e]);
    for (const other of [backward, oneByOne]) {
      const a = slice(forward), b = slice(other);
      expect(b.events).toEqual(a.events);
      expect(b.metrics).toEqual(a.metrics);
      expect(b.current).toEqual(a.current);
      expect(b.tasks).toEqual(a.tasks);
      expect(b.voice).toEqual(a.voice);
      expect(b.goal).toEqual(a.goal);
      expect(b.trend).toEqual(a.trend);
    }
    expect(slice(forward).metrics.session_score).toBe(0.7);
    expect(slice(forward).current.activity).toBe('B');
    expect(slice(forward).tasks['tsk_1']!.status).toBe('running');
    expect(slice(forward).goal.text).toBe('New goal');
  });

  it('a replayed old metrics event never rolls the score back', () => {
    let s = apply(initialState, [metrics(10, 0.9)]);
    s = apply(s, [metrics(4, 0.2)]);
    expect(slice(s).metrics.session_score).toBe(0.9);
    expect(slice(s).trend.map((p) => p.seq)).toEqual([4, 10]);
  });

  it('a live snapshot is not overwritten by older replayed events but is by newer ones', () => {
    const live = {
      session: { id: SID, goal: 'g', status: 'active', device_id: 'dev_1', started_at: '2026-09-19T10:00:00Z' },
      presence: { state: 'online' }, current: { activity: 'Snapshot activity' }, metrics: { session_score: 0.5 }, voice: { state: 'ready' },
      agent: { status: 'idle', pending_approvals: 0 }, goal: { text: 'g', version: 1, state: 'in_progress', subtasks: [] },
      recommendation: null, tasks: [], approvals: [], last_event_sequence: 50,
    } as unknown as LiveView;
    let s = reducer(initialState, { type: 'session/hydrate', live });
    s = apply(s, [ev(40, 'observation.created', { activity: 'Old' }), metrics(41, 0.1)], 30);
    expect(slice(s).current.activity).toBe('Snapshot activity');
    expect(slice(s).metrics.session_score).toBe(0.5);
    s = apply(s, [ev(51, 'observation.created', { activity: 'Fresh' })]);
    expect(slice(s).current.activity).toBe('Fresh');
  });

  it('drops state from stale entity revisions', () => {
    let s = apply(initialState, [ev(8, 'task.completed', { task: task(3, 'completed') })]);
    s = apply(s, [ev(5, 'task.running', { task: task(2, 'running') })]);
    expect(slice(s).tasks['tsk_1']!.status).toBe('completed');
  });

  it('keeps the user-wide approvals inbox in sync with approval events, in any order', () => {
    let s = apply(initialState, [ev(2, 'task.approval_resolved', { approval: approval(2, 'approved') })]);
    s = apply(s, [ev(1, 'task.approval_requested', { approval: approval(1, 'pending') })]);
    expect(Object.keys(s.inbox)).toHaveLength(0);
    expect(pendingApprovals(slice(s))).toHaveLength(0);
    const s2 = apply(initialState, [ev(1, 'task.approval_requested', { approval: approval(1, 'pending') })]);
    expect(Object.keys(s2.inbox)).toEqual(['apr_1']);
  });

  it('pairs tool_started with tool_completed', () => {
    const s = apply(initialState, [
      ev(2, 'task.tool_completed', { task_id: 'tsk_1', tool: 'pytest', exit_code: 0, summary: '42 passed' }),
      ev(1, 'task.tool_started', { task_id: 'tsk_1', tool: 'pytest', args_summary: '-q' }),
    ]);
    const tools = slice(s).tools['tsk_1']!;
    expect(tools).toHaveLength(1);
    expect(tools[0]).toMatchObject({ state: 'done', summary: '42 passed' });
  });

  it('applies only the newest pending recommendation', () => {
    const rec = (id: string, created: string, revision = 1) => ({ id, session_id: SID, type: 'RUN_VALIDATION', title: id, description: '', reason: '', evidence: [], confidence: 0.8, impact_estimate: 'medium', requires_user_action: true, can_delegate: true, level: 'suggest', status: 'pending', created_at: created, revision });
    const s = apply(initialState, [ev(1, 'recommendation.created', { recommendation: rec('r1', '2026-09-19T10:00:00Z') }), ev(2, 'recommendation.created', { recommendation: rec('r2', '2026-09-19T10:05:00Z') })]);
    expect(currentRecommendation(slice(s))!.id).toBe('r2');
  });

  it('session status follows the highest-sequence lifecycle event', () => {
    const base = reducer(initialState, { type: 'session/upsert', session: { id: SID, goal: 'g', status: 'active', device_id: 'd', started_at: 'x' } });
    let s = apply(base, [ev(9, 'session.resumed'), ev(3, 'session.paused')]);
    expect(slice(s).session!.status).toBe('active');
    s = apply(s, [ev(12, 'session.completed')]);
    expect(slice(s).session!.status).toBe('completed');
  });
});

describe('commands', () => {
  const cmd = (status: SessionCommand['status']): SessionCommand => ({ command_id: 'cmd_1', type: 'PAUSE', device_id: 'd', source: 'web', status, payload: {}, created_at: '2026-09-19T10:00:00Z' });
  it('only moves forward and terminal is final', () => {
    let s = reducer(initialState, { type: 'commands/upsert', commands: [cmd('running')] });
    s = reducer(s, { type: 'commands/upsert', commands: [cmd('delivered')] });
    expect(s.commands['cmd_1']!.status).toBe('running');
    s = reducer(s, { type: 'commands/upsert', commands: [cmd('succeeded')] });
    s = reducer(s, { type: 'commands/upsert', commands: [cmd('running'), cmd('failed')] });
    expect(s.commands['cmd_1']!.status).toBe('succeeded');
  });
});

describe('timeline', () => {
  it('splits human and agent lanes and collapses repeated activity', () => {
    const events = [
      ev(1, 'observation.created', { activity: 'Editing parser.ts', category: 'core_task' }),
      ev(2, 'observation.created', { activity: 'Editing parser.ts', category: 'core_task' }),
      ev(3, 'observation.created', { activity: 'Editing parser.ts', category: 'core_task' }),
      ev(4, 'task.running', { task: task(1, 'running') }),
      ev(5, 'metrics.updated', { session_score: 0.5 }),
      ev(6, 'drift.entered', {}),
    ];
    const items = buildTimeline(events);
    expect(items.map((i) => i.lane)).toEqual(['human', 'agent', 'system']);
    expect(items[0]!.count).toBe(3);
  });
});
