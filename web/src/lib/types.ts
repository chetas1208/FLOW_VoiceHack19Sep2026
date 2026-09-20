// Wire types. Mirrors docs/flow/cloud-contract.md and services/flow/remote_models.py (to_dict output).

export type PresenceState = 'online' | 'degraded' | 'offline';
export type HealthLevel = 'ok' | 'warn' | 'error' | 'unknown' | string;

export interface Presence {
  state: PresenceState;
  last_heartbeat_at?: string | null;
  health?: Record<string, HealthLevel | Record<string, unknown>>;
  active_sessions?: string[];
}

export interface Device {
  id: string;
  name: string;
  os: string;
  architecture: string;
  flow_version: string;
  created_at: string;
  last_seen_at?: string | null;
  revoked_at?: string | null;
  presence: Presence;
}

export type RuntimeStatus =
  | 'starting' | 'active' | 'paused' | 'waiting_for_user' | 'executing_delegated_task'
  | 'recovering' | 'completed' | 'failed' | 'offline';

export type PermissionPolicy = 'manual' | 'safe_auto' | 'read_only';
export type PermissionLevel = 'read_only' | 'safe_execute' | 'write_project' | 'external_network' | 'destructive';

export interface RuntimeState {
  status: RuntimeStatus;
  observer?: string;
  vision?: string;
  voice?: string;
  agent?: string;
  voice_muted_until?: string | null;
  permission_policy?: PermissionPolicy;
  goal_version?: number;
  goal_state?: GoalState;
}

export interface SessionOut {
  id: string;
  goal: string;
  status: RuntimeStatus;
  device_id: string;
  device_name?: string;
  started_at: string;
  ended_at?: string | null;
  updated_at?: string;
  runtime_state?: RuntimeState | null;
  goal_version?: number;
}

export type CommandType =
  | 'START' | 'PAUSE' | 'RESUME' | 'STOP' | 'UPDATE_GOAL' | 'REQUEST_STATUS' | 'MUTE_VOICE' | 'UNMUTE_VOICE'
  | 'REQUEST_SUMMARY' | 'ADD_TASK' | 'CANCEL_TASK' | 'APPROVE_ACTION' | 'DENY_ACTION' | 'EXECUTE_RECOMMENDATION'
  | 'ASK' | 'DISMISS_RECOMMENDATION' | 'FEEDBACK_RECOMMENDATION' | 'SET_PERMISSION_POLICY' | 'UPDATE_SUBTASKS';

export type CommandStatus =
  | 'queued' | 'delivered' | 'running' | 'succeeded' | 'failed' | 'expired' | 'cancelled' | 'denied';

export interface SessionCommand {
  command_id: string;
  type: CommandType;
  user_id?: string;
  device_id: string;
  source: 'web' | 'cli' | 'system' | 'voice_agent';
  session_id?: string | null;
  payload: Record<string, unknown>;
  status: CommandStatus;
  result?: Record<string, unknown> | null;
  created_at: string;
  expires_at?: string | null;
}

export type TaskStatus = 'queued' | 'planning' | 'waiting_for_approval' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface PlanStep { title?: string; step?: string; status?: string; [k: string]: unknown }

export interface DelegatedTask {
  id: string;
  session_id: string;
  instruction: string;
  status: TaskStatus;
  created_from: 'cli' | 'web' | 'recommendation';
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  permission_level: PermissionLevel;
  plan: PlanStep[];
  result?: { summary?: string; [k: string]: unknown } | null;
  evidence: string[];
  error?: string | null;
  recommendation_id?: string | null;
  revision: number;
}

export type ApprovalStatus = 'pending' | 'approved' | 'denied' | 'expired';

export interface ActionApproval {
  id: string;
  session_id: string;
  task_id: string;
  action: { summary?: string; tool?: string; command?: string; [k: string]: unknown };
  risk: string;
  requested_at: string;
  expires_at?: string | null;
  status: ApprovalStatus;
  approved_by?: string | null;
  why?: string | null;
  permission_level: PermissionLevel;
  scope?: string | null;
  revision: number;
}

export type ActionLevel = 'passive' | 'suggest' | 'recommend' | 'urgent';
export type RecommendationStatus = 'pending' | 'accepted' | 'dismissed' | 'expired' | 'superseded';

export interface ActionRecommendation {
  id: string;
  session_id: string;
  type: string;
  title: string;
  description: string;
  reason: string;
  evidence: string[];
  confidence: number;
  impact_estimate: string;
  requires_user_action: boolean;
  can_delegate: boolean;
  proposed_task?: string | null;
  level: ActionLevel;
  status: RecommendationStatus;
  created_at: string;
  expires_at?: string | null;
  feedback?: string | null;
  revision: number;
}

export type GoalState = 'not_started' | 'in_progress' | 'partially_complete' | 'likely_complete' | 'confirmed_complete';
export type SubtaskStatus = 'todo' | 'in_progress' | 'done';

export interface Subtask {
  id: string;
  session_id: string;
  title: string;
  status: SubtaskStatus;
  evidence: string[];
  position: number;
  origin: string;
  revision: number;
}

export interface GoalVersion {
  session_id: string;
  version: number;
  goal: string;
  effective_at: string;
  source: string;
  state: GoalState;
}

export interface ChatMessage {
  id: string;
  question: string;
  answer?: string | null;
  asked_at?: string;
  answered_at?: string | null;
  source?: string;
}

export interface Entity<T = unknown> {
  kind: string;
  id: string;
  revision: number;
  status?: string;
  data: T;
  updated_at?: string;
}

export interface FlowEvent {
  event_id: string;
  sequence: number;
  type: string;
  timestamp: string;
  data: Record<string, any>;
}

export interface Metrics {
  goal_alignment?: number | null;
  focus_continuity?: number | null;
  context_stability?: number | null;
  progress?: number | null;
  session_score?: number | null;
  context_switches?: number;
  intervention_count?: number;
  coverage?: number;
  confidence?: number;
  drift_state?: string;
  longest_focus_block?: number;
  [k: string]: unknown;
}

export interface CurrentActivity {
  activity?: string | null;
  task_phase?: string | null;
  alignment?: number | null;
  drift?: string | null;
  blocker?: string | null;
  category?: string | null;
}

export interface LiveView {
  session: SessionOut;
  presence: Presence;
  current: CurrentActivity;
  metrics: Metrics;
  efficiency?: Record<string, unknown>;
  latest_segment?: Record<string, unknown> | null;
  observer_health?: Record<string, unknown>;
  voice: { state: string; muted_until?: string | null };
  agent: { status: string; current_task?: string | null; pending_approvals: number };
  goal: { text: string; version: number; state: GoalState; subtasks: Subtask[] };
  recommendation: ActionRecommendation | null;
  tasks: DelegatedTask[];
  approvals: ActionApproval[];
  last_event_sequence: number;
  sync?: unknown;
}

export interface Page<T> { items: T[]; next_cursor?: string | null }

// Report: the contract lists sections but not exact field names, so every field is optional and read defensively.
export interface SessionReport {
  goal?: string;
  session?: Partial<SessionOut>;
  started_at?: string;
  ended_at?: string | null;
  duration_seconds?: number;
  metrics?: Metrics;
  score?: number | null;
  segments?: Array<Record<string, any>>;
  blockers?: Array<Record<string, any>>;
  drift_periods?: Array<Record<string, any>>;
  interventions?: Array<Record<string, any>>;
  recommendations?: Array<Record<string, any>>;
  human_vs_agent?: Record<string, any>;
  tasks?: Array<Record<string, any>>;
  approvals?: Array<Record<string, any>>;
  voice_interventions?: Array<Record<string, any>>;
  summary?: Record<string, any> | null;
  [k: string]: unknown;
}

export type ViewerFrame =
  | { type: 'ready'; session_id: string; last_sequence: number }
  | { type: 'event'; event: FlowEvent }
  | { type: 'command'; command: SessionCommand }
  | { type: 'presence'; presence: Presence; device_id?: string }
  | { type: 'ping' };

export type UserFrame =
  | { type: 'ready' }
  | { type: 'presence'; device_id: string; presence: Presence }
  | { type: 'approval'; approval: ActionApproval }
  | { type: 'session'; session: SessionOut }
  | { type: 'ping' };
