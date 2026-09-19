import type { ActionApproval, ActionRecommendation, DelegatedTask, PresenceState } from '../lib/types';
import type { AppState, SessionSlice } from './reducer';

export const selectSlice = (state: AppState, id: string): SessionSlice | undefined => state.sessions[id];

export function pendingApprovals(s: SessionSlice): ActionApproval[] {
  return Object.values(s.approvals).filter((a) => a.status === 'pending').sort((a, b) => a.requested_at.localeCompare(b.requested_at));
}

export function currentRecommendation(s: SessionSlice): ActionRecommendation | null {
  const pending = Object.values(s.recommendations).filter((r) => r.status === 'pending');
  pending.sort((a, b) => b.created_at.localeCompare(a.created_at));
  return pending[0] ?? null;
}

const ACTIVE_TASK: DelegatedTask['status'][] = ['running', 'waiting_for_approval', 'planning', 'queued'];

/** The task to feature: the newest active one, otherwise the most recent finished one. */
export function featuredTask(s: SessionSlice): DelegatedTask | null {
  const tasks = Object.values(s.tasks).sort((a, b) => b.created_at.localeCompare(a.created_at));
  return tasks.find((t) => ACTIVE_TASK.includes(t.status)) ?? tasks[0] ?? null;
}

export function agentStatus(s: SessionSlice): 'idle' | 'working' | 'needs_approval' {
  if (pendingApprovals(s).length) return 'needs_approval';
  return Object.values(s.tasks).some((t) => ['running', 'planning', 'queued'].includes(t.status)) ? 'working' : 'idle';
}

export interface TranscriptCard { id: string; kind: 'voice' | 'ask'; ts: string; text: string; question?: string; answer?: string | null }

export function transcript(s: SessionSlice): TranscriptCard[] {
  const cards: TranscriptCard[] = [];
  for (const ev of s.events) {
    if (ev.type === 'intervention.delivered' && ev.data?.message) cards.push({ id: ev.event_id, kind: 'voice', ts: ev.timestamp, text: String(ev.data.message) });
  }
  for (const c of Object.values(s.chats)) {
    cards.push({ id: c.id, kind: 'ask', ts: c.answered_at ?? c.asked_at ?? '', text: c.answer ?? '', question: c.question, answer: c.answer });
  }
  return cards.sort((a, b) => a.ts.localeCompare(b.ts));
}

export function presenceOf(state: AppState, s: SessionSlice | undefined): PresenceState {
  const dev = s?.session ? state.devices[s.session.device_id] : undefined;
  return s?.presence?.state ?? dev?.presence?.state ?? 'offline';
}
