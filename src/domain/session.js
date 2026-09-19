/**
 * Session aggregate: the single place session state is mutated.
 *
 * Every mutation appends a monotonically-sequenced event, so a client that
 * disconnects can ask for everything after the last sequence number it saw and
 * reconcile without replaying the whole session.
 */
import { randomUUID } from 'node:crypto';
import { SCHEMA_VERSION, SELF_REPORTED_OUTCOMES } from './contracts.js';
import { defaultPrivacySettings } from '../observe/privacy.js';
import { blankMemory, rememberObservation } from '../analyze/memory.js';
import { blankCoach, DEFAULTS as COACH_DEFAULTS } from '../coach/state-machine.js';
import { computeMetrics, formatDuration } from '../temporal/metrics.js';
import { analyseInterventionOutcome } from '../coach/index.js';
import { buildIntervals } from '../temporal/intervals.js';

export const now = () => new Date().toISOString();

export function createSession(goal, options = {}) {
  if (typeof goal !== 'string' || !goal.trim()) throw Object.assign(new Error('A session goal is required'), { status: 400 });
  const started = options.startedAt || now();
  return {
    schemaVersion: SCHEMA_VERSION,
    id: options.id || `ses_${randomUUID().slice(0, 8)}`,
    goal: goal.trim(),
    createdAt: started,
    startedAt: started,
    endedAt: null,
    status: 'live',
    mode: options.mode || 'manual',
    simulated: !!options.simulated,
    samplePeriodMs: options.samplePeriodMs || 5000,
    seq: 0,
    events: [],
    pauses: [],
    interventions: [],
    capture: {
      enabled: !!options.observe,
      screenshots: !!options.screenshots,
      permission: 'unknown',
      lastCaptureAt: null,
      lastError: null,
      status: options.observe ? 'starting' : 'off',
    },
    privacy: { ...defaultPrivacySettings(), ...(options.privacy || {}), screenshotsEnabled: !!options.screenshots },
    voice: { enabled: !!options.voice, voice: null, rate: 185, ...COACH_DEFAULTS },
    coach: blankCoach(started),
    memory: blankMemory(),
    metrics: null,
    report: null,
    analyzer: null,
    lastObservationAt: null,
  };
}

/** Append an event with a session-scoped sequence number. */
export function appendEvent(session, event) {
  session.seq += 1;
  const full = { id: event.id || randomUUID(), seq: session.seq, time: event.time || now(), ...event };
  full.seq = session.seq;
  session.events.push(full);
  return full;
}

/** True when this observation duplicates the immediately-preceding one. */
export function isDuplicateObservation(session, observation) {
  const last = session.events.filter((e) => e.type === 'observation.created').at(-1);
  if (!last) return false;
  return last.app === observation.app && last.title === observation.title && last.time === observation.time;
}

/**
 * Record a privacy-filtered, analyzed observation.
 * @returns {object} the appended observation event
 */
export function recordObservation(session, { observation, classification, meta }) {
  if (session.status !== 'live') throw Object.assign(new Error('Session is not live'), { status: 409 });

  const event = appendEvent(session, {
    type: 'observation.created',
    time: observation.time || now(),
    app: observation.app,
    title: observation.title,
    titleWithheld: !!observation.titleWithheld,
    redactions: observation.redactions || [],
    simulated: !!observation.simulated,
    category: classification.category,
    goalRelevance: classification.goalRelevance ?? null,
    confidence: classification.confidence,
    confidenceCalibrated: !!classification.confidenceCalibrated,
    evidence: classification.evidence || [],
    reason: classification.explanation,
    taskContext: classification.taskContext || null,
    progressSignal: classification.progressSignal || null,
    analysis: meta,
  });

  session.lastObservationAt = event.time;
  session.memory = rememberObservation(session.memory, { observation: { ...observation, time: event.time }, classification });
  session.metrics = computeMetrics(session);
  return event;
}

export function pauseSession(session) {
  if (session.status !== 'live') throw Object.assign(new Error('Session is not live'), { status: 409 });
  session.status = 'paused';
  session.pauses.push({ startedAt: now(), endedAt: null });
  session.coach = { ...session.coach, driftSince: null, candidateSince: null, state: 'FOCUSED', since: now() };
  session.capture.status = 'paused';
  session.metrics = computeMetrics(session);
  return appendEvent(session, { type: 'session.paused' });
}

export function resumeSession(session) {
  if (session.status !== 'paused') throw Object.assign(new Error('Session is not paused'), { status: 409 });
  const open = session.pauses.at(-1);
  if (open && !open.endedAt) open.endedAt = now();
  session.status = 'live';
  session.capture.status = session.capture.enabled ? 'observing' : 'off';
  session.metrics = computeMetrics(session);
  return appendEvent(session, { type: 'session.resumed' });
}

export function stopSession(session) {
  if (session.status === 'stopped') return null;
  const open = session.pauses.at(-1);
  if (open && !open.endedAt) open.endedAt = now();
  session.status = 'stopped';
  session.endedAt = now();
  session.capture.status = 'off';
  session.capture.enabled = false;
  session.coach = { ...session.coach, state: 'FOCUSED', driftSince: null, candidateSince: null };
  session.metrics = computeMetrics(session);
  session.report = buildReport(session);
  return appendEvent(session, { type: 'session.stopped' });
}

/** Friction patterns, derived only from observed intervals. Max three. */
function frictionPatterns(metrics, intervals) {
  const out = [];
  const d = metrics.durationsMs;

  if (metrics.switchDensityPerHour !== null && metrics.switchDensityPerHour > 12) {
    out.push({
      pattern: 'High context-switch density',
      detail: `${metrics.contextSwitches} task-context switches across ${formatDuration(d.observed)} of observed time (${metrics.switchDensityPerHour}/hour).`,
      evidence: metrics.switchPoints.slice(0, 4).map((s) => `${new Date(s.at).toLocaleTimeString()} · ${s.from} → ${s.to}`),
    });
  }

  const awayRuns = [];
  let run = null;
  for (const i of intervals) {
    if (['drift', 'distraction'].includes(i.category)) {
      run = run ? { ...run, endedAt: i.endedAt, durationMs: run.durationMs + i.durationMs, apps: [...new Set([...run.apps, i.app])] } : { startedAt: i.startedAt, endedAt: i.endedAt, durationMs: i.durationMs, apps: [i.app] };
    } else if (run) {
      awayRuns.push(run);
      run = null;
    }
  }
  if (run) awayRuns.push(run);
  const longestAway = awayRuns.sort((a, b) => b.durationMs - a.durationMs)[0];
  if (longestAway && longestAway.durationMs > 120000) {
    out.push({
      pattern: 'Sustained time away from the goal',
      detail: `The longest uninterrupted stretch away from the goal lasted ${formatDuration(longestAway.durationMs)} in ${longestAway.apps.filter(Boolean).join(', ') || 'an unnamed app'}.`,
      evidence: [`${new Date(longestAway.startedAt).toLocaleTimeString()} – ${new Date(longestAway.endedAt).toLocaleTimeString()}`],
    });
  }

  if (metrics.shares.unknown !== null && metrics.shares.unknown > 35) {
    out.push({
      pattern: 'Large share of unclassifiable activity',
      detail: `${metrics.shares.unknown}% of observed time could not be linked to the goal with confidence. This is a limit of the analysis, not a judgement about the work.`,
      evidence: intervals.filter((i) => i.category === 'unknown').slice(0, 3).map((i) => `${i.app || 'unknown app'} · ${formatDuration(i.durationMs)}`),
    });
  }

  if (metrics.focus.blockCount > 0 && metrics.focus.medianBlockMs !== null && metrics.focus.medianBlockMs < 120000 && metrics.focus.blockCount > 2) {
    out.push({
      pattern: 'Aligned work arrived in short fragments',
      detail: `${metrics.focus.blockCount} aligned blocks with a median length of ${formatDuration(metrics.focus.medianBlockMs)}.`,
      evidence: [`Longest block: ${formatDuration(metrics.focus.longestBlockMs)}`],
    });
  }

  return out.slice(0, 3);
}

/** One concrete, testable behaviour for next time — never generic motivation. */
function nextExperiment(metrics, friction) {
  const top = friction[0]?.pattern;
  if (top === 'High context-switch density') {
    return {
      experiment: 'Batch the research. Next session, keep a scratch list of questions while coding and answer them in one documentation pass instead of switching per question.',
      measure: `Context-switch density — this session was ${metrics.switchDensityPerHour}/hour. Watch whether it falls below ${Math.max(4, Math.round(metrics.switchDensityPerHour * 0.6))}/hour.`,
    };
  }
  if (top === 'Sustained time away from the goal') {
    return {
      experiment: 'Set the coach cooldown to 5 minutes for the next session so a sustained drift is flagged sooner, and note what pulled you away when it fires.',
      measure: 'Length of the longest uninterrupted stretch away from the goal.',
    };
  }
  if (top === 'Large share of unclassifiable activity') {
    return {
      experiment: 'Enable screenshot capture (or a local vision model) for one session so activity can be judged from screen content instead of window titles alone.',
      measure: `Share of observed time classified as unknown — this session was ${metrics.shares.unknown}%.`,
    };
  }
  if (top === 'Aligned work arrived in short fragments') {
    return {
      experiment: 'Protect one 25-minute block at the start of the next session with notifications off, and start it on the hardest part of the goal.',
      measure: `Longest aligned block — this session was ${formatDuration(metrics.focus.longestBlockMs)}.`,
    };
  }
  return {
    experiment: 'State the goal more narrowly next time (one testable outcome rather than a theme) so classification has something concrete to match against.',
    measure: `Share of observed time classified as unknown — this session was ${metrics.shares.unknown ?? 'not measurable'}%.`,
  };
}

export function buildReport(session) {
  const metrics = computeMetrics(session);
  const { intervals } = buildIntervals(session);
  const friction = frictionPatterns(metrics, intervals);
  const durationMs = new Date(session.endedAt || now()) - new Date(session.startedAt);

  return {
    schema: 'flow.report.v2',
    generatedAt: now(),
    sessionId: session.id,
    goal: session.goal,
    startedAt: session.startedAt,
    endedAt: session.endedAt,
    durationMs,
    durationLabel: formatDuration(durationMs),
    selfReportedOutcome: session.report?.selfReportedOutcome ?? null,
    metrics,
    timeline: intervals,
    interventions: session.interventions.map((i) => ({ ...i, outcome: analyseInterventionOutcome(i, intervals) })),
    friction,
    nextExperiment: nextExperiment(metrics, friction),
    observedFacts: {
      observationCount: session.events.filter((e) => e.type === 'observation.created').length,
      simulatedObservationCount: session.events.filter((e) => e.type === 'observation.created' && e.simulated).length,
      interventionCount: session.interventions.length,
      pauseCount: session.pauses.length,
      analyzers: [...new Set(session.events.filter((e) => e.analysis).map((e) => `${e.analysis.provider}${e.analysis.model ? ` (${e.analysis.model})` : ''}`))],
      screenshotsUsed: session.events.some((e) => e.analysis?.usedScreenshot),
    },
    limitations: [
      'Durations come from observation intervals, not continuous recording. Time with no observation is reported separately as unobserved and is never attributed to an activity.',
      'Classifications are a model or heuristic interpretation of screen metadata. They can be wrong, and confidence values are uncalibrated estimates rather than probabilities.',
      'Scores are engineered heuristics for reflection. They are not a measure of productivity, attention, motivation, or any mental state.',
      'Intervention comparisons are temporal associations, not causal evidence.',
      session.simulated ? 'This session contains simulated observations generated by the demo script, not real screen observation.' : null,
    ].filter(Boolean),
  };
}

export function setOutcome(session, outcome) {
  if (session.status !== 'stopped') throw Object.assign(new Error('Stop the session before recording an outcome'), { status: 409 });
  if (!SELF_REPORTED_OUTCOMES.includes(outcome)) throw Object.assign(new Error(`Outcome must be one of: ${SELF_REPORTED_OUTCOMES.join(', ')}`), { status: 400 });
  session.report = session.report || buildReport(session);
  session.report.selfReportedOutcome = outcome;
  return appendEvent(session, { type: 'report.updated', outcome });
}

/** Summary row for the sessions list — never ships the full event log. */
export function summarise(session) {
  const { events, memory, report, ...rest } = session;
  return {
    ...rest,
    observationCount: events.filter((e) => e.type === 'observation.created').length,
    interventionCount: session.interventions.length,
    durationMs: new Date(session.endedAt || Date.now()) - new Date(session.startedAt),
    hasReport: !!report,
  };
}
