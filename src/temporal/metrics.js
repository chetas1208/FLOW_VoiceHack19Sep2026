/**
 * Duration-based session metrics.
 *
 * Every metric here is an engineered heuristic over observed screen metadata and
 * model interpretation. None of it measures productivity, attention, motivation
 * or any mental state, and the formulas are published alongside the numbers so a
 * user can disagree with them.
 */
import { ALIGNED_CATEGORIES, AWAY_CATEGORIES, CATEGORIES } from '../domain/contracts.js';
import { buildIntervals } from './intervals.js';

/** Aligned blocks shorter than this do not count toward focus continuity... */
export const FOCUS_BLOCK_TARGET_MS = 5 * 60 * 1000;
/** ...unless the session is short, in which case the threshold scales down to this floor. */
export const FOCUS_BLOCK_FLOOR_MS = 30 * 1000;
/** Context-switch density at which context stability reaches 0 (switches per observed hour). */
export const SWITCH_DENSITY_SATURATION = 30;

const WEIGHTS = { goalAlignment: 0.45, focusContinuity: 0.25, contextStability: 0.2, progressSignal: 0.1 };

const median = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
};

const pct = (x) => (x === null || x === undefined ? null : Math.round(x * 100));

/**
 * A task context is the coarse "what kind of work is this" bucket. Switching
 * between coding and its own documentation is legitimate and must not be
 * punished as hard as switching to an unrelated app.
 */
export function taskContextOf(interval) {
  if (interval.taskContext) return interval.taskContext;
  if (!interval.app) return null;
  return `${interval.app}:${interval.category}`;
}

/** Contiguous runs of goal-aligned intervals, uninterrupted by away/unknown/unobserved time. */
export function alignedBlocks(intervals) {
  const blocks = [];
  let current = null;
  for (const i of intervals) {
    if (i.category === 'paused') continue; // a pause suspends, it does not break, a block
    if (ALIGNED_CATEGORIES.includes(i.category)) {
      if (current) {
        current.durationMs += i.durationMs;
        current.endedAt = i.endedAt;
        current.intervalIds.push(i.id);
      } else {
        current = { startedAt: i.startedAt, endedAt: i.endedAt, durationMs: i.durationMs, intervalIds: [i.id] };
      }
    } else if (current) {
      blocks.push(current);
      current = null;
    }
  }
  if (current) blocks.push(current);
  return blocks;
}

/**
 * Compute duration-based metrics for a session.
 * Returns null-valued metrics (never fabricated numbers) when evidence is absent.
 */
export function computeMetrics(session, options = {}) {
  const timeline = buildIntervals(session, options);
  const { intervals, observedMs, unobservedMs, pausedMs, coverage } = timeline;

  const durationsByCategory = Object.fromEntries([...CATEGORIES, 'unobserved', 'paused'].map((c) => [c, 0]));
  for (const i of intervals) durationsByCategory[i.category] = (durationsByCategory[i.category] || 0) + i.durationMs;

  const alignedMs = ALIGNED_CATEGORIES.reduce((n, c) => n + durationsByCategory[c], 0);
  const awayMs = AWAY_CATEGORIES.reduce((n, c) => n + durationsByCategory[c], 0);
  const unknownMs = durationsByCategory.unknown;
  const classifiedMs = alignedMs + awayMs;

  const blocks = alignedBlocks(intervals);
  const blockThresholdMs = Math.max(FOCUS_BLOCK_FLOOR_MS, Math.min(FOCUS_BLOCK_TARGET_MS, Math.round(observedMs * 0.15)));
  const qualifyingMs = blocks.filter((b) => b.durationMs >= blockThresholdMs).reduce((n, b) => n + b.durationMs, 0);

  const workIntervals = intervals.filter((i) => i.category !== 'paused' && i.category !== 'unobserved');
  let contextSwitches = 0;
  const switchPoints = [];
  for (let i = 1; i < workIntervals.length; i += 1) {
    const prev = taskContextOf(workIntervals[i - 1]);
    const next = taskContextOf(workIntervals[i]);
    if (prev && next && prev !== next) {
      contextSwitches += 1;
      switchPoints.push({ at: workIntervals[i].startedAt, from: prev, to: next });
    }
  }
  const observedHours = observedMs / 3_600_000;
  const switchDensityPerHour = observedHours > 0 ? contextSwitches / observedHours : null;

  const progressSignals = intervals
    .filter((i) => i.progressSignals?.length)
    .flatMap((i) => i.progressSignals.map((text) => ({ at: i.startedAt, intervalId: i.id, text })));

  const goalAlignment = classifiedMs > 0 ? alignedMs / classifiedMs : null;
  const focusContinuity = alignedMs > 0 ? qualifyingMs / alignedMs : null;
  const contextStability =
    switchDensityPerHour === null ? null : Math.max(0, Math.min(1, 1 - switchDensityPerHour / SWITCH_DENSITY_SATURATION));
  // Progress is evidence-gated: absence of signals is not evidence of no progress, so it
  // only contributes to the score once at least one signal exists.
  const progressSignal = progressSignals.length ? Math.min(1, progressSignals.length / 3) : null;

  const components = { goalAlignment, focusContinuity, contextStability, progressSignal };
  const available = Object.entries(components).filter(([, v]) => v !== null);
  const weightSum = available.reduce((n, [k]) => n + WEIGHTS[k], 0);
  const sessionScore = weightSum > 0 ? Math.round(100 * available.reduce((n, [k, v]) => n + WEIGHTS[k] * v, 0) / weightSum) : null;

  // Confidence: how much of the session we actually saw, weighted by how sure the
  // analyzer was about what it saw.
  const weightedConfidence =
    observedMs > 0 ? workIntervals.reduce((n, i) => n + (i.confidence || 0) * i.durationMs, 0) / observedMs : null;
  const confidence = weightedConfidence === null || coverage === null ? null : weightedConfidence * coverage;

  const band =
    sessionScore === null ? 'No data'
    : sessionScore >= 80 ? 'Strong alignment'
    : sessionScore >= 60 ? 'Mostly aligned'
    : sessionScore >= 40 ? 'Mixed'
    : 'Fragmented';

  return {
    schema: 'flow.metrics.v2',
    computedAt: new Date().toISOString(),
    boundedAt: timeline.boundedAt,
    samplePeriodMs: timeline.samplePeriodMs,

    // Percentages for display (0-100), null when there is no evidence.
    goalAlignment: pct(goalAlignment),
    focusContinuity: pct(focusContinuity),
    contextStability: pct(contextStability),
    progressSignal: pct(progressSignal),
    sessionScore,
    band,

    confidence: confidence === null ? null : Math.round(confidence * 100) / 100,
    uncertainty: confidence === null ? null : Math.round((1 - confidence) * 100) / 100,
    coverage: coverage === null ? null : Math.round(coverage * 100) / 100,

    durationsMs: { ...durationsByCategory, aligned: alignedMs, away: awayMs, classified: classifiedMs, observed: observedMs, unobserved: unobservedMs, paused: pausedMs },
    shares: {
      aligned: observedMs > 0 ? pct(alignedMs / observedMs) : null,
      away: observedMs > 0 ? pct(awayMs / observedMs) : null,
      unknown: observedMs > 0 ? pct(unknownMs / observedMs) : null,
      unobservedOfSession: observedMs + unobservedMs > 0 ? pct(unobservedMs / (observedMs + unobservedMs)) : null,
    },

    focus: {
      blockThresholdMs,
      blockCount: blocks.length,
      qualifyingBlockCount: blocks.filter((b) => b.durationMs >= blockThresholdMs).length,
      longestBlockMs: blocks.length ? Math.max(...blocks.map((b) => b.durationMs)) : 0,
      medianBlockMs: median(blocks.map((b) => b.durationMs)),
      blocks,
    },

    contextSwitches,
    switchDensityPerHour: switchDensityPerHour === null ? null : Math.round(switchDensityPerHour * 10) / 10,
    switchPoints,
    progressSignals,

    method: {
      label: 'Engineered heuristic — not a validated measure of productivity, attention, or any mental state.',
      goalAlignment: 'aligned time ÷ confidently classified time (core + supporting + recovery vs. drift + distraction). Unknown and unobserved time is excluded from both sides.',
      focusContinuity: `time in uninterrupted aligned blocks of at least ${Math.round(blockThresholdMs / 1000)}s ÷ total aligned time.`,
      contextStability: `1 − (task-context switches per observed hour ÷ ${SWITCH_DENSITY_SATURATION}), clamped to 0–1. Switching between related contexts (code ↔ its docs) counts as one context and is not penalised.`,
      progressSignal: 'evidence-gated: min(1, number of observed progress signals ÷ 3). Null when no signal was observed — absence of a signal is not evidence of no progress.',
      sessionScore: `weighted mean of the available components (${Object.entries(WEIGHTS).map(([k, v]) => `${k} ${v}`).join(', ')}), renormalised over whichever components have evidence.`,
      confidence: 'mean analyzer confidence weighted by interval duration, multiplied by observation coverage (observed ÷ observable time).',
    },
    timeline: intervals,
  };
}

/** Human-readable duration, e.g. "1h 04m" / "7m 30s". */
export function formatDuration(msValue) {
  const total = Math.max(0, Math.round(msValue / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}
