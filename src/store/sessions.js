/**
 * Session persistence.
 *
 * Local JSON with atomic writes and owner-only permissions. A `schemaVersion`
 * on every record drives forward migrations, so an existing v1 data file from
 * the previous FLOW build keeps working instead of being silently dropped.
 */
import fs from 'node:fs';
import path from 'node:path';
import { SCHEMA_VERSION } from '../domain/contracts.js';
import { defaultPrivacySettings } from '../observe/privacy.js';
import { blankMemory } from '../analyze/memory.js';
import { blankCoach, DEFAULTS as COACH_DEFAULTS } from '../coach/state-machine.js';
import { computeMetrics } from '../temporal/metrics.js';

/** v1 → v2: split flat fields into capture/privacy/voice/coach, add seq + pauses. */
function migrateV1(old) {
  const started = old.startedAt || new Date().toISOString();
  const events = (old.events || []).map((e, i) => ({
    ...e,
    seq: i + 1,
    evidence: e.evidence || (e.reason ? [`Active application: ${e.app}`] : []),
    taskContext: e.taskContext ?? null,
    progressSignal: null,
    goalRelevance: e.alignment ?? null,
    analysis: e.analysis || {
      provider: e.source === 'manual' ? 'manual' : 'heuristic',
      model: null,
      modality: 'metadata-only',
      usedScreenshot: false,
      screenshotRetention: 'not-captured',
      degraded: false,
      note: 'Migrated from a FLOW v1 session: this observation predates interval-based analysis.',
    },
  }));

  return {
    schemaVersion: 2,
    id: old.id,
    goal: old.goal,
    createdAt: started,
    startedAt: started,
    endedAt: old.endedAt || null,
    status: old.status || 'stopped',
    mode: old.mode || 'manual',
    simulated: false,
    samplePeriodMs: 5000,
    seq: events.length,
    events,
    pauses: [],
    interventions: (old.interventions || []).map((i) => ({
      id: i.id,
      sessionId: old.id,
      triggeredAt: i.time,
      stage: 'speech_completed',
      transcript: i.transcript,
      reason: i.reason,
      observationId: i.observationId || null,
      evidence: [],
      driftStartedAt: null,
      driftSeconds: null,
      confidence: null,
      dismissed: false,
      lifecycle: [{ stage: 'triggered', at: i.time }],
      outcome: null,
    })),
    capture: { enabled: false, screenshots: false, permission: 'unknown', lastCaptureAt: null, lastError: null, status: 'off' },
    privacy: { ...defaultPrivacySettings(), excludedApps: old.privacy?.excludedApps || defaultPrivacySettings().excludedApps },
    voice: { enabled: !!old.voiceEnabled, voice: null, rate: 185, ...COACH_DEFAULTS },
    coach: blankCoach(started),
    memory: blankMemory(),
    metrics: null,
    report: null,
    analyzer: null,
    lastObservationAt: old.lastObservationAt || null,
    migratedFrom: 'v1',
  };
}

export const MIGRATIONS = [{ from: 1, to: 2, apply: migrateV1 }];

export function migrate(record) {
  let s = record;
  let version = s.schemaVersion || 1;
  while (version < SCHEMA_VERSION) {
    const m = MIGRATIONS.find((x) => x.from === version);
    if (!m) break;
    s = m.apply(s);
    version = m.to;
  }
  // Recompute derived state so migrated sessions get interval-based metrics.
  if (s.schemaVersion === SCHEMA_VERSION && s.events?.length) {
    try {
      s.metrics = computeMetrics(s);
    } catch { /* leave metrics null rather than fail the load */ }
  }
  return s;
}

export function createStore({ file }) {
  const sessions = new Map();
  let loadError = null;

  function load() {
    try {
      const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
      for (const record of Array.isArray(raw) ? raw : []) {
        try {
          const migrated = migrate(record);
          sessions.set(migrated.id, migrated);
        } catch (err) {
          loadError = `Skipped an unreadable session record: ${err.message}`;
        }
      }
    } catch (err) {
      if (err.code !== 'ENOENT') loadError = `Could not read ${file}: ${err.message}`;
    }
  }

  function save() {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify([...sessions.values()], null, 2), { mode: 0o600 });
    fs.renameSync(tmp, file);
    try {
      fs.chmodSync(file, 0o600);
    } catch { /* best effort on exotic filesystems */ }
  }

  load();

  return {
    file,
    get loadError() {
      return loadError;
    },
    all: () => [...sessions.values()],
    get: (id) => sessions.get(id),
    has: (id) => sessions.has(id),
    set(session) {
      sessions.set(session.id, session);
      save();
      return session;
    },
    /** Hard-delete a session and every artefact it references. */
    delete(id) {
      const s = sessions.get(id);
      if (!s) return false;
      sessions.delete(id);
      save();
      return true;
    },
    deleteAll() {
      const count = sessions.size;
      sessions.clear();
      save();
      return count;
    },
    save,
  };
}
