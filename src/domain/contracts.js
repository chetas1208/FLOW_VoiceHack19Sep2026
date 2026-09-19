/**
 * Shared data contracts between observer, analyzer, scoring, coach, API and UI.
 * Version this file when a breaking change is made; the server advertises
 * API_VERSION on /api/meta and stamps schemaVersion onto every persisted session.
 */
import { parse } from './schema.js';

export const API_VERSION = 2;
export const SCHEMA_VERSION = 2;

/** Activity classifications. Order matters for UI legends. */
export const CATEGORIES = ['core', 'supporting', 'unknown', 'drift', 'distraction', 'recovery'];

/** Categories that count as goal-aligned working time. */
export const ALIGNED_CATEGORIES = ['core', 'supporting', 'recovery'];

/** Categories that count as away-from-goal time. */
export const AWAY_CATEGORIES = ['drift', 'distraction'];

export const CATEGORY_LABELS = {
  core: 'Core task',
  supporting: 'Supporting task',
  unknown: 'Unknown',
  drift: 'Drifting',
  distraction: 'Distraction',
  recovery: 'Recovery',
  unobserved: 'Not observed',
};

/** Spec §04 timeline semantics. */
export const CATEGORY_COLORS = {
  core: '#a3e635',
  supporting: '#22d3ee',
  unknown: '#64748b',
  drift: '#fbbf24',
  distraction: '#fb7185',
  recovery: '#8b5cf6',
  unobserved: '#1e293b',
};

export const SESSION_STATUSES = ['live', 'paused', 'stopped'];

export const EVENT_TYPES = [
  'session.started',
  'session.paused',
  'session.resumed',
  'session.stopped',
  'observation.created',
  'metrics.updated',
  'drift.changed',
  'intervention.triggered',
  'intervention.queued',
  'intervention.speech_started',
  'intervention.speech_completed',
  'intervention.failed',
  'intervention.muted',
  'intervention.dismissed',
  'analyzer.status',
  'observer.status',
  'privacy.changed',
  'voice.changed',
  'report.updated',
  'session.deleted',
];

/** Coach state machine states (spec §06). */
export const COACH_STATES = ['FOCUSED', 'WATCHING', 'DRIFT_CANDIDATE', 'INTERVENE', 'RECOVERY', 'COOLDOWN'];

/** Intervention lifecycle stages we track end-to-end. */
export const INTERVENTION_STAGES = ['triggered', 'queued', 'speech_started', 'speech_completed', 'failed', 'muted', 'dismissed'];

export const SELF_REPORTED_OUTCOMES = ['completed', 'partial', 'not-completed', 'prefer-not-to-say'];

/** Apps excluded from observation by default. Content never reaches a model. */
export const DEFAULT_EXCLUDED_APPS = [
  '1Password',
  'Bitwarden',
  'Keychain Access',
  'Messages',
  'WhatsApp',
  'Signal',
  'Mail',
  'System Settings',
  'Tor Browser',
];

/**
 * The structured output every semantic analyzer provider must return.
 * Providers that cannot fill a field must omit it rather than invent a value.
 */
export const ClassificationSchema = {
  type: 'object',
  properties: {
    category: { type: 'string', enum: CATEGORIES },
    goalRelevance: { type: 'number', min: 0, max: 1, clamp: true, nullable: true },
    confidence: { type: 'number', min: 0, max: 1, clamp: true },
    confidenceCalibrated: { type: 'boolean', optional: true, default: false },
    evidence: { type: 'array', maxItems: 12, items: { type: 'string', maxLength: 400, truncate: true }, optional: true, default: [] },
    explanation: { type: 'string', maxLength: 800, truncate: true },
    taskContext: { type: 'string', maxLength: 80, truncate: true, optional: true, nullable: true },
    progressSignal: { type: 'string', maxLength: 300, truncate: true, optional: true, nullable: true },
  },
};

/** What the analyzer attaches after validation: provenance for the evidence explorer. */
export const AnalysisMetaSchema = {
  type: 'object',
  properties: {
    provider: { type: 'string', maxLength: 60 },
    model: { type: 'string', maxLength: 120, nullable: true },
    modality: { type: 'string', enum: ['metadata-only', 'vision-language', 'text-language'] },
    latencyMs: { type: 'number', min: 0, optional: true, nullable: true },
    usedScreenshot: { type: 'boolean' },
    screenshotRetention: { type: 'string', enum: ['not-captured', 'discarded-after-analysis', 'retained'] },
    degraded: { type: 'boolean', optional: true, default: false },
    note: { type: 'string', maxLength: 400, truncate: true, optional: true, nullable: true },
  },
};

export const ObservationInputSchema = {
  type: 'object',
  properties: {
    app: { type: 'string', minLength: 1, maxLength: 120 },
    title: { type: 'string', maxLength: 400, truncate: true, optional: true, default: '' },
    time: { type: 'isoDate', optional: true, nullable: true },
    simulated: { type: 'boolean', optional: true, default: false },
    screenshotPath: { type: 'string', maxLength: 1024, optional: true, nullable: true },
    classification: { type: 'any', optional: true, nullable: true },
  },
};

export const PrivacySettingsSchema = {
  type: 'object',
  properties: {
    excludedApps: { type: 'array', maxItems: 200, items: { type: 'string', minLength: 1, maxLength: 120 }, optional: true, nullable: true },
    screenshotsEnabled: { type: 'boolean', optional: true, nullable: true },
    retention: { type: 'string', enum: ['discard-after-analysis', 'retain'], optional: true, nullable: true },
    retentionMinutes: { type: 'number', min: 1, max: 10080, integer: true, clamp: true, optional: true, nullable: true },
    analysisLocation: { type: 'string', enum: ['metadata-only', 'local', 'cloud'], optional: true, nullable: true },
    cloudConsent: { type: 'boolean', optional: true, nullable: true },
  },
};

export const VoiceSettingsSchema = {
  type: 'object',
  properties: {
    enabled: { type: 'boolean', optional: true, nullable: true },
    voice: { type: 'string', maxLength: 60, optional: true, nullable: true },
    rate: { type: 'number', min: 120, max: 320, integer: true, clamp: true, optional: true, nullable: true },
    cooldownMinutes: { type: 'number', min: 1, max: 240, integer: true, clamp: true, optional: true, nullable: true },
    sustainedDriftSeconds: { type: 'number', min: 15, max: 1800, integer: true, clamp: true, optional: true, nullable: true },
    minConfidence: { type: 'number', min: 0, max: 1, clamp: true, optional: true, nullable: true },
  },
};

export const StartSessionSchema = {
  type: 'object',
  properties: {
    goal: { type: 'string', minLength: 3, maxLength: 400 },
    observe: { type: 'boolean', optional: true, default: false },
    screenshots: { type: 'boolean', optional: true, default: false },
    voice: { type: 'boolean', optional: true, default: false },
    simulated: { type: 'boolean', optional: true, default: false },
  },
};

export const validateClassification = (value) => parse(ClassificationSchema, value);
export const validateAnalysisMeta = (value) => parse(AnalysisMetaSchema, value);
