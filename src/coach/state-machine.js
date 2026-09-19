/**
 * Voice coach state machine (spec §06).
 *
 *   FOCUSED ──weakening──▶ WATCHING ──sustained + confident──▶ DRIFT_CANDIDATE
 *                                                                    │
 *                              task boundary OR hard threshold       ▼
 *                                                               INTERVENE
 *                                                                    │
 *                  user returns ──▶ RECOVERY ──▶ FOCUSED             ▼
 *                  dismiss/mute ─────────────────────────────▶ COOLDOWN
 *
 * Pure and time-injected so every branch is unit-testable without waiting.
 */
import { ALIGNED_CATEGORIES, AWAY_CATEGORIES } from '../domain/contracts.js';

export const DEFAULTS = {
  sustainedDriftSeconds: 90,
  hardDriftMultiplier: 2, // intervene without a task boundary after this × sustained
  minConfidence: 0.7,
  cooldownMinutes: 12,
};

const ms = (t) => new Date(t).getTime();

export function blankCoach(now = new Date().toISOString()) {
  return {
    state: 'FOCUSED',
    since: now,
    driftSince: null,
    candidateSince: null,
    cooldownUntil: null,
    muteUntil: null,
    lastInterventionAt: null,
    lastBoundaryAt: null,
    interventionCount: 0,
    suppressedReason: null,
  };
}

const isAway = (c) => AWAY_CATEGORIES.includes(c);
const isAligned = (c) => ALIGNED_CATEGORIES.includes(c);

/**
 * Advance the machine given the newest observation.
 *
 * @param {object} coach   current coach state (mutated copy returned)
 * @param {object} input   { category, confidence, time, appChanged, voiceEnabled, settings }
 * @returns {{coach: object, transition: string|null, intervene: boolean, reason: string|null}}
 */
export function step(coach, input) {
  const s = { ...DEFAULTS, ...(input.settings || {}) };
  const now = input.time;
  const next = { ...coach };
  const from = coach.state;
  let intervene = false;
  let reason = null;
  next.suppressedReason = null;

  const muted = next.muteUntil && ms(now) < ms(next.muteUntil);
  const cooling = next.cooldownUntil && ms(now) < ms(next.cooldownUntil);
  if (input.appChanged) next.lastBoundaryAt = now;

  const setState = (state) => {
    if (next.state !== state) {
      next.state = state;
      next.since = now;
    }
  };

  if (isAligned(input.category)) {
    // Returning to the goal after being away is recovery, then steady focus.
    const wasAway = from === 'WATCHING' || from === 'DRIFT_CANDIDATE' || from === 'INTERVENE' || coach.driftSince;
    next.driftSince = null;
    next.candidateSince = null;
    if (cooling) setState('COOLDOWN');
    else if (wasAway) setState('RECOVERY');
    else setState('FOCUSED');
    return { coach: next, transition: from === next.state ? null : `${from}→${next.state}`, intervene, reason };
  }

  if (!isAway(input.category)) {
    // Unknown: uncertainty rose. Hold, never escalate, never intervene.
    if (from === 'DRIFT_CANDIDATE') {
      next.candidateSince = null;
      next.suppressedReason = 'Confidence dropped to unknown before intervening, so the coach stayed silent.';
      setState('WATCHING');
    } else if (from === 'RECOVERY') {
      setState('FOCUSED');
    }
    return { coach: next, transition: from === next.state ? null : `${from}→${next.state}`, intervene, reason };
  }

  // --- away from the goal ---
  next.driftSince ??= now;
  const driftMs = ms(now) - ms(next.driftSince);
  const sustainedMs = s.sustainedDriftSeconds * 1000;
  const confident = (input.confidence ?? 0) >= s.minConfidence;

  if (from === 'FOCUSED' || from === 'RECOVERY' || from === 'COOLDOWN') setState('WATCHING');

  if (next.state === 'WATCHING') {
    if (driftMs >= sustainedMs && confident) {
      next.candidateSince = now;
      setState('DRIFT_CANDIDATE');
    } else if (driftMs >= sustainedMs && !confident) {
      next.suppressedReason = `Drift has lasted ${Math.round(driftMs / 1000)}s but confidence is ${(input.confidence ?? 0).toFixed(2)}, below the ${s.minConfidence} threshold. Staying silent.`;
    }
  }

  if (next.state === 'DRIFT_CANDIDATE') {
    if (!confident) {
      next.candidateSince = null;
      next.suppressedReason = 'Confidence fell below the threshold, so the queued intervention was cancelled.';
      setState('WATCHING');
    } else if (!input.voiceEnabled) {
      next.suppressedReason = 'Voice coaching is disabled, so no spoken intervention was delivered.';
    } else if (muted) {
      next.suppressedReason = `Coach is muted until ${next.muteUntil}.`;
    } else if (cooling) {
      next.suppressedReason = `Cooldown is active until ${next.cooldownUntil}; the coach will not interrupt again yet.`;
    } else {
      // Prefer a task boundary; fall back to a hard threshold so we never stay
      // silent forever when the user never switches app.
      const atBoundary = !!input.appChanged;
      const hardThreshold = driftMs >= sustainedMs * s.hardDriftMultiplier;
      if (atBoundary || hardThreshold) {
        intervene = true;
        reason = atBoundary
          ? `Sustained drift for ${Math.round(driftMs / 1000)}s at confidence ${(input.confidence ?? 0).toFixed(2)}; an application switch offered a natural task boundary.`
          : `Sustained drift for ${Math.round(driftMs / 1000)}s at confidence ${(input.confidence ?? 0).toFixed(2)}, past the hard threshold of ${Math.round((sustainedMs * s.hardDriftMultiplier) / 1000)}s.`;
        next.state = 'INTERVENE';
        next.since = now;
        next.lastInterventionAt = now;
        next.interventionCount += 1;
        next.cooldownUntil = new Date(ms(now) + s.cooldownMinutes * 60000).toISOString();
        next.candidateSince = null;
      } else {
        next.suppressedReason = 'Waiting for a natural task boundary before interrupting.';
      }
    }
  }

  return { coach: next, transition: from === next.state ? null : `${from}→${next.state}`, intervene, reason };
}

/**
 * Compose the spoken line.
 * References the task and offers a choice. Never evaluates the person.
 */
export function composeMessage({ goal, awayMinutes, lastAlignedContext }) {
  const anchor = lastAlignedContext ? `You were working on ${lastAlignedContext}` : `Your session goal is "${goal}"`;
  const howLong =
    awayMinutes >= 1 ? ` about ${Math.round(awayMinutes)} minute${Math.round(awayMinutes) === 1 ? '' : 's'} ago` : ' a moment ago';
  return `${anchor}${howLong}. Want to head back to it?`;
}
